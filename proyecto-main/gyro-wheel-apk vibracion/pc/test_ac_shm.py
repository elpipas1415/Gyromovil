"""Pruebas del lector de telemetría y del protocolo UDP.

Se ejecutan sin Assetto Corsa y sin ViGEmBus: el test crea sus propias páginas
de memoria compartida con nombres distintos (``Local\\gyrotest_acpmf_*``) y
comprueba que el lector, los tiempos, el delta y el FFB reaccionan.

    python -m unittest -v test_ac_shm
"""
from __future__ import annotations

import ctypes
import os
import sys
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import ac_shm
from ac_shm import AcSharedMemory, Telemetry
from server import parse_control, telemetry_packet

_PAGE_READWRITE = 0x04
_FILE_MAP_ALL_ACCESS = 0x000F001F
_INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value
_MAPPING_SIZE = 2048
# Prefijo único por proceso: evita chocar con Assetto Corsa real o con otra
# ejecución de las pruebas (las páginas con nombre son de toda la sesión).
_PREFIX = rf"Local\gyrotest_{os.getpid()}_acpmf"

_kernel32 = ctypes.windll.kernel32
_kernel32.CreateFileMappingW.argtypes = [
    ctypes.c_void_p, ctypes.c_void_p, ctypes.c_uint32,
    ctypes.c_uint32, ctypes.c_uint32, ctypes.c_wchar_p,
]
_kernel32.CreateFileMappingW.restype = ctypes.c_void_p
_kernel32.MapViewOfFile.argtypes = [
    ctypes.c_void_p, ctypes.c_uint32, ctypes.c_uint32,
    ctypes.c_uint32, ctypes.c_size_t,
]
_kernel32.MapViewOfFile.restype = ctypes.c_void_p
_kernel32.UnmapViewOfFile.argtypes = [ctypes.c_void_p]
_kernel32.CloseHandle.argtypes = [ctypes.c_void_p]


class FakeSharedMemory:
    """Crea las tres páginas que leería AC, pero con un prefijo de prueba."""

    def __init__(self) -> None:
        self._pages: dict[str, tuple[int, int]] = {}
        self.physics = ac_shm._PageFilePhysics()
        self.graphics = ac_shm._PageFileGraphics()
        self.static = ac_shm._PageFileStatic()
        for suffix in ("physics", "graphics", "static"):
            name = f"{_PREFIX}_{suffix}"
            handle = _kernel32.CreateFileMappingW(
                _INVALID_HANDLE_VALUE, None, _PAGE_READWRITE, 0, _MAPPING_SIZE, name
            )
            if not handle:
                raise OSError(ctypes.get_last_error(), f"CreateFileMappingW({name})")
            view = _kernel32.MapViewOfFile(handle, _FILE_MAP_ALL_ACCESS, 0, 0, _MAPPING_SIZE)
            if not view:
                _kernel32.CloseHandle(handle)
                raise OSError(ctypes.get_last_error(), f"MapViewOfFile({name})")
            ctypes.memset(view, 0, _MAPPING_SIZE)
            self._pages[suffix] = (handle, view)

    def _write(self, suffix: str, obj: ctypes.Structure) -> None:
        _handle, view = self._pages[suffix]
        ctypes.memset(view, 0, _MAPPING_SIZE)
        ctypes.memmove(view, ctypes.byref(obj), ctypes.sizeof(obj))

    def publish(self) -> None:
        self._write("physics", self.physics)
        self._write("graphics", self.graphics)
        self._write("static", self.static)

    def close(self) -> None:
        for handle, view in self._pages.values():
            _kernel32.UnmapViewOfFile(view)
            _kernel32.CloseHandle(handle)
        self._pages.clear()


class TelemetryReaderTest(unittest.TestCase):
    def setUp(self) -> None:
        self.shared = FakeSharedMemory()
        self.shared.static.maxRpm = 8000
        for i in range(4):
            self.shared.static.tyreRadius[i] = 0.33
        self.shared.static.carModel = "ks_testcar"
        self.shared.static.track = "test_track"

        self.shared.graphics.status = ac_shm.AC_LIVE
        self.shared.graphics.iCurrentTime = 61234
        self.shared.graphics.iLastTime = 90000
        self.shared.graphics.iBestTime = 88000
        self.shared.graphics.iDeltaLapTime = 250
        self.shared.graphics.isDeltaPositive = 1
        self.shared.graphics.isValidLap = 1

        self.shared.physics.gear = 3
        self.shared.physics.rpms = 6000
        self.shared.physics.speedKmh = 120.0
        for i in range(4):
            self.shared.physics.suspensionTravel[i] = 0.02
            self.shared.physics.wheelAngularSpeed[i] = (120.0 / 3.6) / 0.33
        self.shared.physics.localVelocity[2] = 120.0 / 3.6
        self.shared.publish()

        self.reader = AcSharedMemory(_PREFIX)

    def tearDown(self) -> None:
        self.reader.close()
        self.shared.close()

    def _read_after(self, seconds: float):
        time.sleep(seconds)
        return self.reader.read()

    def test_datos_basicos(self) -> None:
        data = self.reader.read()
        self.assertIsNotNone(data)
        assert data is not None
        self.assertTrue(data.live)
        self.assertEqual(data.car, "ks_testcar")
        self.assertEqual(data.track, "test_track")
        self.assertEqual(data.gear, 3)
        self.assertEqual(data.rpm, 6000)
        self.assertEqual(data.max_rpm, 8000)
        self.assertAlmostEqual(data.speed_kmh, 120.0, places=1)
        self.assertEqual(data.current_ms, 61234)
        self.assertEqual(data.last_ms, 90000)
        self.assertEqual(data.best_ms, 88000)
        self.assertEqual(data.delta_ms, 250)
        self.assertLess(data.bump, 30)
        self.assertLess(data.grip, 30)

    def test_delta_negativo(self) -> None:
        self.shared.graphics.isDeltaPositive = 0
        self.shared.graphics.iDeltaLapTime = 180
        self.shared.publish()
        data = self.reader.read()
        assert data is not None
        self.assertEqual(data.delta_ms, -180)

    def test_delta_no_disponible(self) -> None:
        # Sin vuelta de referencia no hay delta posible.
        self.shared.graphics.iBestTime = 0
        self.shared.graphics.bestTime = ""
        self.shared.publish()
        data = self.reader.read()
        assert data is not None
        self.assertIsNone(data.delta_ms)

    def test_delta_de_ac_ignorado_si_vuelta_invalida(self) -> None:
        # Con la vuelta invalidada AC publica deltas que no valen (a veces van
        # subiendo sin parar). Se descarta y manda el delta propio.
        self.shared.graphics.isValidLap = 0
        self.shared.publish()
        data = self.reader.read()
        assert data is not None
        self.assertIsNone(data.delta_ms)

    def test_tiempos_desde_texto(self) -> None:
        # Algunos casos dejan los enteros a 0 y solo rellenan el texto.
        g = self.shared.graphics
        g.iCurrentTime = 0
        g.iLastTime = 0
        g.iBestTime = 0
        g.iDeltaLapTime = 0
        g.currentTime = "1:02.345"
        g.lastTime = "1:23.456"
        g.bestTime = "1:22.000"
        g.deltaLapTime = "-0.250"
        g.isValidLap = 1
        self.shared.publish()
        data = self.reader.read()
        assert data is not None
        self.assertEqual(data.current_ms, 62345)
        self.assertEqual(data.last_ms, 83456)
        self.assertEqual(data.best_ms, 82000)
        self.assertEqual(data.delta_ms, -250)

    def test_tiempos_formato_del_juego(self) -> None:
        # AC escribe los textos como "minutos:segundos:milésimas" (2:26:680),
        # no "2:26.680". Es el formato que aparece de verdad en el juego.
        g = self.shared.graphics
        g.iCurrentTime = 0
        g.iLastTime = 0
        g.iBestTime = 0
        g.iDeltaLapTime = 0
        g.currentTime = "0:14:535"
        g.lastTime = "2:26:680"
        g.bestTime = "1:22:005"
        g.deltaLapTime = ""
        self.shared.publish()
        data = self.reader.read()
        assert data is not None
        self.assertEqual(data.current_ms, 14535)
        self.assertEqual(data.last_ms, 146680)
        self.assertEqual(data.best_ms, 82005)

    def test_mejor_sin_registrar(self) -> None:
        # Estado real observado en Spa: se completó la vuelta de salida, AC
        # copia el tiempo en iBestTime pero su propio HUD dice que no hay
        # mejor vuelta ("-:--:---") y no da delta.
        g = self.shared.graphics
        g.iCurrentTime = 14535
        g.iLastTime = 146680
        g.iBestTime = 146680        # AC copia aquí la última vuelta
        g.lastTime = "2:26:680"
        g.bestTime = "-:--:---"     # ...pero dice que no hay mejor
        g.iDeltaLapTime = 0
        g.deltaLapTime = ""
        g.isValidLap = 0
        self.shared.publish()
        data = self.reader.read()
        assert data is not None
        self.assertEqual(data.current_ms, 14535)
        self.assertEqual(data.last_ms, 146680)
        self.assertIsNone(data.delta_ms)

    def test_delta_propio_sin_delta_de_ac(self) -> None:
        # AC no publica delta (vuelta invalidada), pero Gyromovil lo calcula
        # comparando con su mejor vuelta: aquí 200 ms más lento en cada punto.
        g = self.shared.graphics
        g.iBestTime = 90000
        g.bestTime = "-:--:---"
        g.iDeltaLapTime = 0
        g.deltaLapTime = ""
        g.isValidLap = 0

        def vuelta(offset_ms: int, hasta: int = 200) -> None:
            for i in range(1, hasta + 1):
                pos = i * 0.005
                g.normalizedCarPosition = pos
                g.iCurrentTime = int(pos * 100_000) + offset_ms
                self.shared.publish()
                self.reader.read()

        vuelta(0)
        # Cruzar la línea: la posición vuelve a 0 y la vuelta pasa a referencia.
        g.normalizedCarPosition = 0.001
        g.iCurrentTime = 50
        g.iLastTime = 100_000
        self.shared.publish()
        self.reader.read()

        # Vuelta 2 hasta la mitad, 200 ms más lenta en todo el trazado.
        vuelta(200, hasta=100)
        data = self.reader.read()
        assert data is not None
        self.assertIsNotNone(data.delta_ms, "debe haber delta propio")
        self.assertAlmostEqual(abs(data.delta_ms or 0), 200, delta=60)

    def test_vuelta_con_salto_no_sirve_de_referencia(self) -> None:
        # Si en la vuelta de referencia hay un teleport del juego (reset a
        # boxes, tirón del PC), el delta se volvía loco: subía en rojo sin
        # parar. Esa vuelta ya no se usa.
        g = self.shared.graphics
        g.iBestTime = 90000
        g.bestTime = "-:--:---"
        g.iDeltaLapTime = 0
        g.deltaLapTime = ""

        def paso(pos: float, cur: int) -> None:
            g.normalizedCarPosition = pos
            g.iCurrentTime = cur
            self.shared.publish()
            self.reader.read()

        # Vuelta 1: normal hasta el 30 %, luego salto al 60 % (teleport).
        for i in range(0, 301):
            paso(i / 1000.0, int(i * 100))
        for i in range(600, 1001):
            paso(i / 1000.0, int(i * 100))
        paso(0.001, 50)

        # Vuelta 2 hasta la mitad. Sin referencia válida no debe haber delta.
        for i in range(0, 501):
            paso(i / 1000.0, int(i * 100))
        data = self.reader.read()
        assert data is not None
        self.assertIsNone(data.delta_ms, "una vuelta con saltos no vale de referencia")

    def test_baches_y_agarre(self) -> None:
        self.reader.read()  # primera lectura: fija la referencia
        # La suspensión se comprime 4 cm en 30 ms y las ruedas se bloquean.
        for i in range(4):
            self.shared.physics.suspensionTravel[i] = 0.06
            self.shared.physics.wheelAngularSpeed[i] = 0.0
        self.shared.publish()
        data = self._read_after(0.03)
        assert data is not None
        self.assertGreater(data.bump, 20, "el bache debería detectarse")
        self.assertGreater(data.grip, 50, "el bloqueo de ruedas debería detectarse")

    def test_pausa_resetea_ffb(self) -> None:
        self.reader.read()
        self.shared.graphics.status = ac_shm.AC_PAUSE
        self.shared.publish()
        data = self._read_after(0.03)
        assert data is not None
        self.assertFalse(data.live)
        self.assertEqual(data.bump, 0)
        self.assertEqual(data.grip, 0)

    def test_sin_juego(self) -> None:
        reader = AcSharedMemory(rf"Local\no_existe_{os.getpid()}_acpmf")
        self.assertIsNone(reader.read())
        self.assertFalse(reader.available)
        reader.close()

    def test_datos_corruptos_no_rompen(self) -> None:
        # Si AC escribe justo mientras se lee, pueden aparecer NaN.
        nan = float("nan")
        self.shared.physics.accG[0] = nan
        self.shared.physics.rpms = 999999
        self.shared.physics.speedKmh = nan
        self.shared.physics.wheelAngularSpeed[1] = nan
        self.shared.physics.localVelocity[0] = nan
        self.shared.publish()
        data = self.reader.read()
        self.assertIsNotNone(data)
        assert data is not None
        self.assertEqual(data.rpm, 30000)
        self.assertEqual(data.speed_kmh, 0.0)
        self.assertGreaterEqual(data.bump, 0)
        self.assertLessEqual(data.bump, 100)
        self.assertGreaterEqual(data.grip, 0)
        self.assertLessEqual(data.grip, 100)

    def test_maxrpm_por_defecto(self) -> None:
        # Algunos mods publican maxRpm = 0; el HUD no debe apagarse.
        self.shared.static.maxRpm = 0
        self.shared.publish()
        data = self.reader.read()
        assert data is not None
        self.assertEqual(data.max_rpm, 8000)

    def test_conduccion_normal_no_vibra(self) -> None:
        for _ in range(25):
            self.reader.read()
            time.sleep(0.02)
        data = self.reader.read()
        assert data is not None
        self.assertEqual(data.bump, 0)
        self.assertEqual(data.grip, 0)

    def test_piano_corto_a_alta_frecuencia(self) -> None:
        # El servidor lee AC a ~200 Hz: un piano de pocos milisegundos debe
        # notarse (a 50 Hz se perdía entre dos paquetes).
        self.reader.read()
        peak = 0
        for i in range(12):
            if i == 2 or i == 4:
                for w in range(4):
                    self.shared.physics.suspensionTravel[w] = 0.055 if i == 2 else 0.02
            self.shared.publish()
            data = self.reader.read()
            assert data is not None
            peak = max(peak, data.bump)
            time.sleep(0.004)
        self.assertGreaterEqual(peak, 50, "un piano corto debe notarse")

    def test_bache_se_apaga(self) -> None:
        self.reader.read()
        for i in range(4):
            self.shared.physics.suspensionTravel[i] = 0.06
        self.shared.publish()
        first = self._read_after(0.03)
        assert first is not None
        self.assertGreater(first.bump, 20, "el bache debería detectarse")

        for i in range(4):
            self.shared.physics.suspensionTravel[i] = 0.02
        self.shared.publish()
        last = first
        for _ in range(20):
            last = self._read_after(0.02)
            assert last is not None
        self.assertLess(last.bump, 10, "el bache debe apagarse al dejar el piano")


class FfbMathTest(unittest.TestCase):
    """Cálculo del FFB sin memoria compartida real (solo matemáticas)."""

    def _reader(self):
        reader = AcSharedMemory(_PREFIX)
        static = ac_shm._PageFileStatic()
        for i in range(4):
            static.tyreRadius[i] = 0.33
        return reader, static

    @staticmethod
    def _physics(speed_kmh: float = 120.0, slip: float = 0.0):
        physics = ac_shm._PageFilePhysics()
        physics.speedKmh = speed_kmh
        v = speed_kmh / 3.6
        for i in range(4):
            physics.suspensionTravel[i] = 0.02
            physics.wheelAngularSpeed[i] = v * (1.0 + slip) / 0.33
        physics.localVelocity[2] = v
        return physics

    def _run(self, reader, static, physics, steps: int = 5) -> None:
        for _ in range(steps):
            reader._update_ffb(physics, static, 0.01)

    def test_aviso_de_limite_antes_de_perder_agarre(self) -> None:
        reader, static = self._reader()
        self._run(reader, static, self._physics(slip=0.07))
        self.assertGreater(reader._limit, 0.5, "debe avisar cerca del límite")
        self.assertLess(reader._grip, 0.01, "todavía no hay pérdida de agarre")

    def test_sin_aviso_en_conduccion_normal(self) -> None:
        reader, static = self._reader()
        self._run(reader, static, self._physics(slip=0.01))
        self.assertEqual(reader._limit, 0.0)

    def test_perdida_de_agarre_supera_el_aviso(self) -> None:
        reader, static = self._reader()
        self._run(reader, static, self._physics(slip=0.30))
        self.assertGreater(reader._grip, 0.5)
        self.assertEqual(reader._limit, 1.0)

    def test_aviso_se_apaga_al_recuperar_agarre(self) -> None:
        reader, static = self._reader()
        self._run(reader, static, self._physics(slip=0.07))
        self._run(reader, static, self._physics(slip=0.0), steps=60)
        self.assertLess(reader._limit, 0.05)

    def test_curb_mediano_se_siente_fuerte(self) -> None:
        reader, static = self._reader()
        physics = self._physics()
        reader._update_ffb(physics, static, 0.01)      # fija la referencia
        for i in range(4):
            physics.suspensionTravel[i] = 0.023        # ~0,3 m/s: un curb suave
        reader._update_ffb(physics, static, 0.01)
        self.assertGreater(reader._bump, 0.5)


class ProtocolTest(unittest.TestCase):
    def test_siete_campos(self) -> None:
        control = parse_control(b"0.25,0.80,0.10,1,0,1,1")
        assert control is not None
        self.assertAlmostEqual(control.steer, 0.25)
        self.assertAlmostEqual(control.gas, 0.80)
        self.assertAlmostEqual(control.brake, 0.10)
        self.assertTrue(control.up)
        self.assertFalse(control.down)
        self.assertTrue(control.handbrake)
        self.assertTrue(control.clutch)

    def test_cinco_campos_compatible(self) -> None:
        control = parse_control(b"-0.5,1.0,0.0,0,1")
        assert control is not None
        self.assertFalse(control.up)
        self.assertTrue(control.down)
        self.assertFalse(control.handbrake)
        self.assertFalse(control.clutch)

    def test_paquetes_invalidos(self) -> None:
        self.assertIsNone(parse_control(b"GYRO?"))
        self.assertIsNone(parse_control(b"1,2"))
        self.assertIsNone(parse_control(b"nan,0,0,0,0"))
        self.assertIsNone(parse_control(b"0,inf,0,0,0"))
        self.assertIsNone(parse_control(b""))

    def test_limites(self) -> None:
        control = parse_control(b"2.0,3.0,-1.0,1,1")
        assert control is not None
        self.assertEqual(control.steer, 1.0)
        self.assertEqual(control.gas, 1.0)
        self.assertEqual(control.brake, 0.0)

    def test_paquete_telemetria(self) -> None:
        data = Telemetry(
            gear=3, rpm=6000, max_rpm=8000, speed_kmh=120.4,
            current_ms=61234, last_ms=90000, best_ms=88000,
            delta_ms=-250, bump=42, grip=17, limit=63,
        )
        self.assertEqual(
            telemetry_packet(data),
            b"T,3,6000,8000,120,61234,90000,88000,-250,42,17,63",
        )

    def test_paquete_telemetria_sin_delta(self) -> None:
        data = Telemetry(gear=1, rpm=0, max_rpm=8000, delta_ms=None)
        self.assertTrue(telemetry_packet(data).endswith(b",N,0,0,0"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
