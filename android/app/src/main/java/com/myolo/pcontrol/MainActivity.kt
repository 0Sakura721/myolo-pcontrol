package com.myolo.pcontrol

import android.app.Activity
import android.content.Intent
import android.content.res.ColorStateList
import android.media.projection.MediaProjectionManager
import android.os.Bundle
import android.view.View
import android.widget.Button
import android.widget.EditText
import android.widget.ImageView
import android.widget.TextView
import android.widget.Toast
import androidx.activity.result.contract.ActivityResultContracts
import androidx.appcompat.app.AppCompatActivity
import androidx.core.content.ContextCompat
import com.google.android.material.button.MaterialButtonToggleGroup
import com.myolo.pcontrol.net.TcpClient
import com.myolo.pcontrol.pipeline.AppConfig
import com.myolo.pcontrol.pipeline.Pipeline
import com.myolo.pcontrol.service.ScreenCaptureService

/**
 * 主界面：申请 MediaProjection 权限 → 启动捕获前台服务 → 连接服务端 → 发送控制指令。
 * 生命周期与线程：
 *  - 屏幕捕获在 [ScreenCaptureService] 前台服务中运行；
 *  - [Pipeline] 作为单例把检测器与 TCP 客户端串起来；
 *  - 网络回调（[TcpClient.Listener]）在线程池回调，需切回主线程更新 UI。
 */
class MainActivity : AppCompatActivity() {

    private lateinit var ipEdit: EditText
    private lateinit var statusText: TextView
    private lateinit var preview: ImageView
    private lateinit var statusDot: View
    private lateinit var guideCard: View

    private var serviceStarted = false
    private lateinit var projectionManager: MediaProjectionManager

    /** 屏幕捕获授权回调（通过 ActivityResult 获取 data） */
    private val captureLauncher = registerForActivityResult(
        ActivityResultContracts.StartActivityForResult()
    ) { result ->
        if (result.resultCode == Activity.RESULT_OK && result.data != null) {
            AppConfig.serverIp = ipEdit.text.toString().trim().ifEmpty { AppConfig.serverIp }
            val intent = Intent(this, ScreenCaptureService::class.java).apply {
                putExtra(ScreenCaptureService.EXTRA_RESULT_CODE, result.resultCode)
                putExtra(ScreenCaptureService.EXTRA_RESULT_DATA, result.data)
            }
            ContextCompat.startForegroundService(this, intent)
            serviceStarted = true
            findViewById<Button>(R.id.btnCaptureStart).isEnabled = false
            findViewById<Button>(R.id.btnCaptureStop).isEnabled = true
            updateStatus("捕获中，目标 ${AppConfig.serverIp}:${AppConfig.serverPort}", R.color.status_connected)
        } else {
            updateStatus("用户取消授权", R.color.status_idle)
        }
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_main)
        projectionManager =
            getSystemService(MEDIA_PROJECTION_SERVICE) as MediaProjectionManager

        ipEdit = findViewById(R.id.ipEdit)
        statusText = findViewById(R.id.statusText)
        preview = findViewById(R.id.preview)
        statusDot = findViewById(R.id.statusDot)
        guideCard = findViewById(R.id.guideCard)
        setConnectionButtons(false)

        // 画面来源切换：电脑画面流（默认）/ 手机屏幕
        findViewById<MaterialButtonToggleGroup>(R.id.sourceGroup).addOnButtonCheckedListener { _, checkedId, isChecked ->
            if (!isChecked) return@addOnButtonCheckedListener
            if (checkedId == R.id.radioPcStream) {
                Pipeline.switchCaptureMode(Pipeline.MODE_PC_STREAM)
            } else if (checkedId == R.id.radioPhoneScreen) {
                Pipeline.switchCaptureMode(Pipeline.MODE_PHONE_SCREEN)
            }
        }

        findViewById<Button>(R.id.btnCaptureStart).setOnClickListener { startCapture() }
        findViewById<Button>(R.id.btnCaptureStop).setOnClickListener { stopCapture() }
        findViewById<Button>(R.id.btnConnect).setOnClickListener { connectServer() }
        findViewById<Button>(R.id.btnDisconnect).setOnClickListener {
            Pipeline.disconnect()
            updateStatus("已断开", R.color.status_disconnected)
            setConnectionButtons(false)
            guideCard.visibility = View.VISIBLE
        }
        findViewById<Button>(R.id.btnClick).setOnClickListener {
            // 点击屏幕中心（演示；实际可用触摸坐标）
            Pipeline.sendClick(0.5f, 0.5f)
        }
        findViewById<Button>(R.id.btnScrollUp).setOnClickListener {
            Pipeline.sendScroll(-120)
        }
        findViewById<Button>(R.id.btnScrollDown).setOnClickListener {
            Pipeline.sendScroll(120)
        }
        findViewById<Button>(R.id.btnModels).setOnClickListener {
            startActivity(Intent(this, ModelManagerActivity::class.java))
        }
    }

    private fun startCapture() {
        // 电脑画面流：不启用本机 MediaProjection，连接服务端后即开始接收电脑画面
        if (Pipeline.captureMode == Pipeline.MODE_PC_STREAM) {
            updateStatus("电脑画面流，请先连接服务端", R.color.status_idle)
            Toast.makeText(this, "电脑画面流：点「连接」后开始接收电脑画面", Toast.LENGTH_LONG).show()
            return
        }
        // 手机屏幕：授权流程，先请求投屏权限
        captureLauncher.launch(projectionManager.createScreenCaptureIntent())
    }

    private fun stopCapture() {
        if (serviceStarted) {
            stopService(Intent(this, ScreenCaptureService::class.java))
            serviceStarted = false
            updateStatus("已停止捕获", R.color.status_idle)
            findViewById<Button>(R.id.btnCaptureStop).isEnabled = false
            findViewById<Button>(R.id.btnCaptureStart).isEnabled = true
        }
    }

    private fun connectServer() {
        val ip = ipEdit.text.toString().trim()
        if (ip.isNotEmpty()) AppConfig.serverIp = ip
        Pipeline.connect(this, object : TcpClient.Listener {
            override fun onConnected() = runOnUiThread {
                updateStatus("已连接 ${AppConfig.serverIp}", R.color.status_connected)
                setConnectionButtons(true)
                guideCard.visibility = View.GONE
            }

            override fun onDisconnected(reason: String?) = runOnUiThread {
                updateStatus("连接断开 ${reason ?: ""}", R.color.status_disconnected)
                setConnectionButtons(false)
                guideCard.visibility = View.VISIBLE
            }
        })
        if (!Pipeline.ensureModel(this)) {
            Toast.makeText(this, "模型缺失：请将 model.param/model.bin 放入 files/models", Toast.LENGTH_LONG).show()
        }
    }

    private fun setConnectionButtons(enabled: Boolean) {
        findViewById<Button>(R.id.btnDisconnect).isEnabled = enabled
        findViewById<Button>(R.id.btnClick).isEnabled = enabled
        findViewById<Button>(R.id.btnScrollUp).isEnabled = enabled
        findViewById<Button>(R.id.btnScrollDown).isEnabled = enabled
    }

    private fun updateStatus(text: String, dotColorRes: Int) {
        statusText.text = text
        statusDot.backgroundTintList = ColorStateList.valueOf(getColor(dotColorRes))
    }

    override fun onDestroy() {
        if (serviceStarted) stopService(Intent(this, ScreenCaptureService::class.java))
        super.onDestroy()
    }
}
