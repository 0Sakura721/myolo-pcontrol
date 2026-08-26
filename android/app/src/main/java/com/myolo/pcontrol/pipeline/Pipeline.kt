package com.myolo.pcontrol.pipeline

import android.content.Context
import android.graphics.Bitmap
import android.graphics.BitmapFactory
import com.myolo.pcontrol.inference.DeviceTier
import com.myolo.pcontrol.inference.NcnnDetector
import com.myolo.pcontrol.net.TcpClient
import com.myolo.pcontrol.protocol.CommandEncoder
import java.io.File

/** 全局配置（简单内存状态，联网前由 MainActivity 写入） */
object AppConfig {
    @Volatile var serverIp = "192.168.1.100"
    @Volatile var serverPort = 9999  // 与 pc/server.py 默认端口一致
}

/**
 * 管线单例：把「检测器 + TCP 客户端」串起来。
 *  - [ensureModel] 加载 .param/.bin（需用户放入 files/models）
 *  - [processFrame] 由捕获回调驱动：检测 → 最高置信度目标中心 → move 指令发送
 *  - [connect]/[sendClick]/[sendScroll] 由 UI 调用
 */
object Pipeline {

    /** 画面来源：手机屏幕（本机 MediaProjection 捕获） */
    const val MODE_PHONE_SCREEN = "phone_screen"
    /** 画面来源：电脑画面流（接收服务端推流 JPEG 帧） */
    const val MODE_PC_STREAM = "pc_stream"

    @Volatile var running = false

    /** 当前画面来源模式，默认电脑画面流 */
    @Volatile var captureMode = MODE_PC_STREAM

    private val detector = NcnnDetector
    private val tcp = TcpClient()

    @Volatile private var modelLoaded = false

    /** 模型文件名（可改为 yolo26n.param / yolo26n.bin 等，与导出的模型一致） */
    @Volatile var modelParam = "model.param"
    @Volatile var modelBin = "model.bin"

    private const val MODELS_DIR = "models"
    private const val PREFS_NAME = "myolo_prefs"
    private const val KEY_PARAM = "model_param"
    private const val KEY_BIN = "model_bin"
    @Volatile private var prefsLoaded = false

    /**
     * 加载模型（幂等）。首次调用时从 SharedPreferences 恢复用户选中的模型。
     * @return 加载成功与否（模型缺失/失败返回 false）
     */
    fun ensureModel(context: Context): Boolean {
        if (modelLoaded) return true
        if (!prefsLoaded) {
            val sp = context.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)
            sp.getString(KEY_PARAM, null)?.let { modelParam = it }
            sp.getString(KEY_BIN, null)?.let { modelBin = it }
            prefsLoaded = true
        }
        val cfg = DeviceTier.backend
        val param = File(modelsDir(context), modelParam)
        val bin = File(modelsDir(context), modelBin)
        if (!param.exists() || !bin.exists()) return false
        val ok = detector.create(param.absolutePath, bin.absolutePath, cfg.useGpu)
        modelLoaded = ok
        return ok
    }

    // ------------------------------------------------------------------
    // 模型管理（列表/切换/删除），供 ModelManagerActivity 使用
    // ------------------------------------------------------------------
    private fun modelsDir(context: Context) = File(context.filesDir, MODELS_DIR).apply { mkdirs() }

    /** 列出已导入的模型对（.param + 同名 .bin） */
    fun listModels(context: Context): List<Pair<String, String>> {
        val dir = modelsDir(context)
        return dir.listFiles()
            ?.filter { it.isFile && it.name.endsWith(".param") }
            ?.mapNotNull { p ->
                val bin = File(dir, p.name.removeSuffix(".param") + ".bin")
                if (bin.exists()) p.name to bin.name else null
            }
            ?.sortedBy { it.first } ?: emptyList()
    }

    /** 启用指定模型并记忆选择；返回加载是否成功 */
    fun setActiveModel(context: Context, param: String, bin: String): Boolean {
        modelLoaded = false
        modelParam = param
        modelBin = bin
        context.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)
            .edit().putString(KEY_PARAM, param).putString(KEY_BIN, bin).apply()
        return ensureModel(context)
    }

    /** 删除模型文件（连同 .bin） */
    fun deleteModel(context: Context, param: String, bin: String) {
        val dir = modelsDir(context)
        File(dir, param).delete()
        File(dir, bin).delete()
    }

    /** 捕获回调入口：每帧推理并发送指令 */
    fun processFrame(rgba: ByteArray, w: Int, h: Int) {
        if (!running) return
        val det = try {
            detector.detect(rgba, w, h)
        } catch (e: Exception) {
            return
        }
        if (det.size >= 6) {
            tcp.sendJson(CommandEncoder.encodeMoveByDetection(det))
        } else {
            tcp.sendJson(CommandEncoder.encodeNone())
        }
    }

    /**
     * 电脑画面流入口：收到一帧 JPEG → 解码 → 缩放（宽 640）→ 紧凑 RGBA8888 → 检测 → 发送。
     * 该回调仅在订阅电脑画面流后触发（[MODE_PC_STREAM]），无需受 running（本机捕获）门控。
     */
    fun processJpeg(jpeg: ByteArray) {
        val bmp = try {
            BitmapFactory.decodeByteArray(jpeg, 0, jpeg.size)
        } catch (e: Exception) {
            null
        } ?: return

        // 等比缩放到宽 640
        val targetW = 640
        val scale = if (bmp.width > 0) targetW.toFloat() / bmp.width.toFloat() else 1f
        val targetH = ((bmp.height * scale).toInt()).coerceAtLeast(1)
        val scaled = if (bmp.width != targetW) {
            Bitmap.createScaledBitmap(bmp, targetW, targetH, true)
        } else {
            bmp
        }
        val w = scaled.width
        val h = scaled.height

        // 像素 ARGB → 紧凑 RGBA8888
        val pixels = IntArray(w * h)
        scaled.getPixels(pixels, 0, w, 0, 0, w, h)
        val rgba = ByteArray(w * h * 4)
        var idx = 0
        for (p in pixels) {
            rgba[idx++] = ((p shr 16) and 0xFF).toByte() // R
            rgba[idx++] = ((p shr 8) and 0xFF).toByte()  // G
            rgba[idx++] = (p and 0xFF).toByte()          // B
            rgba[idx++] = ((p shr 24) and 0xFF).toByte() // A
        }
        if (scaled !== bmp) scaled.recycle()
        bmp.recycle()

        val det = try {
            detector.detect(rgba, w, h)
        } catch (e: Exception) {
            return
        }
        if (det.size >= 6) {
            tcp.sendJson(CommandEncoder.encodeMoveByDetection(det))
        } else {
            tcp.sendJson(CommandEncoder.encodeNone())
        }
    }

    /**
     * 切换画面来源。电脑画面流模式：连接后自动订阅；切走时取消订阅（未连接时为空操作）。
     */
    fun switchCaptureMode(mode: String) {
        captureMode = mode
        if (mode == MODE_PC_STREAM) tcp.subscribeScreen(10) else tcp.unsubscribeScreen()
    }

    fun connect(context: Context, listener: TcpClient.Listener?) {
        val base = listener ?: object : TcpClient.Listener {
            override fun onConnected() {}
            override fun onDisconnected(reason: String?) {}
        }
        tcp.listener = object : TcpClient.Listener {
            override fun onConnected() {
                // 电脑画面流：连接建立后自动订阅服务端推流
                if (captureMode == MODE_PC_STREAM) tcp.subscribeScreen(10)
                base.onConnected()
            }
            override fun onDisconnected(reason: String?) = base.onDisconnected(reason)
        }
        ensureModel(context)
        tcp.connect(AppConfig.serverIp, AppConfig.serverPort)
    }

    fun disconnect() = tcp.disconnect()

    fun sendClick(x: Float, y: Float) =
        tcp.sendJson(CommandEncoder.encodeClick(x, y, "left"))

    fun sendScroll(delta: Int) =
        tcp.sendJson(CommandEncoder.encodeScroll(delta))
}
