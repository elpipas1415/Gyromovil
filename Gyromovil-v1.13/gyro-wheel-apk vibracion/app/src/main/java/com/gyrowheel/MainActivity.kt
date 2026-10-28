package com.gyrowheel

import android.app.Activity
import android.content.Context
import android.content.pm.ActivityInfo
import android.graphics.Canvas
import android.graphics.Color
import android.graphics.Paint
import android.graphics.RadialGradient
import android.graphics.RectF
import android.graphics.Shader
import android.graphics.Typeface
import android.hardware.Sensor
import android.hardware.SensorEvent
import android.hardware.SensorEventListener
import android.hardware.SensorManager
import android.os.Bundle
import android.view.Gravity
import android.view.MotionEvent
import android.view.Surface
import android.view.View
import android.view.WindowManager
import android.widget.Button
import android.widget.EditText
import android.widget.LinearLayout
import android.widget.TextView
import android.app.AlertDialog
import android.net.wifi.WifiManager
import android.os.Build
import android.os.VibrationEffect
import android.os.Vibrator
import android.widget.ScrollView
import android.widget.SeekBar
import android.widget.Switch
import android.graphics.Bitmap
import android.graphics.BitmapShader
import android.os.Handler
import android.os.Looper
import android.content.res.ColorStateList
import android.os.SystemClock
import android.view.ViewGroup
import android.widget.RadioButton
import android.widget.RadioGroup
import java.net.DatagramPacket
import java.net.DatagramSocket
import java.net.InetAddress
import java.util.Locale
import kotlin.math.abs
import kotlin.math.atan2
import kotlin.math.ceil
import kotlin.math.max
import kotlin.math.min
import kotlin.math.roundToInt

// Paleta GT3: carbono, grafito, plata y acentos de volante de carreras
private val CARBON = 0xFF0F1113.toInt()
private val GRAFITO = 0xFF2B2F35.toInt()
private val GRAFITO_OSC = 0xFF15181B.toInt()
private val ALCANTARA = 0xFF3A3F46.toInt()
private val PLATA = 0xFFC3C8CE.toInt()
private val PLATA_OSC = 0xFF7D858E.toInt()
private val BLANCO = 0xFFF2F4F6.toInt()
private val NARANJA = 0xFFFF7A1A.toInt()
private val VERDE_GT = 0xFF2BD66A.toInt()
private val ROJO_GT = 0xFFF0392B.toInt()
private val AZUL_GT = 0xFF3A8DFF.toInt()
private val AMARILLO_GT = 0xFFFFC21A.toInt()
private val APAGADO = 0xFF4A5057.toInt()

/** Ajustes del usuario (se guardan en el celular). */
object Cfg {
    var hapMode = 0        // 0 normal, 1 simple, 2 sin vibración
    var gearHaptic = true  // vibrar al cambiar de marcha (en cualquier modo)
    var level = 1          // 0 suave, 1 media, 2 fuerte
    var invert = false
    var dead = 0.04f       // zona muerta del pedal
    var smooth = 0.4f      // respuesta de la dirección
    var drift = false      // modo drift: freno de mano y embrague
    var telemetry = true   // usar marcha y revoluciones del juego
    var bumpGain = 150     // fuerza de la vibración por baches y curbs (%)
    var gripGain = 100     // fuerza de la vibración por agarre perdido (%)
    var limitGain = 100    // fuerza del aviso antes de perder agarre (%)
    var clutchInvert = false
}

class MainActivity : Activity(), SensorEventListener {
    private lateinit var sm: SensorManager
    private var dash: DashView? = null
    private var addr: String? = null
    @Volatile private var running = false
    private var raw = 0f
    private var offset = 0f
    private var smooth = 0f
    private var hasReading = false
    private var range = 180f
    private var vib: Vibrator? = null
    private val handler = Handler(Looper.getMainLooper())
    private var pumping = false
    @Volatile private var inSettings = false
    private var holdUntil = 0L
    @Volatile private var searching = false
    // FFB del juego: señales suavizadas y control de repetición de los pulsos.
    private var ffbBump = 0f
    private var ffbGrip = 0f
    private var ffbLastBump = 0L
    private var ffbLastGrip = 0L
    private var ffbLimit = 0f
    private var ffbLastLimit = 0L

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        // Orientación bloqueada en horizontal (no gira al mover el celular)
        requestedOrientation = ActivityInfo.SCREEN_ORIENTATION_LANDSCAPE
        window.addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
        sm = getSystemService(Context.SENSOR_SERVICE) as SensorManager
        @Suppress("DEPRECATION")
        vib = getSystemService(Context.VIBRATOR_SERVICE) as? Vibrator
        loadCfg()
        showConnect()
    }

    private fun showConnect() {
        val prefs = getSharedPreferences("gw", MODE_PRIVATE)
        val serif = Typeface.create(Typeface.SERIF, Typeface.BOLD)
        val box = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            gravity = Gravity.CENTER
            setBackgroundColor(CARBON)
            setPadding(80, 30, 80, 30)
        }
        val title = TextView(this).apply {
            text = "Gyromovil"; textSize = 34f; setTextColor(BLANCO); gravity = Gravity.CENTER
            typeface = serif
        }
        val status = TextView(this).apply {
            setTextColor(NARANJA); gravity = Gravity.CENTER; setPadding(0, 10, 0, 10)
        }
        val ip = EditText(this).apply {
            setText(prefs.getString("ip", ""))
            hint = "o escribe la IP (192.168.1.20)"
            setTextColor(BLANCO); setHintTextColor(Color.GRAY); gravity = Gravity.CENTER
            setSingleLine()
        }
        val go = Button(this).apply {
            text = "Conectar"
            setOnClickListener {
                searching = false
                val a2 = ip.text.toString().trim()
                if (a2.isNotEmpty()) {
                    prefs.edit().putString("ip", a2).apply()
                    addr = a2
                    startDash()
                }
            }
        }
        val find = {
            status.text = "Buscando tu PC…"
            discover({ found ->
                prefs.edit().putString("ip", found).apply()
                addr = found
                startDash()
            }, { status.text = "No encontré el PC. Abre el servidor en la PC o escribe la IP." })
        }
        val again = Button(this).apply { text = "Buscar de nuevo"; setOnClickListener { find() } }
        box.addView(title); box.addView(status); box.addView(ip); box.addView(go); box.addView(again)
        setContentView(box)
        find()
    }

    private fun startDash() {
        val d = DashView(this)
        d.onCenter = { offset = raw; smooth = 0f }
        d.onRange = {
            range = when (range) { 120f -> 180f; 180f -> 270f; 270f -> 360f; else -> 120f }
            d.rangeDeg = range
            saveCfg()
        }
        d.rangeDeg = range
        d.onHaptic = { buzz(it) }
        d.onPedal = { startPump() }
        d.onSettings = { showSettings() }
        dash = d
        setContentView(d)
        startSensorsAndSending()
    }

    private fun startSensorsAndSending() {
        val d = dash ?: return
        val target = addr ?: return
        val s = sm.getDefaultSensor(Sensor.TYPE_GRAVITY) ?: sm.getDefaultSensor(Sensor.TYPE_ACCELEROMETER)
        if (s == null) { d.status = "Este celular no tiene sensor de movimiento"; return }
        sm.registerListener(this, s, SensorManager.SENSOR_DELAY_GAME)
        running = true
        resetFfb()
        handler.removeCallbacks(ffbPump)
        handler.post(ffbPump)
        Thread {
            try {
                val sock = DatagramSocket()
                val ipAddr = InetAddress.getByName(target)
                sock.soTimeout = 500
                startReceiver(sock, d)
                d.status = "Enviando a $target"
                while (running) {
                    val msg = String.format(
                        Locale.US, "%.4f,%.3f,%.3f,%d,%d,%d,%d",
                        if (inSettings) 0f else d.steer, if (inSettings) 0f else d.gas, if (inSettings) 0f else d.brake,
                        if (!inSettings && d.up) 1 else 0, if (!inSettings && d.down) 1 else 0,
                        if (!inSettings && d.handbrake) 1 else 0, if ((!inSettings && d.clutch) != Cfg.clutchInvert) 1 else 0
                    )
                    val b = msg.toByteArray()
                    sock.send(DatagramPacket(b, b.size, ipAddr, 5005))
                    d.postInvalidate()
                    Thread.sleep(16)
                }
                sock.close()
            } catch (e: Exception) {
                d.status = "Error: ${e.message}"
                d.postInvalidate()
            }
        }.start()
    }

    /** Mientras el pedal está activo, vibra cada vez más fuerte cuanto más lo empujas. */
    private val pump = object : Runnable {
        override fun run() {
            val d = dash
            val g = d?.gas ?: 0f
            val br = d?.brake ?: 0f
            val level = max(g, br)
            if (d != null && level > 0f && Cfg.hapMode == 0) {
                val braking = br > g
                if (SystemClock.uptimeMillis() >= holdUntil) gradualBuzz(level, braking)
                handler.postDelayed(this, if (braking) 100L else 60L)
            } else {
                pumping = false
                vib?.cancel()
            }
        }
    }

    private fun startPump() {
        if (pumping || Cfg.hapMode != 0) return
        pumping = true
        handler.post(pump)
    }

    /** Acelerar: zumbido continuo. Frenar: pulsos. Los dos crecen con la fuerza del pedal. */
    private fun gradualBuzz(level: Float, braking: Boolean) {
        val v = vib ?: return
        if (!v.hasVibrator()) return
        val scale = floatArrayOf(0.5f, 0.75f, 1f)[Cfg.level.coerceIn(0, 2)]
        val amp = (30 + 225 * level * scale).toInt().coerceIn(1, 255)
        val ms = if (braking) 50L else 70L
        if (Build.VERSION.SDK_INT >= 26) {
            // sin control de intensidad en el motor, se simula alargando el pulso
            val dur = if (v.hasAmplitudeControl()) ms else (ms * (0.3f + 0.7f * level)).toLong().coerceAtLeast(10L)
            v.vibrate(VibrationEffect.createOneShot(dur, amp))
        } else {
            @Suppress("DEPRECATION") v.vibrate(ms)
        }
    }

    private fun loadCfg() {
        val p = getSharedPreferences("gw", MODE_PRIVATE)
        Cfg.hapMode = p.getInt("mode", 0)
        Cfg.gearHaptic = p.getBoolean("gearhap", true)
        Cfg.drift = p.getBoolean("drift", false)
        Cfg.telemetry = p.getBoolean("tele", true)
        Cfg.bumpGain = p.getInt("bump2", 150)   // clave nueva: todos parten del nuevo valor agresivo
        Cfg.gripGain = p.getInt("grip", 100)
        Cfg.limitGain = p.getInt("limit", 100)
        Cfg.clutchInvert = p.getBoolean("cinv", false)
        range = p.getFloat("range", 180f)
        Cfg.level = p.getInt("lvl", 1)
        Cfg.invert = p.getBoolean("inv", false)
        Cfg.dead = p.getFloat("dead", 0.04f)
        Cfg.smooth = p.getFloat("smo", 0.4f)
    }

    private fun saveCfg() {
        getSharedPreferences("gw", MODE_PRIVATE).edit()
            .putInt("mode", Cfg.hapMode).putBoolean("gearhap", Cfg.gearHaptic).putBoolean("drift", Cfg.drift).putBoolean("tele", Cfg.telemetry).putInt("bump2", Cfg.bumpGain).putInt("limit", Cfg.limitGain).putInt("grip", Cfg.gripGain).putBoolean("cinv", Cfg.clutchInvert).putFloat("range", range).putInt("lvl", Cfg.level).putBoolean("inv", Cfg.invert)
            .putFloat("dead", Cfg.dead).putFloat("smo", Cfg.smooth).apply()
    }

    /**
     * Modo FFB: vibra según los baches, pianos y el límite de agarre que calcula el PC.
     *
     * Los valores llegan a 50 Hz y ya vienen limitados a 0..100. Aquí se suavizan
     * para que la vibración no "tiemble" y se convierten en pulsos cortos:
     * los baches son golpes secos y el límite de agarre es un zumbido continuo.
     */
    private val ffbPump = object : Runnable {
        override fun run() {
            if (!running) return
            val d = dash
            val now = SystemClock.uptimeMillis()
            if (d == null || inSettings || Cfg.hapMode != 3 || !d.ffbOn) {
                resetFfb()
                handler.postDelayed(this, 50)
                return
            }

            val targetBump = min(1f, d.tBump / 100f * (Cfg.bumpGain / 100f))
            val targetGrip = min(1f, d.tGrip / 100f * (Cfg.gripGain / 100f))
            val targetLimit = min(1f, d.tLimit / 100f * (Cfg.limitGain / 100f))
            // Los golpes entran de inmediato; el resto sube y baja suave para no parpadear.
            ffbBump += (targetBump - ffbBump) * if (targetBump > ffbBump) 0.90f else 0.25f
            ffbGrip += (targetGrip - ffbGrip) * if (targetGrip > ffbGrip) 0.35f else 0.12f
            ffbLimit += (targetLimit - ffbLimit) * if (targetLimit > ffbLimit) 0.40f else 0.20f
            if (ffbBump < 0.01f) ffbBump = 0f
            if (ffbGrip < 0.01f) ffbGrip = 0f
            if (ffbLimit < 0.01f) ffbLimit = 0f

            // Un clic de marcha o de tope de pedal tiene prioridad un instante.
            if (now < holdUntil) {
                handler.postDelayed(this, 40)
                return
            }

            val k = 0.7f + 0.3f * floatArrayOf(0.5f, 0.75f, 1f)[Cfg.level.coerceIn(0, 2)]
            // 1) Curbs y baches (prioridad máxima): golpe largo y casi a toda la fuerza.
            //    Un golpe grande da además un "mazazo" de 110 ms a tope. Repetidos sin
            //    pausa se sienten como el traqueteo de un piano.
            if (ffbBump >= 0.05f) {
                if (ffbBump >= 0.45f && now - ffbLastBump >= 130L) {
                    ffbLastBump = now
                    pulse(110L, 255)
                } else if (now - ffbLastBump >= 30L) {
                    ffbLastBump = now
                    pulse(80L, (255 * (0.55f + 0.45f * ffbBump) * k).toInt())
                }
                handler.postDelayed(this, 20)
                return
            }
            // 2) Agarre perdido: zumbido continuo (pulsos solapados).
            if (ffbGrip >= 0.08f) {
                if (now - ffbLastGrip >= 55L) {
                    ffbLastGrip = now
                    pulse(55L, (30 + 150 * ffbGrip * k).toInt())
                }
                handler.postDelayed(this, 20)
                return
            }
            // 3) A punto de perder agarre: tics cortos que se aceleran al acercarse al
            //    límite (190 ms entre tics lejos, 60 ms casi encima). No se confunde con
            //    el zumbido continuo del agarre perdido ni con los golpes de curb.
            if (ffbLimit >= 0.08f) {
                val period = (190f - 130f * ffbLimit).toLong()
                if (now - ffbLastLimit >= period) {
                    ffbLastLimit = now
                    pulse(30L, (90 + 130 * ffbLimit * k).toInt())
                }
            }
            handler.postDelayed(this, 20)
        }
    }

    /** Vuelve los filtros del FFB a cero (menús, pausa, cambio de PC o de ajustes). */
    private fun resetFfb() {
        ffbBump = 0f
        ffbGrip = 0f
        ffbLastBump = 0L
        ffbLastGrip = 0L
        ffbLimit = 0f
        ffbLastLimit = 0L
    }

    /** Recibe del PC la marcha y las revoluciones del juego ("T,marcha,rpm,rpmMax,km/h"). */
    private fun startReceiver(sock: DatagramSocket, d: DashView) {
        Thread {
            val buf = ByteArray(128)
            while (running && !sock.isClosed) {
                try {
                    val pk = DatagramPacket(buf, buf.size)
                    sock.receive(pk)
                    val parts = String(pk.data, 0, pk.length).split(",")
                    if (parts.size >= 5 && parts[0] == "T") {
                        d.tGear = parts[1].trim().toInt()
                        d.tRpm = parts[2].trim().toInt()
                        d.tMaxRpm = parts[3].trim().toInt()
                        d.tSpeed = parts[4].trim().toFloat()
                        if (parts.size >= 11) {
                            d.tCur = parts[5].trim().toInt()
                            d.tLast = parts[6].trim().toInt()
                            d.tBest = parts[7].trim().toInt()
                            d.tDelta = if (parts[8].trim() == "N") Int.MIN_VALUE else parts[8].trim().toInt()
                            d.tBump = parts[9].trim().toInt()
                            d.tGrip = parts[10].trim().toInt()
                            d.tLimit = if (parts.size >= 12) (parts[11].trim().toIntOrNull() ?: 0) else 0
                        }
                        d.tStamp = SystemClock.uptimeMillis()
                    }
                } catch (e: java.net.SocketTimeoutException) {
                } catch (e: Exception) {
                }
            }
        }.start()
    }

    private fun pulse(ms: Long, amp: Int) {
        val v = vib ?: return
        if (!v.hasVibrator()) return
        val a = amp.coerceIn(1, 255)
        if (Build.VERSION.SDK_INT >= 26) {
            val effect = if (v.hasAmplitudeControl()) {
                VibrationEffect.createOneShot(ms, a)
            } else {
                // Sin control de intensidad: se acorta el pulso para que se sienta más suave.
                val dur = (ms * (0.30f + 0.70f * a / 255f)).toLong().coerceAtLeast(10L)
                VibrationEffect.createOneShot(dur, 255)
            }
            v.vibrate(effect)
        } else @Suppress("DEPRECATION") v.vibrate(ms)
    }

    /** kind: 1 = cambio de marcha, 2 = tope del pedal, 3 = paso de acelerador a freno (siempre fuerte) */
    private fun buzz(kind: Int) {
        when (kind) {
            1 -> if (!Cfg.gearHaptic) return
            2 -> if (Cfg.hapMode != 0) return
            // El golpe al pasar de acelerar a frenar se mantiene también en modo
            // FFB: es corto y el FFB se reanuda solo cuando termina.
            3 -> if (Cfg.hapMode == 2) return
        }
        val k = floatArrayOf(0.5f, 0.75f, 1f)[Cfg.level.coerceIn(0, 2)]
        val ms = when (kind) { 1 -> 25L; 2 -> 40L; else -> 130L }
        holdUntil = SystemClock.uptimeMillis() + ms + 40L   // que el zumbido gradual no lo tape
        when (kind) {
            1 -> pulse(ms, (60 + 195 * k).toInt())
            2 -> pulse(ms, (80 + 175 * k).toInt())
            else -> pulse(ms, 255)
        }
    }

    private fun testBuzz() {
        val k = floatArrayOf(0.5f, 0.75f, 1f)[Cfg.level.coerceIn(0, 2)]
        listOf(0L to 0.2f, 300L to 0.55f, 600L to 1f).forEach { (t, lv) ->
            handler.postDelayed({ pulse(70, (30 + 225 * lv * k).toInt()) }, t)
        }
        handler.postDelayed({ pulse(130, 255) }, 1000L)
    }

    // ---- pantalla de ajustes ----
    private fun tint(c: Int) = ColorStateList.valueOf(c)

    private fun hdr(t: String) = TextView(this).apply {
        text = t; textSize = 22f; setTextColor(NARANJA); setPadding(0, 24, 0, 8)
        typeface = Typeface.create("sans-serif-condensed", Typeface.BOLD)
    }

    private fun txt(t: String) = TextView(this).apply {
        text = t; textSize = 16f; setTextColor(BLANCO); setPadding(0, 16, 0, 4)
    }

    private fun toggleRow(t: String, on: Boolean, f: (Boolean) -> Unit) = Switch(this).apply {
        text = t; textSize = 16f; isChecked = on; setTextColor(BLANCO); thumbTintList = tint(NARANJA)
        setPadding(0, 16, 0, 8)
        setOnCheckedChangeListener { _, v -> f(v) }
    }

    private fun slider(label: String, min: Int, max: Int, cur: Int, fmt: (Int) -> String, f: (Int) -> Unit): LinearLayout {
        val l = txt("$label: ${fmt(cur)}")
        val s = SeekBar(this).apply {
            this.max = max - min
            progress = cur - min
            progressTintList = tint(NARANJA)
            thumbTintList = tint(NARANJA)
            setOnSeekBarChangeListener(object : SeekBar.OnSeekBarChangeListener {
                override fun onProgressChanged(sb: SeekBar?, p: Int, user: Boolean) {
                    l.text = "$label: ${fmt(p + min)}"
                    f(p + min)
                }
                override fun onStartTrackingTouch(sb: SeekBar?) {}
                override fun onStopTrackingTouch(sb: SeekBar?) {}
            })
        }
        return LinearLayout(this).apply { orientation = LinearLayout.VERTICAL; addView(l); addView(s) }
    }

    private fun radios(options: List<String>, cur: Int, f: (Int) -> Unit) = RadioGroup(this).apply {
        options.forEachIndexed { i, o ->
            addView(RadioButton(this@MainActivity).apply {
                id = 1000 + i; text = o; textSize = 16f; setTextColor(BLANCO)
                buttonTintList = tint(NARANJA); isChecked = i == cur
                setPadding(8, 12, 8, 12)
            })
        }
        setOnCheckedChangeListener { _, id -> f(id - 1000) }
    }

    private fun action(t: String, f: () -> Unit) = Button(this).apply { text = t; setOnClickListener { f() } }

    private fun page(i: Int, d: DashView, refresh: () -> Unit): View {
        val col = LinearLayout(this).apply { orientation = LinearLayout.VERTICAL; setPadding(32, 16, 48, 40) }
        fun add(vararg v: View) = v.forEach { col.addView(it) }
        when (i) {
            0 -> add(
                hdr("Vibración"),
                txt("Modo"),
                radios(listOf("Normal: sigue la fuerza de los pedales", "Simple: solo marcha y cambio de acelerador a freno", "Sin vibración", "FFB del juego: baches, curbs y límite de agarre"), Cfg.hapMode) { Cfg.hapMode = it },
                toggleRow("Vibrar al cambiar de marcha", Cfg.gearHaptic) { Cfg.gearHaptic = it },
                slider("Intensidad", 0, 2, Cfg.level, { listOf("Suave", "Media", "Fuerte")[it] }) { Cfg.level = it },
                slider("Baches y curbs (modo FFB)", 0, 300, Cfg.bumpGain, { "$it %" }) { Cfg.bumpGain = it },
                slider("Límite de agarre (modo FFB)", 0, 200, Cfg.gripGain, { "$it %" }) { Cfg.gripGain = it },
                slider("Aviso antes de perder agarre (modo FFB)", 0, 200, Cfg.limitGain, { "$it %" }) { Cfg.limitGain = it },
                action("Probar vibración") { testBuzz() }
            )
            1 -> add(
                hdr("Dirección"),
                slider("Giro total", 90, 540, range.roundToInt().coerceIn(90, 540), { "$it°" }) { range = it.toFloat(); d.rangeDeg = range },
                slider("Respuesta", 1, 9, (Cfg.smooth * 10f).roundToInt().coerceIn(1, 9), { "${it * 10} %" }) { Cfg.smooth = it / 10f },
                toggleRow("Invertir dirección", Cfg.invert) { Cfg.invert = it },
                action("Centrar volante") { offset = raw; smooth = 0f }
            )
            2 -> add(
                hdr("Pedales"),
                slider("Zona muerta", 0, 15, (Cfg.dead * 100f).roundToInt().coerceIn(0, 15), { "$it %" }) { Cfg.dead = it / 100f }
            )
            3 -> add(
                hdr("Modo de juego"),
                radios(listOf("Carrera: marchas y pedales", "Drift: agrega freno de mano y embrague"), if (Cfg.drift) 1 else 0) { Cfg.drift = it == 1 },
                toggleRow("Invertir embrague (si en el juego va al revés)", Cfg.clutchInvert) { Cfg.clutchInvert = it }
            )
            else -> add(
                hdr("Conexión"),
                txt("PC actual: ${addr ?: "sin conectar"}"),
                txt(if (d.telemetryOn) "Datos del juego: conectados" else "Datos del juego: sin señal (abre Assetto Corsa y entra a pista)"),
                toggleRow("Usar datos del juego (marcha y luces)", Cfg.telemetry) { Cfg.telemetry = it },
                action("Buscar otro PC") { changePc() },
                action("Restablecer todos los ajustes") { resetCfg(); refresh() }
            )
        }
        return col
    }

    private fun showSettings() {
        val d = dash ?: return
        inSettings = true
        // Sin telemetría vibrando detrás del menú.
        resetFfb()
        handler.removeCallbacks(ffbPump)
        vib?.cancel()
        val root = LinearLayout(this).apply { orientation = LinearLayout.HORIZONTAL; setBackgroundColor(CARBON) }
        val tabs = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL; setBackgroundColor(GRAFITO_OSC); setPadding(20, 20, 20, 20)
        }
        val content = ScrollView(this)
        var current = 0
        fun show(i: Int) {
            current = i
            content.removeAllViews()
            content.addView(page(i, d) { show(current) })
        }
        listOf("Vibración", "Dirección", "Pedales", "Modo", "Conexión").forEachIndexed { i, n ->
            tabs.addView(action(n) { show(i) })
        }
        tabs.addView(action("← Volver") { closeSettings() })
        val mp = ViewGroup.LayoutParams.MATCH_PARENT
        root.addView(ScrollView(this).apply { addView(tabs) }, LinearLayout.LayoutParams(0, mp, 0.3f))
        root.addView(content, LinearLayout.LayoutParams(0, mp, 0.7f))
        setContentView(root)
        show(0)
    }

    private fun closeSettings() {
        inSettings = false
        saveCfg()
        resetFfb()
        dash?.let { setContentView(it) }
        if (running) {
            handler.removeCallbacks(ffbPump)
            handler.post(ffbPump)
        }
    }

    private fun changePc() {
        inSettings = false
        running = false
        sm.unregisterListener(this)
        handler.removeCallbacks(pump)
        handler.removeCallbacks(ffbPump)
        resetFfb()
        pumping = false
        vib?.cancel()
        dash = null
        showConnect()
    }

    private fun resetCfg() {
        Cfg.hapMode = 0; Cfg.gearHaptic = true; Cfg.level = 1; Cfg.invert = false
        Cfg.dead = 0.04f; Cfg.smooth = 0.4f; Cfg.drift = false; Cfg.telemetry = true
        Cfg.bumpGain = 150; Cfg.gripGain = 100; Cfg.limitGain = 100; Cfg.clutchInvert = false
        range = 180f
        dash?.rangeDeg = range
        saveCfg()
    }

    @Suppress("DEPRECATION")
    override fun onBackPressed() {
        if (inSettings) closeSettings() else super.onBackPressed()
    }

    /** Busca el servidor del PC mandando un aviso a toda la red WiFi. */
    private fun discover(onFound: (String) -> Unit, onFail: () -> Unit) {
        searching = true
        Thread {
            var found: String? = null
            try {
                val sock = DatagramSocket()
                sock.broadcast = true
                sock.soTimeout = 700
                val msg = "GYRO?".toByteArray()
                val targets = mutableListOf("255.255.255.255")
                subnetBroadcast()?.let { targets.add(it) }
                val buf = ByteArray(32)
                var tries = 0
                while (searching && found == null && tries < 5) {
                    tries++
                    for (t in targets) {
                        try {
                            sock.send(DatagramPacket(msg, msg.size, InetAddress.getByName(t), 5005))
                        } catch (e: Exception) { }
                    }
                    try {
                        val reply = DatagramPacket(buf, buf.size)
                        sock.receive(reply)
                        if (String(reply.data, 0, reply.length) == "GYRO!") found = reply.address.hostAddress
                    } catch (e: java.net.SocketTimeoutException) { }
                }
                sock.close()
            } catch (e: Exception) { }
            val result = found
            runOnUiThread {
                if (searching) {
                    searching = false
                    if (result != null) onFound(result) else onFail()
                }
            }
        }.start()
    }

    @Suppress("DEPRECATION")
    private fun subnetBroadcast(): String? {
        val wm = applicationContext.getSystemService(Context.WIFI_SERVICE) as? WifiManager ?: return null
        val d = wm.dhcpInfo ?: return null
        if (d.ipAddress == 0) return null
        val b = (d.ipAddress and d.netmask) or d.netmask.inv()
        return "${b and 255}.${(b shr 8) and 255}.${(b shr 16) and 255}.${(b shr 24) and 255}"
    }

    override fun onResume() {
        super.onResume()
        if (dash != null && !running) startSensorsAndSending()
    }

    override fun onPause() {
        super.onPause()
        running = false
        handler.removeCallbacks(pump)
        handler.removeCallbacks(ffbPump)
        pumping = false
        resetFfb()
        vib?.cancel()
        saveCfg()
        sm.unregisterListener(this)
    }

    @Suppress("DEPRECATION")
    override fun onSensorChanged(e: SensorEvent) {
        val x = e.values[0]
        val y = e.values[1]
        val right: Float
        val up: Float
        when (windowManager.defaultDisplay.rotation) {
            Surface.ROTATION_90 -> { right = -y; up = x }
            Surface.ROTATION_270 -> { right = y; up = -x }
            Surface.ROTATION_180 -> { right = -x; up = -y }
            else -> { right = x; up = y }
        }
        raw = Math.toDegrees(atan2(-right, up).toDouble()).toFloat()
        if (!hasReading) { hasReading = true; offset = raw }
        var delta = raw - offset
        while (delta > 180) delta -= 360
        while (delta < -180) delta += 360
        if (Cfg.invert) delta = -delta
        smooth += (delta - smooth) * Cfg.smooth
        dash?.steer = (smooth / (range / 2f)).coerceIn(-1f, 1f)
    }

    override fun onAccuracyChanged(s: Sensor?, a: Int) {}
}

class DashView(ctx: Context) : View(ctx) {
    @Volatile var steer = 0f
    /** Palanca única: -1 (freno a fondo) ... 0 (reposo) ... +1 (acelerador a fondo) */
    @Volatile var pedal = 0f
    @Volatile var up = false
    @Volatile var down = false
    @Volatile var rangeDeg = 180f
    @Volatile var status = ""
    var onCenter: () -> Unit = {}
    var onRange: () -> Unit = {}
    var onSettings: () -> Unit = {}
    var onHaptic: (Int) -> Unit = {}
    var onPedal: () -> Unit = {}
    @Volatile var handbrake = false
    @Volatile var clutch = false
    @Volatile var tGear = 1
    @Volatile var tRpm = 0
    @Volatile var tMaxRpm = 0
    @Volatile var tSpeed = 0f
    @Volatile var tStamp = 0L
    @Volatile var tCur = -1
    @Volatile var tLast = -1
    @Volatile var tBest = -1
    @Volatile var tDelta = Int.MIN_VALUE
    @Volatile var tBump = 0
    @Volatile var tGrip = 0
    @Volatile var tLimit = 0
    val telemetryOn: Boolean get() = Cfg.telemetry && tMaxRpm > 0 && SystemClock.uptimeMillis() - tStamp < 1500
    /** Para el FFB: si el juego deja de mandar datos (pausa, menú, boxes) se corta en seguida. */
    val ffbOn: Boolean get() = telemetryOn && SystemClock.uptimeMillis() - tStamp < 400

    val gas: Float get() = deadzone(pedal)
    val brake: Float get() = deadzone(-pedal)
    private fun deadzone(x: Float) = if (x < Cfg.dead) 0f else (x - Cfg.dead) / (1f - Cfg.dead)

    private val pedalR = RectF(); private val upR = RectF(); private val downR = RectF()
    private val calR = RectF(); private val rangeR = RectF(); private val settingsR = RectF()
    private val ledR = RectF(); private val tmp = RectF()
    private val handR = RectF(); private val clutchR = RectF()
    private val p = Paint(Paint.ANTI_ALIAS_FLAG)
    private val bgPaint = Paint()
    private val fontMono = Typeface.create(Typeface.MONOSPACE, Typeface.BOLD)
    private val fontCond = Typeface.create("sans-serif-condensed", Typeface.BOLD)
    private var cTop = 0f; private var cH = 1f; private var cCx = 0f; private var cW = 1f
    private var trackCy = 0f; private var halfLen = 1f; private var knobH = 60f
    private var pedalId = -1
    private var lastStep = 0
    private var lastSide = 0
    private var driftCaptionY = 0f
    private var gearCaptionX = 0f; private var gearCaptionY = 0f

    init {
        // Fondo de fibra de carbono: un cuadrito que se repite
        val t = 20
        val bmp = Bitmap.createBitmap(t, t, Bitmap.Config.ARGB_8888)
        val cv = Canvas(bmp)
        val q = Paint()
        cv.drawColor(0xFF111316.toInt())
        q.color = 0xFF1A1D21.toInt()
        cv.drawRect(0f, 0f, t / 2f, t / 2f, q)
        cv.drawRect(t / 2f, t / 2f, t.toFloat(), t.toFloat(), q)
        q.color = 0xFF0C0D0F.toInt()
        cv.drawRect(t / 2f, 0f, t.toFloat(), t / 2f, q)
        bgPaint.shader = BitmapShader(bmp, Shader.TileMode.REPEAT, Shader.TileMode.REPEAT)
    }

    override fun onSizeChanged(w: Int, h: Int, ow: Int, oh: Int) {
        val m = 20f
        val sideW = w * 0.2f
        val gap = 14f
        // Derecha: palanca única
        pedalR.set(w - m - sideW, m, w - m, h - m)
        val hh = pedalR.height()
        knobH = hh * 0.085f
        trackCy = pedalR.centerY()
        halfLen = hh * 0.5f - hh * 0.22f - knobH / 2f
        // Izquierda: ajustes, giro y marchas
        val cbh = h * 0.13f
        settingsR.set(m, m, m + sideW, m + cbh)
        rangeR.set(m, m + cbh + gap, m + sideW, m + 2 * cbh + gap)
        val gb = (sideW - gap) / 2f
        val gy = h / 2f - gb / 2f + cbh * 0.5f
        downR.set(m, gy, m + gb, gy + gb)
        upR.set(m + gb + gap, gy, m + sideW, gy + gb)
        gearCaptionX = m + sideW / 2f
        gearCaptionY = gy - 16f
        handR.set(m, gy + gb + 44f, m + gb, gy + 2 * gb + 44f)
        clutchR.set(m + gb + gap, gy + gb + 44f, m + sideW, gy + 2 * gb + 44f)
        driftCaptionY = gy + gb + 34f
        // Centro: tira de luces, volante y botón de centrar
        val cl = m + sideW + gap
        val cr = pedalR.left - gap
        val cbw = w * 0.2f
        ledR.set(cl, m, cr, m + h * 0.07f)
        calR.set(w / 2f - cbw / 2f, h - m - gap - cbh, w / 2f + cbw / 2f, h - m - gap)
        val availH = calR.top - ledR.bottom
        cTop = ledR.bottom + 10f
        cH = availH - 30f
        cCx = (cl + cr) / 2f
        cW = cr - cl
    }

    override fun onDraw(c: Canvas) {
        c.drawPaint(bgPaint)
        drawLeds(c)
        drawPedalPanel(c)
        drawCenter(c)

        p.style = Paint.Style.FILL
        p.typeface = fontCond
        p.color = PLATA_OSC
        p.textAlign = Paint.Align.CENTER
        p.textSize = 26f
        c.drawText("MARCHA", gearCaptionX, gearCaptionY, p)
        button(c, downR, "−", down, downR.height() * 0.7f, AZUL_GT)
        button(c, upR, "+", up, downR.height() * 0.7f, NARANJA)
        if (Cfg.drift) {
            p.style = Paint.Style.FILL
            p.typeface = fontCond
            p.color = PLATA_OSC
            p.textAlign = Paint.Align.CENTER
            p.textSize = 26f
            c.drawText("DRIFT", gearCaptionX, driftCaptionY, p)
            button(c, handR, "Freno mano", handbrake, 34f, ROJO_GT)
            button(c, clutchR, "Embrague", clutch, 34f, AMARILLO_GT)
        }
        button(c, calR, "Centrar", false, min(calR.height() * 0.42f, 34f), PLATA_OSC)
        button(c, rangeR, "Giro ${rangeDeg.roundToInt()}°", false, min(rangeR.height() * 0.42f, 34f), PLATA_OSC)
        button(c, settingsR, "Ajustes", false, min(settingsR.height() * 0.42f, 34f), PLATA_OSC)

        p.typeface = fontMono
        p.color = APAGADO
        p.textSize = 22f
        c.drawText(status + (if (telemetryOn) " · juego conectado" else "") + (if (telemetryOn && Cfg.hapMode == 3) "  baches ${tBump}% agarre ${tGrip}% límite ${tLimit}%" else ""), width / 2f, height - 4f, p)
    }

    /** Tira de luces como la de un volante GT3: se enciende con el acelerador. */
    private fun drawLeds(c: Canvas) {
        val n = 15
        val cw = ledR.width() / n
        val rad = min(cw, ledR.height()) * 0.36f
        // con datos del juego: sigue las revoluciones (desde el 70 %) y parpadea en el corte; sin datos: sigue el acelerador
        val lit: Int = if (telemetryOn) {
            val f = ((tRpm.toFloat() / tMaxRpm) - 0.70f) / 0.30f
            if (tRpm >= tMaxRpm * 0.985f) {
                if ((SystemClock.uptimeMillis() / 90) % 2L == 0L) n else 0
            } else ceil(f.coerceIn(0f, 1f) * n).toInt()
        } else ceil(gas * n).toInt()
        p.style = Paint.Style.FILL
        for (i in 0 until n) {
            p.color = if (i < lit) {
                if (i < 5) VERDE_GT else if (i < 10) ROJO_GT else AZUL_GT
            } else 0xFF23272C.toInt()
            c.drawCircle(ledR.left + cw * (i + 0.5f), ledR.centerY(), rad, p)
        }
    }

    private fun gearLabel(): String = when (tGear) { 0 -> "R"; 1 -> "N"; else -> (tGear - 1).toString() }

    private fun fmtTime(ms: Int): String {
        if (ms <= 0 || ms > 3_600_000) return "--:--.---"
        return String.format(Locale.US, "%d:%02d.%03d", ms / 60000, (ms % 60000) / 1000, ms % 1000)
    }

    /** Centro: marcha grande, diferencia con tu mejor vuelta, tiempos y barra de dirección. */
    private fun drawCenter(c: Canvas) {
        val on = telemetryOn
        val x = cCx
        p.style = Paint.Style.FILL
        p.textAlign = Paint.Align.CENTER

        // marcha
        p.typeface = fontMono
        p.color = if (on && tGear != 1) NARANJA else APAGADO
        p.textSize = cH * 0.46f
        c.drawText(if (on) gearLabel() else "–", x, cTop + cH * 0.40f, p)

        // diferencia: rojo y "+" = más lento que tu mejor vuelta, verde y "−" = más rápido
        val d = tDelta
        p.textSize = cH * 0.13f
        if (on && d != Int.MIN_VALUE) {
            p.color = if (d > 0) ROJO_GT else VERDE_GT
            c.drawText(String.format(Locale.US, "%s%.3f", if (d > 0) "+" else "−", abs(d) / 1000f), x, cTop + cH * 0.56f, p)
        } else {
            p.color = APAGADO
            c.drawText("--.---", x, cTop + cH * 0.56f, p)
        }

        // tiempos
        val cols = listOf("ACTUAL" to tCur, "ÚLTIMA" to tLast, "MEJOR" to tBest)
        cols.forEachIndexed { i, (name, ms) ->
            val cx = x + (i - 1) * cW * 0.33f
            p.typeface = fontCond; p.color = PLATA_OSC; p.textSize = cH * 0.05f
            c.drawText(name, cx, cTop + cH * 0.68f, p)
            p.typeface = fontMono; p.color = if (on) BLANCO else APAGADO; p.textSize = cH * 0.08f
            c.drawText(if (on) fmtTime(ms) else "--:--.---", cx, cTop + cH * 0.78f, p)
        }

        // barra de dirección
        val half = cW * 0.4f
        val by = cTop + cH * 0.90f
        p.style = Paint.Style.STROKE
        p.strokeCap = Paint.Cap.ROUND
        p.strokeWidth = 8f
        p.color = GRAFITO
        c.drawLine(x - half, by, x + half, by, p)
        p.strokeWidth = 4f
        p.color = PLATA_OSC
        c.drawLine(x, by - 14f, x, by + 14f, p)
        p.style = Paint.Style.FILL
        p.color = NARANJA
        c.drawCircle(x + steer * half, by, 16f, p)
        p.typeface = fontMono
        p.color = PLATA
        p.textSize = cH * 0.05f
        c.drawText("${(steer * rangeDeg / 2f).roundToInt()}°", x, cTop + cH, p)
    }

    private fun drawPedalPanel(c: Canvas) {
        val r = pedalR
        val pw = r.width()
        val cx = r.centerX()
        p.style = Paint.Style.FILL
        p.color = 0xFF0A0B0D.toInt()
        c.drawRoundRect(r, 22f, 22f, p)
        p.style = Paint.Style.STROKE
        p.strokeWidth = 4f
        p.color = PLATA_OSC
        c.drawRoundRect(r, 22f, 22f, p)

        val gasV = gas
        val brakeV = brake
        val tag = pw * 0.075f
        val pct = pw * 0.17f
        p.style = Paint.Style.FILL
        p.textAlign = Paint.Align.CENTER
        p.typeface = fontCond; p.textSize = tag; p.color = PLATA
        c.drawText("ACEL", cx, r.top + 16f + tag + 8f, p)
        p.typeface = fontMono; p.textSize = pct
        p.color = if (gasV > 0f) VERDE_GT else APAGADO
        c.drawText("${(gasV * 100).roundToInt()}%", cx, r.top + 16f + tag + 8f + pct + 8f, p)
        p.color = if (brakeV > 0f) ROJO_GT else APAGADO
        c.drawText("${(brakeV * 100).roundToInt()}%", cx, r.bottom - 16f - tag - 22f, p)
        p.typeface = fontCond; p.textSize = tag; p.color = PLATA
        c.drawText("FRENO", cx, r.bottom - 16f, p)

        // barras por segmentos: verde sube, rojo baja
        val n = 10
        val step = halfLen / n
        val gap = 5f
        val bw = pw * 0.34f
        for (i in 0 until n) {
            tmp.set(cx - bw / 2f, trackCy - (i + 1) * step + gap / 2f, cx + bw / 2f, trackCy - i * step - gap / 2f)
            p.color = if (gasV * n > i) VERDE_GT else 0xFF1B1F23.toInt()
            c.drawRoundRect(tmp, 6f, 6f, p)
            tmp.set(cx - bw / 2f, trackCy + i * step + gap / 2f, cx + bw / 2f, trackCy + (i + 1) * step - gap / 2f)
            p.color = if (brakeV * n > i) ROJO_GT else 0xFF1B1F23.toInt()
            c.drawRoundRect(tmp, 6f, 6f, p)
        }

        // perilla de aluminio
        val ky = trackCy - pedal * halfLen
        val kw = pw * 0.8f
        tmp.set(cx - kw / 2f, ky - knobH / 2f, cx + kw / 2f, ky + knobH / 2f)
        p.color = PLATA_OSC
        c.drawRoundRect(tmp, 12f, 12f, p)
        tmp.set(tmp.left + 4f, tmp.top + 4f, tmp.right - 4f, tmp.bottom - 4f)
        p.color = PLATA
        c.drawRoundRect(tmp, 9f, 9f, p)
        p.style = Paint.Style.STROKE
        p.strokeCap = Paint.Cap.BUTT
        p.strokeWidth = 5f
        p.color = NARANJA
        c.drawLine(cx - kw / 2f + 14f, ky, cx + kw / 2f - 14f, ky, p)
    }

    private fun button(c: Canvas, r: RectF, label: String, pressed: Boolean, textSize: Float, accent: Int) {
        p.style = Paint.Style.FILL
        p.color = if (pressed) accent else GRAFITO_OSC
        c.drawRoundRect(r, 14f, 14f, p)
        p.style = Paint.Style.STROKE
        p.strokeWidth = 4f
        p.color = accent
        c.drawRoundRect(r, 14f, 14f, p)
        p.style = Paint.Style.FILL
        p.typeface = fontCond
        p.color = if (pressed) CARBON else BLANCO
        p.textAlign = Paint.Align.CENTER
        p.textSize = textSize
        while (p.measureText(label) > r.width() - 14f && p.textSize > 12f) p.textSize -= 1f
        c.drawText(label, r.centerX(), r.centerY() + p.textSize / 3f, p)
    }

    override fun onTouchEvent(e: MotionEvent): Boolean {
        val act = e.actionMasked
        if (act == MotionEvent.ACTION_CANCEL) {
            pedalId = -1; pedal = 0f; up = false; down = false; handbrake = false; clutch = false
            invalidate()
            return true
        }
        val lifting = if (act == MotionEvent.ACTION_UP || act == MotionEvent.ACTION_POINTER_UP) e.actionIndex else -1
        if (act == MotionEvent.ACTION_DOWN || act == MotionEvent.ACTION_POINTER_DOWN) {
            val i = e.actionIndex
            val x = e.getX(i); val y = e.getY(i)
            when {
                pedalR.contains(x, y) -> pedalId = e.getPointerId(i)
                calR.contains(x, y) -> onCenter()
                rangeR.contains(x, y) -> onRange()
                settingsR.contains(x, y) -> onSettings()
            }
        }
        if (lifting >= 0 && e.getPointerId(lifting) == pedalId) pedalId = -1

        var v = 0f; var u = false; var d = false; var hb = false; var cl = false
        for (i in 0 until e.pointerCount) {
            if (i == lifting) continue
            val x = e.getX(i); val y = e.getY(i)
            if (e.getPointerId(i) == pedalId) {
                v = ((trackCy - y) / halfLen).coerceIn(-1f, 1f)   // arriba acelera, abajo frena
            } else if (upR.contains(x, y)) {
                u = true
            } else if (downR.contains(x, y)) {
                d = true
            } else if (Cfg.drift && handR.contains(x, y)) {
                hb = true
            } else if (Cfg.drift && clutchR.contains(x, y)) {
                cl = true
            }
        }
        // vibración fuerte al pasar de acelerador a freno (o al revés) en un mismo gesto
        val side = if (v > 0.1f) 1 else if (v < -0.1f) -1 else lastSide
        if (pedalId == -1) {
            lastSide = 0
        } else {
            if (lastSide != 0 && side != lastSide) onHaptic(3)
            lastSide = side
        }
        if (u && !up) onHaptic(1)          // clic al cambiar de marcha
        if (d && !down) onHaptic(1)
        val step = (v * 10f).toInt()
        if (pedalId != -1 && step != lastStep && abs(step) >= 10) onHaptic(2)   // golpe al llegar al tope
        lastStep = step
        pedal = v; up = u; down = d; handbrake = hb; clutch = cl   // al soltar, la palanca vuelve al centro
        if (pedalId != -1 && v != 0f) onPedal()
        invalidate()
        return true
    }
}
