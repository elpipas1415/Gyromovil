"""Lector de telemetría de Assetto Corsa (AC1) para Windows.

Lee las tres páginas de memoria compartida que publica el juego:

    Local\\acpmf_physics   -> motor, velocidad, suspensiones, deslizamiento
    Local\\acpmf_graphics  -> tiempos de vuelta, delta, estado de sesión
    Local\\acpmf_static    -> datos fijos del coche (RPM máximas, radio de rueda)

No necesita plugins ni apps dentro del juego: AC publica estas páginas por sí
solo. Está pensado para el servidor ``server.py`` y para ``diagnostico.py``.

Además de los datos "de HUD" (marcha, RPM, tiempos...), calcula las dos señales
que alimentan la vibración FFB del móvil:

* ``bump`` (0..100): baches, pianos y curbs. Se obtiene de la velocidad del
  recorrido de suspensión y de los cambios bruscos del vector de aceleración.
* ``limit`` (0..100): aviso de que el coche está a punto de perder agarre
  (el deslizamiento se acerca al umbral, pero todavía no lo supera).
* ``grip`` (0..100): agarre perdido. Se obtiene del deslizamiento
  longitudinal real de cada rueda (velocidad angular x radio frente a la
  velocidad del coche) y del ángulo de deriva de la carrocería.

Solo se leen los campos de AC1; ACC y AC Evo comparten los nombres de las
páginas pero cambian el layout a partir de cierto punto, así que este módulo no
está pensado para ellos.
"""
from __future__ import annotations

import bisect
import ctypes
import math
import sys
import time
from ctypes import c_float, c_int32, c_wchar
from dataclasses import dataclass
from typing import Optional

# ---------------------------------------------------------------------------
# Estructuras de Assetto Corsa 1 (plugin SDK, #pragma pack(4))
# ---------------------------------------------------------------------------

class _PageFilePhysics(ctypes.Structure):
    _pack_ = 4
    _fields_ = [
        ("packetId", c_int32),
        ("gas", c_float),
        ("brake", c_float),
        ("fuel", c_float),
        ("gear", c_int32),
        ("rpms", c_int32),
        ("steerAngle", c_float),
        ("speedKmh", c_float),
        ("velocity", c_float * 3),
        ("accG", c_float * 3),
        ("wheelSlip", c_float * 4),
        ("wheelLoad", c_float * 4),
        ("wheelsPressure", c_float * 4),
        ("wheelAngularSpeed", c_float * 4),
        ("tyreWear", c_float * 4),
        ("tyreDirtyLevel", c_float * 4),
        ("tyreCoreTemperature", c_float * 4),
        ("camberRAD", c_float * 4),
        ("suspensionTravel", c_float * 4),
        ("drs", c_float),
        ("tc", c_float),
        ("heading", c_float),
        ("pitch", c_float),
        ("roll", c_float),
        ("cgHeight", c_float),
        ("carDamage", c_float * 5),
        ("numberOfTyresOut", c_int32),
        ("pitLimiterOn", c_int32),
        ("abs", c_float),
        ("kersCharge", c_float),
        ("kersInput", c_float),
        ("autoShifterOn", c_int32),
        ("rideHeight", c_float * 2),
        ("turboBoost", c_float),
        ("ballast", c_float),
        ("airDensity", c_float),
        ("airTemp", c_float),
        ("roadTemp", c_float),
        ("localAngularVel", c_float * 3),
        ("finalFF", c_float),
        ("performanceMeter", c_float),
        ("engineBrake", c_int32),
        ("ersRecoveryLevel", c_int32),
        ("ersPowerLevel", c_int32),
        ("ersHeatCharging", c_int32),
        ("ersIsCharging", c_int32),
        ("kersCurrentKJ", c_float),
        ("drsAvailable", c_int32),
        ("drsEnabled", c_int32),
        ("brakeTemp", c_float * 4),
        ("clutch", c_float),
        ("tyreTempI", c_float * 4),
        ("tyreTempM", c_float * 4),
        ("tyreTempO", c_float * 4),
        ("isAIControlled", c_int32),
        ("tyreContactPoint", (c_float * 3) * 4),
        ("tyreContactNormal", (c_float * 3) * 4),
        ("tyreContactHeading", (c_float * 3) * 4),
        ("brakeBias", c_float),
        ("localVelocity", c_float * 3),
    ]


class _PageFileGraphics(ctypes.Structure):
    """Parte de la página graphics que usa Gyromovil.

    Se corta en ``isValidLap``; el resto de campos de AC no se leen.
    """

    _pack_ = 4
    _fields_ = [
        ("packetId", c_int32),
        ("status", c_int32),
        ("session", c_int32),
        ("currentTime", c_wchar * 15),
        ("lastTime", c_wchar * 15),
        ("bestTime", c_wchar * 15),
        ("split", c_wchar * 15),
        ("completedLaps", c_int32),
        ("position", c_int32),
        ("iCurrentTime", c_int32),
        ("iLastTime", c_int32),
        ("iBestTime", c_int32),
        ("sessionTimeLeft", c_float),
        ("distanceTraveled", c_float),
        ("isInPit", c_int32),
        ("currentSectorIndex", c_int32),
        ("lastSectorTime", c_int32),
        ("numberOfLaps", c_int32),
        ("tyreCompound", c_wchar * 33),
        ("replayTimeMultiplier", c_float),
        ("normalizedCarPosition", c_float),
        ("carCoordinates", c_float * 3),
        ("penaltyTime", c_float),
        ("flag", c_int32),
        ("idealLineOn", c_int32),
        ("isInPitLane", c_int32),
        ("surfaceGrip", c_float),
        ("mandatoryPitDone", c_int32),
        ("windSpeed", c_float),
        ("windDirection", c_float),
        ("isSetupMenuVisible", c_int32),
        ("mainDisplayIndex", c_int32),
        ("secondaryDisplayIndex", c_int32),
        ("TC", c_int32),
        ("TCCut", c_int32),
        ("engineMap", c_int32),
        ("ABS", c_int32),
        ("fuelXLap", c_float),
        ("rainLights", c_int32),
        ("flashingLights", c_int32),
        ("lightsStage", c_int32),
        ("exhaustTemperature", c_float),
        ("wiperLV", c_int32),
        ("driverStintTotalTimeLeft", c_int32),
        ("driverStintTimeLeft", c_int32),
        ("rainTyres", c_int32),
        ("sessionIndex", c_int32),
        ("usedFuel", c_float),
        ("deltaLapTime", c_wchar * 15),
        ("iDeltaLapTime", c_int32),
        ("estimatedLapTime", c_wchar * 15),
        ("iEstimatedLapTime", c_int32),
        ("isDeltaPositive", c_int32),
        ("iSplit", c_int32),
        ("isValidLap", c_int32),
    ]


class _PageFileStatic(ctypes.Structure):
    """Solo la cabecera de la página static (hasta ``tyreRadius``)."""

    _pack_ = 4
    _fields_ = [
        ("smVersion", c_wchar * 15),
        ("acVersion", c_wchar * 15),
        ("numberOfSessions", c_int32),
        ("numCars", c_int32),
        ("carModel", c_wchar * 33),
        ("track", c_wchar * 33),
        ("playerName", c_wchar * 33),
        ("playerSurname", c_wchar * 33),
        ("playerNick", c_wchar * 33),
        ("sectorCount", c_int32),
        ("maxTorque", c_float),
        ("maxPower", c_float),
        ("maxRpm", c_int32),
        ("maxFuel", c_float),
        ("suspensionMaxTravel", c_float * 4),
        ("tyreRadius", c_float * 4),
    ]


PHYSICS_SIZE = ctypes.sizeof(_PageFilePhysics)
GRAPHICS_SIZE = ctypes.sizeof(_PageFileGraphics)
STATIC_SIZE = ctypes.sizeof(_PageFileStatic)

AC_OFF = 0
AC_REPLAY = 1
AC_LIVE = 2
AC_PAUSE = 3

# Cada cuánto se reintenta abrir las páginas si AC no está publicando nada.
_RETRY_SECONDS = 2.0
# La página static solo cambia al cambiar de coche; releerla cada segundo basta.
_STATIC_REFRESH = 1.0

# ---- Calibración del delta propio -----------------------------------------
# Un salto de posición mayor que esto entre dos lecturas (~5 ms) no es
# conducción: es un teleport del juego (reset a boxes, repetición, menú). Esa
# vuelta no sirve como referencia.
_TRACE_JUMP = 0.05
# Hueco máximo aceptable entre dos puntos del trazado de referencia.
_TRACE_STORE_GAP = 0.10
# Hueco máximo para interpolar un delta (más grande = no se sabe).
_TRACE_QUERY_GAP = 0.05
# Un delta mayor que esto no es una vuelta peor: es una referencia rota.
_TRACE_MAX_DELTA = 15_000
# Si el coche pasa más de esto sin avanzar por el circuito (boxes, choque),
# la vuelta no vale como referencia.
_TRACE_STALL_MS = 3_000

# ---- Calibración del FFB (v1.13: curbs más agresivos + aviso de límite) -------
# Baches/curbs: velocidad del recorrido de suspensión (m/s) y desviación del
# vector de aceleración (g). Se lee a ~200 Hz, así que un piano de 10 ms sí se ve.
# Umbrales bajos y curva < 1: un golpe mediano ya se siente casi a fondo.
_BUMP_TRAVEL_START = 0.12
_BUMP_TRAVEL_FULL = 0.60
_BUMP_ACC_START = 0.30
_BUMP_ACC_FULL = 0.85
_BUMP_ACC_TAU = 1.20       # segundos; media móvil lenta del vector de aceleración
_BUMP_RELEASE_TAU = 0.14   # segundos; cuánto tarda en apagarse un golpe
_BUMP_CURVE = 0.6          # score ** curva (menor = golpes medianos más fuertes)

# Agarre perdido: deslizamiento longitudinal (0 = rueda perfecta, 1 = bloqueo
# total) y ángulo de deriva de la carrocería (grados).
_GRIP_SLIP_START = 0.08
_GRIP_SLIP_FULL = 0.40
_GRIP_BETA_START = 5.0
_GRIP_BETA_FULL = 22.0
_GRIP_RELEASE_TAU = 0.16

# Aviso de límite: la zona justo ANTES de que empiece la pérdida de agarre.
# Sube de 0 a 1 entre este porcentaje del umbral de pérdida y el umbral mismo.
_LIMIT_FRACTION = 0.45
_LIMIT_RELEASE_TAU = 0.10

# ---------------------------------------------------------------------------
# Acceso a las páginas de memoria compartida de Windows
# ---------------------------------------------------------------------------

_FILE_MAP_READ = 0x0004
_ERROR_FILE_NOT_FOUND = 2

if sys.platform == "win32":
    _kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    _kernel32.OpenFileMappingW.argtypes = [ctypes.c_uint32, ctypes.c_int, ctypes.c_wchar_p]
    _kernel32.OpenFileMappingW.restype = ctypes.c_void_p
    _kernel32.MapViewOfFile.argtypes = [
        ctypes.c_void_p, ctypes.c_uint32, ctypes.c_uint32, ctypes.c_uint32, ctypes.c_size_t
    ]
    _kernel32.MapViewOfFile.restype = ctypes.c_void_p
    _kernel32.UnmapViewOfFile.argtypes = [ctypes.c_void_p]
    _kernel32.UnmapViewOfFile.restype = ctypes.c_int
    _kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
    _kernel32.CloseHandle.restype = ctypes.c_int
else:  # pragma: no cover - el servidor es Windows
    _kernel32 = None


class _NamedMapping:
    """Vista de solo lectura de un file mapping con nombre de Windows."""

    def __init__(self, name: str, size: int) -> None:
        if _kernel32 is None:
            raise OSError("la memoria compartida de Assetto Corsa solo existe en Windows")
        self._size = size
        self._view: Optional[int] = None
        self._handle: Optional[int] = None
        handle = _kernel32.OpenFileMappingW(_FILE_MAP_READ, 0, name)
        if not handle:
            error = ctypes.get_last_error()
            if error == _ERROR_FILE_NOT_FOUND:
                raise FileNotFoundError(name)
            raise OSError(error, f"no se pudo abrir {name}")
        view = _kernel32.MapViewOfFile(handle, _FILE_MAP_READ, 0, 0, 0)
        if not view:
            error = ctypes.get_last_error()
            _kernel32.CloseHandle(handle)
            raise OSError(error, f"no se pudo mapear {name}")
        self._handle = handle
        self._view = view

    def read(self) -> bytes:
        if self._view is None:
            raise OSError("mapping cerrado")
        return ctypes.string_at(self._view, self._size)

    def close(self) -> None:
        if _kernel32 is None:
            return
        if self._view is not None:
            _kernel32.UnmapViewOfFile(self._view)
            self._view = None
        if self._handle is not None:
            _kernel32.CloseHandle(self._handle)
            self._handle = None


# ---------------------------------------------------------------------------
# Datos que consume el servidor
# ---------------------------------------------------------------------------

@dataclass(slots=True)
class Telemetry:
    car: str = ""
    track: str = ""
    status: int = AC_OFF
    gear: int = 1
    rpm: int = 0
    max_rpm: int = 0
    speed_kmh: float = 0.0
    current_ms: int = -1
    last_ms: int = -1
    best_ms: int = -1
    delta_ms: Optional[int] = None
    bump: int = 0
    grip: int = 0
    limit: int = 0
    # Solo se rellena cuando ``AcSharedMemory.raw_debug`` está activo (diagnóstico).
    raw: str = ""

    @property
    def live(self) -> bool:
        """True solo cuando se está rodando (no en menús, pausa o replay)."""
        return self.status == AC_LIVE


def _clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return low if value < low else high if value > high else value


def telemetry_packet(data: "Telemetry") -> bytes:
    """Línea de telemetría que entiende ``MainActivity.startReceiver()``.

    T,marcha,rpm,rpmMax,kmh,actual,ultima,mejor,delta,baches,agarre,limite
    ``delta`` es milisegundos con signo o "N" si no hay referencia.
    """
    delta = "N" if data.delta_ms is None else str(int(data.delta_ms))
    line = (
        f"T,{int(data.gear)},{int(data.rpm)},{int(data.max_rpm)},"
        f"{float(data.speed_kmh):.0f},"
        f"{int(data.current_ms)},{int(data.last_ms)},{int(data.best_ms)},"
        f"{delta},{int(data.bump)},{int(data.grip)},{int(data.limit)}"
    )
    return line.encode("ascii", "ignore")


def _num(value, default: float = 0.0) -> float:
    """Convierte a float y descarta NaN/Inf (AC puede escribir a medias)."""
    try:
        result = float(value)
    except (TypeError, ValueError):
        return default
    return result if math.isfinite(result) else default


def _ramp(value: float, start: float, full: float) -> float:
    """0 por debajo de ``start``, 1 por encima de ``full``, lineal en medio."""
    if full <= start:
        return 0.0
    return _clamp((value - start) / (full - start))


def _text(value) -> str:
    return str(value).replace("\x00", "").strip()


def _parse_time_text(value) -> Optional[int]:
    """Convierte el texto de AC ("0:14:535" o "+0.25") a milisegundos.

    AC publica los tiempos dos veces: como entero en milisegundos y como texto.
    Algunos casos dejan el entero a 0, así que el texto sirve de respaldo.

    El juego usa el formato ``minutos:segundos:milésimas`` ("2:26:680"), no
    "2:26.680". También se aceptan "1:23.456" y "+0.250" (delta).
    Devuelve ``None`` si el texto no es un tiempo válido ("-:--:---", vacío...).
    """
    text = _text(value).replace(",", ".")
    if not text or set(text) <= {"-", ":", ".", " "}:
        return None
    sign = 1
    if text[0] in "+-":
        if text[0] == "-":
            sign = -1
        text = text[1:]
    try:
        parts = text.split(":")
        if len(parts) == 3:
            # Formato del propio juego: "0:14:535" -> 14 s y 535 milésimas.
            minutes, seconds, thousandths = parts
            milliseconds = (int(minutes) * 60 + int(seconds)) * 1000.0
            milliseconds += int(thousandths.ljust(3, "0")[:3])
        elif len(parts) == 2:
            minutes, rest = parts
            milliseconds = (int(minutes) * 60 + float(rest)) * 1000.0
        else:
            milliseconds = float(text) * 1000.0
    except ValueError:
        return None
    if not math.isfinite(milliseconds):
        return None
    return sign * int(round(milliseconds))


def _time_or_text(number, text) -> int:
    """Usa el entero de AC si es válido; si no, intenta con el texto."""
    value = int(number)
    if value > 0:
        return value
    parsed = _parse_time_text(text)
    if parsed is None or parsed <= 0:
        return -1
    return parsed


class _LapTrace:
    """Trazado de una vuelta: tiempo acumulado en cada punto del circuito.

    AC a veces no publica su propio delta (vuelta invalidada o mejor vuelta sin
    registrar), así que Gyromovil se guarda la mejor vuelta y calcula el delta
    comparando el tiempo actual con el de la referencia en la misma posición.
    """

    __slots__ = ("pos", "ms")

    def __init__(self) -> None:
        self.pos: list[float] = []
        self.ms: list[int] = []

    def add(self, pos: float, ms: int) -> None:
        self.pos.append(pos)
        self.ms.append(ms)

    def max_gap(self) -> float:
        """Mayor salto de posición entre dos puntos seguidos."""
        return max((b - a for a, b in zip(self.pos, self.pos[1:])), default=0.0)

    def at(self, pos: float) -> Optional[int]:
        """Tiempo de la referencia en esa posición (interpolado), o None."""
        if len(self.pos) < 50:
            return None
        i = bisect.bisect_left(self.pos, pos)
        if i <= 0 or i >= len(self.pos):
            return None
        p0, p1 = self.pos[i - 1], self.pos[i]
        t0, t1 = self.ms[i - 1], self.ms[i]
        # Hueco en el trazado (tirón del juego, teleport a boxes...): mejor no
        # inventarse un tiempo que enseñar un delta que sube sin control.
        if p1 - p0 > _TRACE_QUERY_GAP:
            return None
        if p1 <= p0:
            return t1
        frac = (pos - p0) / (p1 - p0)
        return int(round(t0 + (t1 - t0) * frac))



class AcSharedMemory:
    """Lee AC y calcula las señales de FFB.

    Uso::

        reader = AcSharedMemory()
        while True:
            data = reader.read()      # None si AC no está abierto
            if data and data.live:
                ...

    ``read()`` se puede llamar a 50 Hz sin problema: solo copia los bytes de las
    páginas y parsea los campos necesarios.
    """

    def __init__(self, name_prefix: str = r"Local\acpmf") -> None:
        self._names = (
            name_prefix + "_physics",
            name_prefix + "_graphics",
            name_prefix + "_static",
        )
        self._physics: Optional[_NamedMapping] = None
        self._graphics: Optional[_NamedMapping] = None
        self._static: Optional[_NamedMapping] = None
        self._static_data: Optional[_PageFileStatic] = None
        self._last_static = 0.0
        self._retry_at = 0.0
        # Estado de los filtros de FFB.
        self._prev_time: Optional[float] = None
        self._prev_travel: Optional[tuple[float, float, float, float]] = None
        self._acc_ema: Optional[list[float]] = None
        self._bump = 0.0
        self._grip = 0.0
        self._limit = 0.0
        # Delta propio (por si AC no publica el suyo).
        self._trace = _LapTrace()
        self._ref: Optional[_LapTrace] = None
        self._ref_total = 0
        self._last_pos = -1.0
        self._trace_car: tuple[str, str] = ("", "")
        self._pos_jump = False
        self._trace_bad = False
        # Si es True, Telemetry.raw describe los tiempos tal cual los publica AC.
        self.raw_debug = False

    # -- ciclo de vida -----------------------------------------------------

    @property
    def available(self) -> bool:
        return self._physics is not None

    def open(self) -> None:
        self.close()
        physics = _NamedMapping(self._names[0], PHYSICS_SIZE)
        try:
            graphics = _NamedMapping(self._names[1], GRAPHICS_SIZE)
            static = _NamedMapping(self._names[2], STATIC_SIZE)
        except OSError:
            physics.close()
            raise
        self._physics, self._graphics, self._static = physics, graphics, static
        self._static_data = _PageFileStatic.from_buffer_copy(static.read())
        self._last_static = time.monotonic()
        self._reset_filters()

    def close(self) -> None:
        for page in (self._physics, self._graphics, self._static):
            if page is not None:
                page.close()
        self._physics = self._graphics = self._static = None
        self._static_data = None
        self._reset_filters()

    def _reset_filters(self) -> None:
        self._prev_time = None
        self._prev_travel = None
        self._acc_ema = None
        self._bump = 0.0
        self._grip = 0.0
        self._limit = 0.0

    # -- lectura -----------------------------------------------------------

    def _ensure_open(self, now: float) -> bool:
        if self.available:
            return True
        if now < self._retry_at:
            return False
        try:
            self.open()
            return True
        except OSError:
            self._retry_at = now + _RETRY_SECONDS
            return False

    def read(self) -> Optional[Telemetry]:
        now = time.monotonic()
        if not self._ensure_open(now):
            return None

        assert self._physics is not None
        assert self._graphics is not None
        try:
            physics = _PageFilePhysics.from_buffer_copy(self._physics.read())
            graphics = _PageFileGraphics.from_buffer_copy(self._graphics.read())
            if now - self._last_static >= _STATIC_REFRESH:
                assert self._static is not None
                self._static_data = _PageFileStatic.from_buffer_copy(self._static.read())
                self._last_static = now
        except (OSError, ValueError):
            # AC cerró el juego o la página desapareció: reintentar más tarde.
            self.close()
            self._retry_at = now + _RETRY_SECONDS
            return None

        static = self._static_data
        if static is None:  # no debería pasar, pero evita un NoneType
            self.close()
            return None

        data = Telemetry(
            car=_text(static.carModel),
            track=_text(static.track),
            status=int(graphics.status),
            gear=int(physics.gear),
            rpm=int(_clamp(_num(physics.rpms), 0.0, 30000.0)),
            max_rpm=int(_clamp(_num(static.maxRpm), 0.0, 30000.0)),
            speed_kmh=_clamp(_num(physics.speedKmh), 0.0, 600.0),
        )
        if data.max_rpm <= 0:
            # Algunos mods no publican maxRpm y la app apagaría el HUD entero.
            data.max_rpm = 8000

        # Tiempos de vuelta. AC usa -1 / 0 para "todavía no hay tiempo" y
        # publica el dato dos veces (entero y texto): si el entero viene a 0 se
        # usa el texto.
        data.current_ms = _time_or_text(graphics.iCurrentTime, graphics.currentTime)
        data.last_ms = _time_or_text(graphics.iLastTime, graphics.lastTime)
        data.best_ms = _time_or_text(graphics.iBestTime, graphics.bestTime)
        data.delta_ms = self._delta_ms(graphics)
        own_delta = None
        if data.live:
            self._track_lap(graphics, data)
            own_delta = self._own_delta(graphics, data)
        if data.delta_ms is None:
            data.delta_ms = own_delta
        elif own_delta is not None and abs(data.delta_ms - own_delta) > 5_000:
            # El delta de AC se ha ido muy lejos del nuestro: manda el propio.
            data.delta_ms = own_delta
        if self.raw_debug:
            data.raw = (
                f"cur={int(graphics.iCurrentTime)}/'{_text(graphics.currentTime)}' "
                f"last={int(graphics.iLastTime)}/'{_text(graphics.lastTime)}' "
                f"best={int(graphics.iBestTime)}/'{_text(graphics.bestTime)}' "
                f"delta={int(graphics.iDeltaLapTime)}/'{_text(graphics.deltaLapTime)}' "
                f"signo={int(graphics.isDeltaPositive)} valida={int(graphics.isValidLap)} "
                f"vueltas={int(graphics.completedLaps)} estado={int(graphics.status)} "
                f"pos={_num(graphics.normalizedCarPosition):.3f} "
                f"ref={'si' if self._ref else 'no'} "
                f"propio={'-' if own_delta is None else own_delta}"
            )
        if data.live:
            elapsed = 0.0 if self._prev_time is None else now - self._prev_time
            dt = _clamp(elapsed, 0.005, 0.20)
            self._update_ffb(physics, static, dt)
            data.bump = int(round(_clamp(self._bump) * 100))
            data.grip = int(round(_clamp(self._grip) * 100))
            data.limit = int(round(_clamp(self._limit) * 100))
            self._prev_time = now
        else:
            # En menús/pausa no hay que "arrastrar" una vibración ni un dt enorme.
            self._reset_filters()

        return data

    @staticmethod
    def _delta_ms(graphics: _PageFileGraphics) -> Optional[int]:
        # Sin vuelta de referencia no hay delta posible.
        if _time_or_text(graphics.iBestTime, graphics.bestTime) <= 0:
            return None
        # Con la vuelta en curso invalidada AC publica valores que no valen
        # (a veces van subiendo sin parar). En ese caso se usa el delta propio.
        if int(graphics.isValidLap) == 0:
            return None
        delta = int(graphics.iDeltaLapTime)
        if delta != 0:
            return delta if graphics.isDeltaPositive else -delta
        # Respaldo: el texto ya trae el signo ("+0.250" / "-0.250").
        text = _parse_time_text(graphics.deltaLapTime)
        return text if text not in (None, 0) else None

    # -- delta propio ------------------------------------------------------

    def _track_lap(self, graphics: _PageFileGraphics, data: Telemetry) -> None:
        """Guarda el trazado de la vuelta en curso para el delta propio."""
        key = (data.car, data.track)
        if key[0] and key != self._trace_car:
            # Cambio de coche o de circuito: la referencia ya no sirve.
            self._trace_car = key
            self._trace = _LapTrace()
            self._ref = None
            self._ref_total = 0
            self._last_pos = -1.0
            self._trace_bad = False

        pos = _num(graphics.normalizedCarPosition)
        cur = data.current_ms
        if not (0.0 <= pos <= 1.0) or cur <= 0:
            self._pos_jump = False
            return

        previous = self._last_pos
        self._last_pos = pos
        # En ~5 ms el coche no puede avanzar un 5 % del circuito: eso es un
        # salto de la posición (curva donde el juego proyecta mal) o un
        # teleport. En el primer caso se sigue; el delta se calla un instante.
        self._pos_jump = previous >= 0 and abs(pos - previous) > _TRACE_JUMP

        if previous >= 0 and pos < previous - 0.5:
            # La posición pasa de ~1 a ~0 al cruzar la línea.
            self._store_lap(data.last_ms)
            self._trace = _LapTrace()
            self._trace_bad = False
        elif self._pos_jump and abs(pos - previous) > _TRACE_STORE_GAP:
            # Salto enorme: ni se guarda el punto ni sirve la vuelta entera.
            self._trace_bad = True

        trace = self._trace
        if not trace.pos or pos - trace.pos[-1] >= 0.001:
            trace.add(pos, cur)
        elif cur - trace.ms[-1] > _TRACE_STALL_MS:
            # Más de 3 s sin avanzar (boxes, choque, coche parado): la vuelta
            # no sirve como referencia.
            self._trace_bad = True

    def _store_lap(self, last_ms: int) -> None:
        """Se queda con la mejor vuelta completa como referencia."""
        trace = self._trace
        if self._trace_bad or len(trace.pos) < 200:
            return
        if trace.pos[0] > 0.02 or trace.pos[-1] < 0.98:
            return                      # vuelta incompleta (boxes, pausa, corte)
        total = trace.ms[-1]
        if total < 20_000:
            return
        # Si hay un hueco grande en el trazado, la interpolación se inventaría
        # tiempos: esa vuelta no vale como referencia.
        if trace.max_gap() > _TRACE_STORE_GAP:
            return
        # Y nuestro tiempo tiene que cuadrar con el que cronometra AC.
        if last_ms > 0 and abs(total - last_ms) > max(5_000, last_ms * 0.10):
            return
        if self._ref is None or total < self._ref_total - 20:
            self._ref = trace
            self._ref_total = total

    def _own_delta(self, graphics: _PageFileGraphics, data: Telemetry) -> Optional[int]:
        """Delta calculado por Gyromovil contra su mejor vuelta."""
        if self._ref is None or self._pos_jump:
            return None
        pos = _num(graphics.normalizedCarPosition)
        cur = data.current_ms
        if cur < 500 or pos < 0.005 or pos > 0.995:
            return None
        ref = self._ref.at(pos)
        if ref is None:
            return None
        delta = cur - ref
        if abs(delta) > _TRACE_MAX_DELTA:
            # Referencia que no cuadra o vuelta desastrosa: no se enseña.
            return None
        return delta

    # -- FFB ---------------------------------------------------------------

    def _update_ffb(
        self,
        physics: _PageFilePhysics,
        static: _PageFileStatic,
        dt: float,
    ) -> None:
        dt = _clamp(dt, 0.005, 0.20)
        travel = tuple(_num(v) for v in physics.suspensionTravel)

        # 1) Baches por velocidad de compresión/descompresión de la suspensión.
        travel_speed = 0.0
        if self._prev_travel is not None:
            travel_speed = max(
                abs(travel[i] - self._prev_travel[i]) for i in range(4)
            ) / dt
        travel_score = _ramp(travel_speed, _BUMP_TRAVEL_START, _BUMP_TRAVEL_FULL)

        # 2) Baches por cambios bruscos del vector de aceleración. Se usa el
        #    vector completo para no depender del orden de ejes (X/Y/Z) de AC.
        acc = [_num(v) for v in physics.accG]
        if self._acc_ema is None:
            self._acc_ema = list(acc)
        acc_dev = math.sqrt(sum((acc[i] - self._acc_ema[i]) ** 2 for i in range(3)))
        alpha = 1.0 - math.exp(-dt / _BUMP_ACC_TAU)
        for i in range(3):
            self._acc_ema[i] += (acc[i] - self._acc_ema[i]) * alpha
        acc_score = _ramp(acc_dev, _BUMP_ACC_START, _BUMP_ACC_FULL)

        bump_now = max(travel_score, acc_score) ** _BUMP_CURVE
        bump_decay = math.exp(-dt / _BUMP_RELEASE_TAU)
        self._bump = _clamp(max(bump_now, self._bump * bump_decay))

        # 3) Agarre por deslizamiento longitudinal real de cada rueda:
        #    velocidad de la superficie de la rueda frente a velocidad del coche.
        speed_ms = abs(_num(physics.speedKmh)) / 3.6
        slip_now = 0.0
        if speed_ms > 4.0:
            for i in range(4):
                radius = _num(static.tyreRadius[i])
                if radius <= 0.05:
                    radius = 0.33
                surface = abs(_num(physics.wheelAngularSpeed[i])) * radius
                ratio = abs(surface - speed_ms) / max(speed_ms, 6.0)
                if ratio > slip_now:
                    slip_now = ratio
        slip_score = _ramp(slip_now, _GRIP_SLIP_START, _GRIP_SLIP_FULL)

        # 4) Agarre por ángulo de deriva de la carrocería (subviraje/sobreviraje).
        #    localVelocity: X lateral, Z longitudinal (Y es vertical).
        lv = physics.localVelocity
        beta_deg = 0.0
        if speed_ms > 5.0:
            lateral = abs(_num(lv[0]))
            forward = abs(_num(lv[2]))
            beta_deg = math.degrees(math.atan2(lateral, max(forward, 1.0)))
        beta_score = _ramp(beta_deg, _GRIP_BETA_START, _GRIP_BETA_FULL)

        grip_now = max(slip_score, beta_score)
        grip_decay = math.exp(-dt / _GRIP_RELEASE_TAU)
        self._grip = _clamp(max(grip_now, self._grip * grip_decay))

        # 5) Aviso de límite: el deslizamiento ya se acerca al umbral de pérdida
        #    pero todavía no lo supera. Sube justo antes de que "agarre" suene.
        slip_warn = _ramp(slip_now, _GRIP_SLIP_START * _LIMIT_FRACTION, _GRIP_SLIP_START)
        beta_warn = _ramp(beta_deg, _GRIP_BETA_START * _LIMIT_FRACTION, _GRIP_BETA_START)
        limit_decay = math.exp(-dt / _LIMIT_RELEASE_TAU)
        self._limit = _clamp(max(max(slip_warn, beta_warn), self._limit * limit_decay))

        self._prev_travel = travel
