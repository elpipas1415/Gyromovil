# Gyromovil — volante por giro + FFB de Assetto Corsa

Convierte el celular en un volante para **Assetto Corsa (AC1)**: la app manda
dirección, pedales y marchas por WiFi, y el celular **vibra con la telemetría
del juego** (baches, pianos y límite de agarre).

```
 Celular (Android)                        PC (Windows)
 ┌──────────────────┐   UDP 5005    ┌──────────────────────────┐
 │ volante por giro │ ────────────► │ server.py                │
 │ pedal / marchas  │               │  ├─ vgamepad → mando Xbox│
 │ HUD + vibración  │ ◄──────────── │  └─ ac_shm.py → AC       │
 └──────────────────┘  telemetría   └──────────────────────────┘
```

## 1. Requisitos

| Qué | Detalle |
| --- | --- |
| Juego | **Assetto Corsa** (el primero). ACC y AC Evo usan otra memoria compartida y no están soportados. |
| Windows | 10 u 11, 64 bits |
| Python | 3.11 o 3.12 de 64 bits (marca *Add python.exe to PATH* al instalar) |
| Driver | [ViGEmBus](https://github.com/nefarius/ViGEmBus/releases) — crea el mando Xbox virtual |
| Red | Celular y PC en la **misma WiFi** |

## 2. Instalación en el PC

1. Instala **ViGEmBus** (`ViGEmBus_..._x64.msi` o `.exe`) y **reinicia el PC**.
2. Copia la carpeta `pc` al PC.
3. Doble clic en **`Iniciar-Gyromovil.bat`**.
   - La primera vez instala `vgamepad` solo.
   - Si Windows pregunta por el firewall, pulsa **Permitir** (redes privadas).
4. Elige `1` (servidor normal) o `2` (diagnóstico de telemetría).

El servidor muestra la IP del PC; la app también la encuentra sola.

## 3. Instalación en el celular

1. Instala `Gyromovil.apk` (el que genera GitHub Actions, ver abajo).
2. Abre la app. Si no encuentra el PC, escribe la IP que mostró el servidor.
3. Conduce: el celular vibra según lo que pase en el juego.

## 4. Configurar el mando en Assetto Corsa

Content Manager → **Settings → Controls → Axis/Buttons**, elige el mando
**Xbox 360 Controller for Windows** y asigna:

| Acción | Control |
| --- | --- |
| Dirección | Stick izquierdo, eje **X** |
| Acelerador | Gatillo derecho (**RT**) |
| Freno | Gatillo izquierdo (**LT**) |
| Subir marcha | **RB** |
| Bajar marcha | **LB** |
| Freno de mano (modo drift) | **B** |
| Embrague (modo drift) | **X** |

Desactiva en AC el "mando combinado" y las ayudas de dirección automática si
quieres sentir el FFB real del coche.

> **Importante:** abre el servidor **antes** que Assetto Corsa. El juego
> detecta los mandos al arrancar; si ya estaba abierto, ciérralo y ábrelo otra vez.

## 5. Vibración (FFB)

En la app: **Ajustes → Vibración**.

| Modo | Qué hace |
| --- | --- |
| Normal | Vibra según la fuerza de los pedales |
| Simple | Solo cambio de marcha y paso acelerador ↔ freno |
| Sin vibración | Nada |
| **FFB del juego** | Baches/pianos y límite de agarre reales |

En modo *FFB del juego* hay dos sliders:

- **Baches y curbs**: golpes y traqueteo al pisar pianos, baches y bordillos.
- **Límite de agarre**: zumbido continuo cuando las ruedas deslizan
  (bloqueo de frenada, derrapes, subviraje/sobreviraje).
- **Aviso antes de perder agarre**: tics cortos que se aceleran cuando el coche
  se acerca al límite, justo antes de que empiece el zumbido. Se distingue por
  el ritmo: golpes de curb = pulso largo y fuerte, aviso = tics, agarre
  perdido = zumbido continuo.

La intensidad general se ajusta con **Intensidad** y **Vibrar al cambiar de
marcha**. El modo FFB se apaga solo si el juego deja de mandar datos
(menú, pausa o boxes), así que no se queda vibrando.

El PC lee la memoria del juego a **~200 Hz** (aunque mande la telemetría a
50 Hz) para no perder los pianos, que duran pocos milisegundos.

### Cómo se calcula (pc/ac_shm.py)

- **Baches**: velocidad del recorrido de suspensión + desviación brusca del
  vector de aceleración `accG` respecto a su media lenta.
- **Agarre**: deslizamiento longitudinal real de cada rueda
  (`|ω·radio − v| / v`) y ángulo de deriva de la carrocería
  (`localVelocity`).
- **Aviso de límite**: el mismo deslizamiento y ángulo de deriva, pero en la
  zona previa al umbral de pérdida (`_LIMIT_FRACTION`, 45 % del umbral).
  Limitación: no detecta subviraje puro, porque ahí la carrocería no
  se desliza todavía.

Si vibra demasiado o demasiado poco, mueve los sliders de la app. Para cambiar
la sensibilidad de base, edita las constantes `_BUMP_*` y `_GRIP_*` al
principio de `pc/ac_shm.py`.

## 6. Comprobar la telemetría

Con el juego abierto y el coche en pista:

```
cd pc
python diagnostico.py
```

Muestra coche, circuito, marcha, RPM, velocidad, tiempos, delta y las barras
de **baches** y **agarre**. Si las barras se mueven, el FFB funcionará. Este
diagnóstico **no** necesita ViGEmBus.

Se para con **Ctrl+C**. También puedes pedirle una duración y se cierra solo:

```
python diagnostico.py 10
```

Pruebas automáticas (sin juego ni driver):

```
cd pc
python -m unittest -v test_ac_shm
```

## 7. Problemas frecuentes

| Síntoma | Causa / solución |
| --- | --- |
| El mando no aparece en Assetto Corsa | Abre el servidor antes que el juego, o reinicia AC |
| "No se pudo crear el mando Xbox virtual" | Falta ViGEmBus o no se reinició el PC |
| `pip install vgamepad` falla | Usa Python 3.11/3.12 de 64 bits |
| La app no encuentra el PC | Firewall de Windows: permite Python en red privada. O escribe la IP a mano |
| El mando funciona pero no hay datos del juego | El juego debe estar **en pista** (no en menú/repetición). Comprueba con `diagnostico.py` |
| "Datos del juego: sin señal" | AC cerrado, en pausa, o el servidor se abrió antes que el juego (se reconecta solo cada 2 s) |
| No vibra en modo FFB | Modo *FFB del juego* seleccionado, sliders > 0%, y "Usar datos del juego" activado |
| Se siente "pegajoso" el volante | Ajustes → Dirección → Respuesta (bájala) |
| El delta sale `--.---` | Necesita una vuelta de referencia: el PC se la guarda al cruzar la línea y el delta aparece en la vuelta siguiente. Las vueltas con paradas, boxes o saltos del juego no se usan como referencia |

## 8. Protocolo UDP (puerto 5005)

**App → PC** (cada 16 ms):

```
steer,gas,brake,up,down,handbrake,clutch
-1..1, 0..1, 0..1, 0|1, 0|1, 0|1, 0|1
```

Se aceptan también los 5 primeros campos (apps antiguas).

**PC → app** (50 Hz, solo mientras se conduce):

```
T,marcha,rpm,rpmMax,kmh,actual,ultima,mejor,delta,baches,agarre,limite
delta = milisegundos con signo (+ = más lento) o "N" (sin vuelta de referencia)
baches, agarre, limite = 0..100
```

**Descubrimiento**: la app manda `GYRO?` al broadcast; el PC responde `GYRO!`.

## 9. Compilar el APK

El repo incluye `.github/workflows/build.yml`: cada push compila el APK y lo
deja como artefacto **Gyromovil** en la pestaña *Actions*. El proyecto no
incluye Gradle Wrapper, así que en local hace falta Gradle 8.7 + Android
SDK 34.

## 10. Archivos

```
pc/ac_shm.py              lector de memoria compartida de AC + cálculo del FFB
pc/server.py              mando Xbox virtual + envío de telemetría
pc/diagnostico.py         comprobación de telemetría (sin ViGEmBus)
pc/test_ac_shm.py         pruebas automáticas
pc/Iniciar-Gyromovil.bat  lanzador con comprobación de dependencias
pc/requirements.txt       dependencias (vgamepad)
app/.../MainActivity.kt   app Android (HUD, volante, vibración)
VERSION.txt               versión de la app y del PC + cambios
```

## 11. Versiones

La versión del **PC** se ve al arrancar el servidor (`versión 1.13 del PC`);
la de la **app**, en Android → *Ajustes → Aplicaciones → Gyromovil*. El zip se
entrega con el número de versión en el nombre (`Gyromovil-v1.13.zip`),
así que si el nombre no coincide con lo que dice el servidor al arrancar, es una
copia vieja.
