"""Gyro Wheel - receptor para PC (Windows).

Recibe los paquetes UDP de la app, los convierte en un mando Xbox 360 virtual
(ViGEmBus) y le devuelve telemetría de Assetto Corsa para el HUD y el FFB.

Protocolo app -> PC (texto, puerto 5005):
    steer,gas,brake,up,down,handbrake,clutch,...
    - steer:     -1..1  (volante)
    - gas/brake:  0..1
    - up/down:   1 = botón de subir/bajar marcha pulsado
    - hand:      1 = freno de mano (solo modo drift)
    - clutch:    1 = embrague (solo modo drift)
    Se aceptan también los 5 primeros campos (versiones antiguas de la app).

Protocolo PC -> app (texto, al mismo socket que envió el último control):
    T,marcha,rpm,rpmMax,kmh,actual,ultima,mejor,delta,baches,agarre
    - delta: milisegundos con signo (+ = más lento) o "N" si no hay referencia.
    - baches/agarre: 0..100 para la vibración FFB.
"""
from __future__ import annotations

import select
import socket
import sys
import time
from dataclasses import dataclass
from typing import Optional

from ac_shm import AcSharedMemory, telemetry_packet

PORT = 5005
# Se muestra al arrancar: sirve para saber si estás usando esta versión del PC.
VERSION = "1.13"
TELEMETRY_HZ = 50
# El bucle principal corre a ~200 Hz: así se ven los pianos y baches cortos,
# que a 50 Hz se perdían entre paquetes.
LOOP_SECONDS = 0.005
# Si el móvil deja de mandar controles, se sueltan botones/ejes.
NEUTRAL_TIMEOUT = 0.6
# Si el móvil lleva mucho tiempo callado, se deja de mandar telemetría.
CLIENT_TIMEOUT = 10.0
RECV_BUFFER = 512

try:
    import vgamepad as vg
except Exception as exc:  # ImportError o falta ViGEmClient.dll
    vg = None
    VGAME_IMPORT_ERROR: Optional[BaseException] = exc
else:
    VGAME_IMPORT_ERROR = None

# Botones que emite el servidor. Si cambias estos valores, cambia también la
# configuración de Assetto Corsa (Controles -> mando Xbox 360).
BTN_SHIFT_UP = None if vg is None else vg.XUSB_BUTTON.XUSB_GAMEPAD_RIGHT_SHOULDER
BTN_SHIFT_DOWN = None if vg is None else vg.XUSB_BUTTON.XUSB_GAMEPAD_LEFT_SHOULDER
BTN_HANDBRAKE = None if vg is None else vg.XUSB_BUTTON.XUSB_GAMEPAD_B
BTN_CLUTCH = None if vg is None else vg.XUSB_BUTTON.XUSB_GAMEPAD_X


@dataclass(slots=True)
class Control:
    steer: float = 0.0
    gas: float = 0.0
    brake: float = 0.0
    up: bool = False
    down: bool = False
    handbrake: bool = False
    clutch: bool = False


def clamp(value: float, low: float, high: float) -> float:
    return low if value < low else high if value > high else value


def fmt_time(ms: int) -> str:
    """Milisegundos al formato del HUD ("2:26.680"); "--:--.---" si no hay dato."""
    if ms is None or ms <= 0:
        return "--:--.---"
    return f"{ms // 60000}:{(ms % 60000) / 1000:06.3f}"


def parse_control(payload: bytes) -> Optional[Control]:
    """Parsea un paquete de control. Devuelve None si no es válido.

    Acepta 7 campos (versión actual) y 5 campos (versiones anteriores). Los
    campos extra se ignoran para no romper la compatibilidad.
    """
    if not payload or payload.startswith(b"GYRO?"):
        return None
    try:
        text = payload.decode("ascii")
        parts = text.split(",")
        if len(parts) < 5:
            return None
        steer = float(parts[0])
        gas = float(parts[1])
        brake = float(parts[2])
        if not all(map(math_isfinite, (steer, gas, brake))):
            return None
        up = parts[3].strip() == "1"
        down = parts[4].strip() == "1"
        handbrake = len(parts) > 5 and parts[5].strip() == "1"
        clutch = len(parts) > 6 and parts[6].strip() == "1"
    except (UnicodeDecodeError, ValueError):
        return None
    return Control(
        steer=clamp(steer, -1.0, 1.0),
        gas=clamp(gas, 0.0, 1.0),
        brake=clamp(brake, 0.0, 1.0),
        up=up,
        down=down,
        handbrake=handbrake,
        clutch=clutch,
    )


def math_isfinite(value: float) -> bool:
    # Evita importar math solo para esto y descarta NaN/Inf.
    return value == value and value not in (float("inf"), float("-inf"))


def local_ip() -> str:
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.connect(("10.255.255.255", 1))
        return sock.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        sock.close()


class Gamepad:
    """Envoltorio de vgamepad con un único punto de salida de errores."""

    def __init__(self) -> None:
        assert vg is not None
        self._pad = vg.VX360Gamepad()
        self.neutral()

    def neutral(self) -> None:
        self._pad.left_joystick_float(x_value_float=0.0, y_value_float=0.0)
        self._pad.left_trigger_float(value_float=0.0)
        self._pad.right_trigger_float(value_float=0.0)
        for button in (BTN_SHIFT_UP, BTN_SHIFT_DOWN, BTN_HANDBRAKE, BTN_CLUTCH):
            if button is not None:
                self._pad.release_button(button=button)
        self._pad.update()

    def apply(self, control: Control) -> None:
        self._pad.left_joystick_float(x_value_float=control.steer, y_value_float=0.0)
        self._pad.right_trigger_float(value_float=control.gas)
        self._pad.left_trigger_float(value_float=control.brake)
        self._button(BTN_SHIFT_UP, control.up)
        self._button(BTN_SHIFT_DOWN, control.down)
        self._button(BTN_HANDBRAKE, control.handbrake)
        self._button(BTN_CLUTCH, control.clutch)
        self._pad.update()

    def _button(self, button, pressed: bool) -> None:
        if button is None:
            return
        if pressed:
            self._pad.press_button(button=button)
        else:
            self._pad.release_button(button=button)


def _print_missing_driver(error: Optional[BaseException]) -> None:
    print("\nNo se pudo crear el mando Xbox virtual.")
    print("Hace falta el driver ViGEmBus (solo se instala una vez):")
    print("  https://github.com/nefarius/ViGEmBus/releases")
    print("Descarga el .exe, instálalo, reinicia el PC y vuelve a abrir este servidor.")
    if error is not None:
        print(f"\nDetalle técnico: {type(error).__name__}: {error}")
    print()


def main() -> int:
    print("=" * 62)
    print(" Gyromovil - servidor de mando y telemetría")
    print(f" versión {VERSION} del PC")
    print("=" * 62)

    if vg is None:
        _print_missing_driver(VGAME_IMPORT_ERROR)
        return 1

    try:
        pad = Gamepad()
    except Exception as exc:  # ViGEmBus no instalado / versión incompatible
        _print_missing_driver(exc)
        return 1

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        sock.bind(("0.0.0.0", PORT))
    except OSError as exc:
        print(f"No se pudo abrir el puerto UDP {PORT}: {exc}")
        print("Cierra cualquier otro servidor Gyromovil que esté usando ese puerto.")
        return 1
    sock.setblocking(False)

    reader = AcSharedMemory()
    print(f"\nServidor listo en el puerto UDP {PORT}.")
    print(f"Si la app no encuentra el PC sola, escribe esta IP: {local_ip()}")
    print("En Windows, permite el acceso cuando el firewall lo pregunte.\n")
    print("Mapeo del mando en Assetto Corsa:")
    print("  Dirección      -> stick izquierdo (eje X)")
    print("  Acelerador     -> gatillo derecho (RT)")
    print("  Freno          -> gatillo izquierdo (LT)")
    print("  Subir marcha   -> RB")
    print("  Bajar marcha   -> LB")
    print("  Freno de mano  -> B")
    print("  Embrague       -> X\n")
    print("Abre Assetto Corsa DESPUÉS de este servidor para que detecte el")
    print("mando virtual. Si ya estaba abierto, ciérralo y vuelve a abrirlo.\n")

    client: Optional[tuple[str, int]] = None
    last_control = 0.0
    last_telemetry = 0.0
    last_live = 0.0
    telemetry_seen = False
    pad_is_neutral = True
    client_announced = False
    ac_hint_shown = False

    try:
        while True:
            # select evita un bucle activo al 100 % sin bloquear la telemetría.
            select.select([sock], [], [], LOOP_SECONDS)
            now = time.monotonic()

            # Leer AC a ~200 Hz (no a 50): un piano dura pocos milisegundos y a
            # 50 Hz se colaba entre dos lecturas, así que apenas se notaba.
            latest = reader.read()

            while True:
                try:
                    payload, address = sock.recvfrom(RECV_BUFFER)
                except BlockingIOError:
                    break
                except OSError:
                    break

                if payload.startswith(b"GYRO?"):
                    sock.sendto(b"GYRO!", address)
                    continue

                control = parse_control(payload)
                if control is None:
                    continue

                if address != client:
                    client = address
                    client_announced = False
                last_control = now
                if not client_announced:
                    print(f"Celular conectado: {client[0]}:{client[1]}")
                    client_announced = True

                try:
                    pad.apply(control)
                except Exception as exc:
                    print(f"Error enviando al mando virtual: {exc}")
                    return 1
                pad_is_neutral = False

            if client is not None and not pad_is_neutral and now - last_control > NEUTRAL_TIMEOUT:
                pad.neutral()
                pad_is_neutral = True
                print("Sin señal del celular: mando en neutro")

            if client is not None and now - last_control > CLIENT_TIMEOUT:
                client = None

            # Telemetría a 50 Hz: solo si hay un móvil conectado recientemente.
            if client is not None and now - last_telemetry >= 1.0 / TELEMETRY_HZ:
                last_telemetry = now
                data = latest
                if data is None and not ac_hint_shown:
                    ac_hint_shown = True
                    print("Esperando a Assetto Corsa: abre el juego y entra en pista.")
                if data is not None and data.live:
                    ac_hint_shown = False
                    packet = telemetry_packet(data)
                    try:
                        sock.sendto(packet, client)
                    except OSError:
                        pass
                    last_live = now
                    if not telemetry_seen:
                        telemetry_seen = True
                        extra = ""
                        if data.car or data.track:
                            extra = f" ({data.car} @ {data.track})"
                        print(f"Telemetría de Assetto Corsa conectada{extra}")
                        # Muestra de lo que recibe el móvil: si aquí salen los
                        # tiempos y en el HUD no, el problema está en la app.
                        delta = "sin referencia" if data.delta_ms is None else f"{data.delta_ms:+d} ms"
                        print(f"  envía: {packet.decode('ascii')}")
                        print(f"  tiempos: actual {fmt_time(data.current_ms)} | "
                              f"última {fmt_time(data.last_ms)} | "
                              f"mejor {fmt_time(data.best_ms)} | delta {delta}")
                elif telemetry_seen and now - last_live > 2.0:
                    telemetry_seen = False
                    print("Telemetría de Assetto Corsa sin señal (menú, pausa o juego cerrado)")

    except KeyboardInterrupt:
        print("\nCerrando...")
    finally:
        try:
            pad.neutral()
        except Exception:
            pass
        reader.close()
        sock.close()
        print("Servidor detenido.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
