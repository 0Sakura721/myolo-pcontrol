package com.myolo.pcontrol.capture

import android.graphics.PixelFormat
import android.hardware.display.DisplayManager
import android.hardware.display.VirtualDisplay
import android.media.Image
import android.media.ImageReader
import android.media.projection.MediaProjection
import android.os.Handler
import android.os.HandlerThread

/** 帧回调：rgba 为紧凑 W*H*4 的 RGBA8888 像素缓冲（fun interface，支持 SAM lambda） */
fun interface FrameCallback {
    fun onFrame(rgba: ByteArray, width: Int, height: Int)
}

/**
 * 屏幕捕获：MediaProjection + VirtualDisplay + ImageReader。
 *  - 像素格式 RGBA_8888
 *  - 目标分辨率 640x480（可降为 320x240）
 *  - maxImages = 2
 *  - 回调里复用字节缓冲，并处理 rowStride 对齐
 */
class ScreenCapture(
    private val mediaProjection: MediaProjection,
    private val width: Int,
    private val height: Int,
    private val densityDpi: Int,
    private val callback: FrameCallback
) {
    private var imageReader: ImageReader? = null
    private var virtualDisplay: VirtualDisplay? = null
    private val handlerThread = HandlerThread("screen-capture").apply { start() }

    fun start() {
        val reader = ImageReader.newInstance(width, height, PixelFormat.RGBA_8888, 2)
        reader.setOnImageAvailableListener({ onImageAvailable(it) }, Handler(handlerThread.looper!!))
        imageReader = reader
        virtualDisplay = mediaProjection.createVirtualDisplay(
            "ScreenCapture",
            width, height, densityDpi,
            DisplayManager.VIRTUAL_DISPLAY_FLAG_AUTO_MIRROR,
            reader.surface,
            null, null
        )
    }

    private fun onImageAvailable(reader: ImageReader) {
        val image = reader.acquireLatestImage() ?: return
        try {
            val plane = image.planes[0]
            val buffer = plane.buffer
            val pixelStride = plane.pixelStride
            val rowStride = plane.rowStride
            val rowPadding = rowStride - pixelStride * width

            // 复用缓冲，避免每帧分配
            var data = ByteArray(rowStride * height)
            buffer.rewind()
            buffer.get(data)

            // rowStride 可能与 w*4 不一致，去掉行填充得到紧凑 RGBA
            if (rowPadding != 0) {
                data = removePadding(data, rowStride, pixelStride, width, height)
            }
            callback.onFrame(data, width, height)
        } catch (e: Exception) {
            // 单帧异常忽略，继续后续帧
        } finally {
            image.close()
        }
    }

    /** 按行拷贝，去除每行尾部填充，输出 w*h*4 紧凑缓冲 */
    private fun removePadding(src: ByteArray, rowStride: Int, pixelStride: Int, w: Int, h: Int): ByteArray {
        val out = ByteArray(w * h * 4)
        for (row in 0 until h) {
            val srcStart = row * rowStride
            val dstStart = row * w * 4
            System.arraycopy(src, srcStart, out, dstStart, w * 4)
        }
        return out
    }

    fun stop() {
        try { virtualDisplay?.release() } catch (_: Exception) {}
        try { imageReader?.close() } catch (_: Exception) {}
        try { mediaProjection.stop() } catch (_: Exception) {}
        handlerThread.quitSafely()
        virtualDisplay = null
        imageReader = null
    }
}
