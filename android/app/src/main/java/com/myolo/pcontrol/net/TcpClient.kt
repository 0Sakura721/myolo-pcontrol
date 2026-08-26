package com.myolo.pcontrol.net

import org.json.JSONObject
import java.io.InputStream
import java.net.InetSocketAddress
import java.net.Socket

/**
 * TCP 客户端：
 *  - 帧格式：[4 字节大端长度][JSON 载荷]
 *  - 断线重连：指数退避（1s,2s,4s,8s,16s...，封顶 30s）
 *  - 心跳线程：每 2s 发送 {"op":"ping"}
 *  - 连接状态回调：[Listener]
 */
class TcpClient {

    interface Listener {
        fun onConnected()
        fun onDisconnected(reason: String?)
        /** 收到一帧 JPEG 图片（电脑画面流）。默认空实现，兼容现有监听者。 */
        fun onJpegFrame(bytes: ByteArray) {}
    }

    @Volatile var listener: Listener? = null

    @Volatile private var running = false
    @Volatile private var host = ""
    @Volatile private var port = 0
    @Volatile private var socket: Socket? = null
    @Volatile private var attempt = 0

    private val writeLock = Any()
    private val stateLock = Object()

    companion object {
        private const val PING_INTERVAL_MS = 2000L
        private const val CONNECT_TIMEOUT_MS = 3000
        private const val SO_TIMEOUT_MS = 5000
        private const val MAX_BACKOFF_SHIFT = 5 // 1<<5 = 32s，取封顶 30s
        private const val MAX_PAYLOAD = 512 * 1024
    }

    /** 建立连接并启动自动重连（幂等） */
    fun connect(host: String, port: Int) {
        synchronized(stateLock) {
            if (running) return
            running = true
            this.host = host
            this.port = port
            val t = Thread({ runLoop() }, "tcp-worker").apply { isDaemon = true; start() }
        }
    }

    /** 主动断开 */
    fun disconnect() {
        running = false
        try { socket?.close() } catch (_: Exception) {}
    }

    /** 发送一条 JSON（带长度前缀） */
    fun sendJson(obj: JSONObject): Boolean {
        return sendRaw(obj.toString().toByteArray(Charsets.UTF_8))
    }

    /** 订阅电脑画面流（服务端按 fps 推 JPEG 帧） */
    fun subscribeScreen(fps: Int): Boolean {
        return sendJson(
            JSONObject().put("op", "subscribe_screen").put("fps", fps).put("quality", 70)
        )
    }

    /** 取消订阅电脑画面流 */
    fun unsubscribeScreen(): Boolean {
        return sendJson(JSONObject().put("op", "unsubscribe_screen"))
    }

    // ---- 内部实现 ----

    private fun runLoop() {
        var delay = 1_000L
        while (running) {
            try {
                val s = Socket().apply {
                    connect(InetSocketAddress(host, port), CONNECT_TIMEOUT_MS)
                    soTimeout = SO_TIMEOUT_MS
                    tcpNoDelay = true
                }
                socket = s
                attempt = 0
                listener?.onConnected()
                startHeartbeat()
                readLoop(s) // 阻塞直到断开
            } catch (e: Exception) {
                if (running) listener?.onDisconnected(e.message)
            }
            if (!running) break
            try { Thread.sleep(delay) } catch (ie: InterruptedException) { break }
            delay = (1_000L shl minOf(attempt, MAX_BACKOFF_SHIFT)).coerceAtMost(30_000L)
            attempt++
        }
    }

    private fun startHeartbeat() {
        val t = Thread({
            while (running && socket?.isConnected == true) {
                try { sendRaw(pingJson()) } catch (_: Exception) {}
                try { Thread.sleep(PING_INTERVAL_MS) } catch (ie: InterruptedException) { break }
            }
        }, "tcp-heartbeat").apply { isDaemon = true; start() }
    }

    /**
     * 读回包。服务端→客户端帧格式：[4 字节大端长度][1 字节类型][载荷]。
     *  - 类型 0x00：载荷为 JSON 回执（丢弃）
     *  - 类型 0x01：载荷为 JPEG 图片字节，回调 [Listener.onJpegFrame]
     */
    private fun readLoop(s: Socket) {
        val input = s.getInputStream()
        try {
            while (running) {
                val len = readFrameLen(input) ?: break
                if (len <= 0 || len > MAX_PAYLOAD) break
                val type = input.read()
                if (type < 0) break
                val payload = ByteArray(len)
                var read = 0
                while (read < len) {
                    val n = input.read(payload, read, len - read)
                    if (n < 0) break
                    read += n
                }
                if (read < len) break
                when (type) {
                    0x01 -> listener?.onJpegFrame(payload)
                    else -> { /* 0x00 及其它：JSON 回执，当前丢弃 */ }
                }
            }
        } catch (e: Exception) {
            if (running) listener?.onDisconnected(e.message)
        }
    }

    private fun readFrameLen(input: InputStream): Int? {
        val b0 = input.read(); if (b0 < 0) return null
        val b1 = input.read(); if (b1 < 0) return null
        val b2 = input.read(); if (b2 < 0) return null
        val b3 = input.read(); if (b3 < 0) return null
        return (b0 shl 24) or (b1 shl 16) or (b2 shl 8) or b3
    }

    /** 带长度前缀发送原始字节 */
    private fun sendRaw(payload: ByteArray): Boolean {
        val s = socket ?: return false
        if (!s.isConnected || s.isClosed) return false
        return try {
            synchronized(writeLock) {
                val out = s.getOutputStream()
                val header = ByteArray(4).also {
                    it[0] = ((payload.size shr 24) and 0xFF).toByte()
                    it[1] = ((payload.size shr 16) and 0xFF).toByte()
                    it[2] = ((payload.size shr 8) and 0xFF).toByte()
                    it[3] = (payload.size and 0xFF).toByte()
                }
                out.write(header)
                out.write(payload)
                out.flush()
            }
            true
        } catch (e: Exception) {
            false
        }
    }

    private fun pingJson(): ByteArray =
        JSONObject().put("op", "ping").toString().toByteArray(Charsets.UTF_8)
}
