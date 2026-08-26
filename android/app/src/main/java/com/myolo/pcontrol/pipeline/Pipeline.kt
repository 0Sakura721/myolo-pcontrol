package com.myolo.pcontrol.pipeline

import android.content.Context
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

    @Volatile var running = false

    private val detector = NcnnDetector
    private val tcp = TcpClient()

    @Volatile private var modelLoaded = false

    /** 模型文件名（可改为 yolo26n.param / yolo26n.bin 等，与导出的模型一致） */
    @Volatile var modelParam = "model.param"
    @Volatile var modelBin = "model.bin"

    /**
     * 加载模型（幂等）。模型文件需放到 files/models/ 下：
     *   adb push model.param /data/data/com.myolo.pcontrol/files/models/
     *   adb push model.bin   /data/data/com.myolo.pcontrol/files/models/
     * @return 加载成功与否（模型缺失/失败返回 false）
     */
    fun ensureModel(context: Context): Boolean {
        if (modelLoaded) return true
        val cfg = DeviceTier.backend
        val dir = File(context.filesDir, "models").apply { mkdirs() }
        val param = File(dir, modelParam)
        val bin = File(dir, modelBin)
        if (!param.exists() || !bin.exists()) return false
        val ok = detector.create(param.absolutePath, bin.absolutePath, cfg.useGpu)
        modelLoaded = ok
        return ok
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

    fun connect(context: Context, listener: TcpClient.Listener?) {
        if (listener != null) tcp.listener = listener
        ensureModel(context)
        tcp.connect(AppConfig.serverIp, AppConfig.serverPort)
    }

    fun disconnect() = tcp.disconnect()

    fun sendClick(x: Float, y: Float) =
        tcp.sendJson(CommandEncoder.encodeClick(x, y, "left"))

    fun sendScroll(delta: Int) =
        tcp.sendJson(CommandEncoder.encodeScroll(delta))
}
