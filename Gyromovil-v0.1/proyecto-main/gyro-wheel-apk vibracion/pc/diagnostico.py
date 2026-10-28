"""Diagnóstico de telemetría de Assetto Corsa.

Abre el juego, entra en pista y ejecuta:

    python diagnostico.py

No hace falta tener ViGEmBus instalado ni el servidor Gyromovil abierto.
Sirve para comprobar que el lector ve el coche, la marcha, las RPM, los
tiempos y los valores de FFB (baches / agarre).

Se para con Ctrl+C, o solo, si le dices cuántos segundos quieres:

    python diagnostico.py 10

La última línea ("crudo") muestra los tiempos tal cual los publica el juego:
si algo no cuadra, copia esa línea y mándala.
"""
from __future__ import annotations

import sys
import time
from typing import Optional

from ac_shm import AcSharedMemory, Telemetry, telemetry_packet

INTERVALO = 0.5   # segundos entre bloques


def bar(value: int, width: int = 20) -> str:
    filled = round(max(0, min(100, value)) * width / 100)
    return "█" * filled + "·" * (width - filled)


def fmt_time(ms: int) -> str:
    if ms <= 0:
        return "--:--.---"
    return f"{ms // 60000}:{(ms % 60000) / 1000:06.3f}"


def fmt_delta(ms: Optional[int]) -> str:
    if ms is None:
        return "--.---"
    sign = "+" if ms > 0 else "−"
    return f"{sign}{abs(ms) / 1000:.3f}"


def block(data: Optional[Telemetry]) -> str:
    stamp = time.strftime("%H:%M:%S")
    if data is None:
        return (
            f"[{stamp}] Assetto Corsa no está publicando telemetría.\n"
            "  Abre el juego y entra en pista (los menús no publican datos)."
        )
    if not data.live:
        return (
            f"[{stamp}] AC abierto ({data.car or 'coche'} @ {data.track or 'circuito'}),"
            " pero no estás en pista (menú, pausa o repetición)."
        )
    lines = [
        f"[{stamp}] {data.car or 'AC'} @ {data.track or '?'} | marcha {data.gear} | "
        f"{data.rpm}/{data.max_rpm} rpm | {data.speed_kmh:5.0f} km/h",
        f"  vuelta {fmt_time(data.current_ms)} | última {fmt_time(data.last_ms)} | "
        f"mejor {fmt_time(data.best_ms)} | delta {fmt_delta(data.delta_ms)}",
        f"  baches {bar(data.bump)} {data.bump:3d}% | agarre {bar(data.grip)} {data.grip:3d}%",
        f"  aviso de límite {bar(data.limit)} {data.limit:3d}%",
    ]
    if data.raw:
        lines.append(f"  crudo: {data.raw}")
    lines.append(f"  paquete: {telemetry_packet(data).decode('ascii')}")
    return "\n".join(lines)


def main() -> None:
    # Opcional: "python diagnostico.py 10" se para solo a los 10 segundos.
    seconds = 0.0
    if len(sys.argv) > 1:
        try:
            seconds = max(0.0, float(sys.argv[1]))
        except ValueError:
            seconds = 0.0

    reader = AcSharedMemory()
    reader.raw_debug = True
    print("Gyromovil - diagnóstico de telemetría de Assetto Corsa")
    if seconds > 0:
        print(f"Se parará solo a los {seconds:g} s (Ctrl+C para salir antes).\n")
    else:
        print("Pulsa Ctrl+C para salir.\n")
    limit = time.monotonic() + seconds if seconds > 0 else None
    try:
        while True:
            data = reader.read()
            print(block(data), flush=True)
            print()
            if limit is not None and time.monotonic() >= limit:
                break
            time.sleep(INTERVALO)
    except KeyboardInterrupt:
        print("Fin.")
    finally:
        reader.close()


if __name__ == "__main__":
    main()
