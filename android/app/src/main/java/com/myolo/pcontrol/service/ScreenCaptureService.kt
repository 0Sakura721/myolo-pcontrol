package com.myolo.pcontrol.service

import android.app.Activity
import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.Service
import android.content.Context
import android.content.Intent
import android.content.pm.ServiceInfo
import android.media.projection.MediaProjectionManager
import android.os.Build
import android.os.IBinder
import androidx.core.app.NotificationCompat
import androidx.core.content.IntentCompat
import com.myolo.pcontrol.R
import com.myolo.pcontrol.capture.ScreenCapture
import com.myolo.pcontrol.inference.DeviceTier
import com.myolo.pcontrol.inference.Tier
import com.myolo.pcontrol.pipeline.Pipeline

/**
 * 屏幕捕获前台服务。
 * API 34 起，MediaProjection 必须在带 mediaProjection 类型的前台服务中创建，
 * 且须先 startForeground 再 getMediaProjection。
 */
class ScreenCaptureService : Service() {

    companion object {
        const val EXTRA_RESULT_CODE = "result_code"
        const val EXTRA_RESULT_DATA = "result_data"
        private const val CHANNEL_ID = "screen_capture"
        private const val NOTIF_ID = 1
    }

    private var capture: ScreenCapture? = null
    private lateinit var projectionManager: MediaProjectionManager

    override fun onCreate() {
        super.onCreate()
        projectionManager =
            getSystemService(Context.MEDIA_PROJECTION_SERVICE) as MediaProjectionManager
        createChannel()
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        val resultCode =
            intent?.getIntExtra(EXTRA_RESULT_CODE, Activity.RESULT_CANCELED) ?: Activity.RESULT_CANCELED
        val data = intent?.let {
            IntentCompat.getParcelableExtra(it, EXTRA_RESULT_DATA, Intent::class.java)
        }

        startForeground(NOTIF_ID, buildNotification(),
            if (Build.VERSION.SDK_INT >= 29) ServiceInfo.FOREGROUND_SERVICE_TYPE_MEDIA_PROJECTION else 0)

        if (data != null) {
            val projection = projectionManager.getMediaProjection(resultCode, data)
            // 按设备档位动态选择捕获分辨率与帧率（硬件感知动态调度，降低低端机发热/卡顿）
            val (w, h, fps) = when (DeviceTier.backend.tier) {
                Tier.LOW -> 320 to 240 to 12
                Tier.MEDIUM -> 480 to 320 to 15
                else -> 640 to 480 to 25
            }
            capture = ScreenCapture(
                projection, w, h,
                resources.displayMetrics.densityDpi,
                fps
            ) { rgba, ww, hh -> Pipeline.processFrame(rgba, ww, hh) }
            capture?.start()
            Pipeline.running = true
        }
        return START_STICKY
    }

    override fun onDestroy() {
        Pipeline.running = false
        capture?.stop()
        capture = null
        super.onDestroy()
    }

    override fun onBind(intent: Intent?): IBinder? = null

    private fun createChannel() {
        if (Build.VERSION.SDK_INT >= 26) {
            val channel = NotificationChannel(
                CHANNEL_ID, "屏幕捕获", NotificationManager.IMPORTANCE_LOW
            )
            getSystemService(NotificationManager::class.java).createNotificationChannel(channel)
        }
    }

    private fun buildNotification(): Notification {
        return NotificationCompat.Builder(this, CHANNEL_ID)
            .setContentTitle(getString(R.string.app_name))
            .setContentText("屏幕捕获运行中")
            .setSmallIcon(android.R.drawable.ic_menu_camera)
            .setOngoing(true)
            .build()
    }
}
