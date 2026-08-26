package com.myolo.pcontrol

import android.net.Uri
import android.os.Bundle
import android.widget.Button
import android.widget.LinearLayout
import android.widget.ProgressBar
import android.widget.TextView
import android.widget.Toast
import androidx.activity.result.contract.ActivityResultContracts
import androidx.appcompat.app.AppCompatActivity
import com.myolo.pcontrol.pipeline.Pipeline
import java.io.File
import java.net.HttpURLConnection
import java.net.URL

/**
 * 模型管理页：在线下载（内置模型清单，下载后自动启用）、
 * 本地导入（系统文件选择器，可多选）、启用（点击）、删除（长按）。
 * 模型保存路径：/data/data/com.myolo.pcontrol/files/models/
 */
class ModelManagerActivity : AppCompatActivity() {

    private lateinit var tvCurrent: TextView
    private lateinit var listBox: LinearLayout
    private lateinit var onlineBox: LinearLayout
    private lateinit var progress: ProgressBar

    /** 导入模型文件（任意扩展名均可选，导入时按 .param/.bin 过滤） */
    private val importLauncher =
        registerForActivityResult(ActivityResultContracts.OpenMultipleDocuments()) { uris ->
            if (!uris.isNullOrEmpty()) importFiles(uris)
        }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_model_manager)

        tvCurrent = findViewById(R.id.tvCurrentModel)
        listBox = findViewById(R.id.modelListBox)
        onlineBox = findViewById(R.id.onlineBox)
        progress = findViewById(R.id.modelProgress)
        val btnImport = findViewById<Button>(R.id.btnImportModel)
        val btnRefresh = findViewById<Button>(R.id.btnRefreshModel)

        btnImport.setOnClickListener {
            importLauncher.launch(arrayOf("*/*")) // 系统文件选择器，用户挑 .param/.bin
        }
        btnRefresh.setOnClickListener { refreshList() }
        refreshList()
    }

    // ------------------------------------------------------------------
    // 在线下载
    // ------------------------------------------------------------------
    private fun buildOnlineList() {
        onlineBox.removeAllViews()
        for (item in ModelCatalog.ITEMS) {
            val row = TextView(this).apply {
                text = "📥 ${item.displayName}  (~${item.sizeMb}MB)\n" +
                        "    ${item.desc}\n    点击下载到手机并自动启用"
                textSize = 14f
                setPadding(16, 14, 16, 14)
            }
            row.setOnClickListener { downloadModel(item) }
            onlineBox.addView(row)
        }
    }

    private fun downloadModel(item: ModelCatalog.ModelItem) {
        progress.visibility = ProgressBar.VISIBLE
        Toast.makeText(this, "开始下载 ${item.displayName} ...", Toast.LENGTH_SHORT).show()
        Thread {
            val dir = File(filesDir, "models").apply { mkdirs() }
            var ok = true
            try {
                download(item.paramUrl, File(dir, "${item.id}.param"))
                download(item.binUrl, File(dir, "${item.id}.bin"), minBytes = 100 * 1024)
            } catch (e: Exception) {
                ok = false
            }
            runOnUiThread {
                progress.visibility = ProgressBar.GONE
                if (ok) {
                    val loaded = Pipeline.setActiveModel(this, "${item.id}.param", "${item.id}.bin")
                    Toast.makeText(
                        this,
                        if (loaded) "下载完成并启用：${item.displayName}"
                        else "下载完成，但模型加载失败（可能与解码层不匹配）",
                        Toast.LENGTH_LONG
                    ).show()
                    refreshList()
                } else {
                    Toast.makeText(this, "下载失败：请检查网络后重试", Toast.LENGTH_LONG).show()
                }
            }
        }.start()
    }

    private fun download(url: String, dest: File, minBytes: Long = 0) {
        val conn = URL(url).openConnection() as HttpURLConnection
        conn.connectTimeout = 10_000
        conn.readTimeout = 120_000
        conn.instanceFollowRedirects = true // GitHub release asset 会 302 到对象存储
        try {
            conn.inputStream.use { input ->
                dest.outputStream().use { output -> input.copyTo(output) }
            }
            if (dest.length() < minBytes) {
                dest.delete()
                throw IllegalStateException("下载字节过少: $url")
            }
        } finally {
            conn.disconnect()
        }
    }

    // ------------------------------------------------------------------
    // 本地文件
    // ------------------------------------------------------------------

    /** 把选中的 .param/.bin 拷贝到 files/models/ 下 */
    private fun importFiles(uris: List<Uri>) {
        val dir = File(filesDir, "models").apply { mkdirs() }
        var imported = 0
        for (uri in uris) {
            val name = queryDisplayName(uri) ?: continue
            if (!name.endsWith(".param") && !name.endsWith(".bin")) continue
            try {
                contentResolver.openInputStream(uri)?.use { input ->
                    File(dir, name).outputStream().use { input.copyTo(it) }
                }
                imported++
            } catch (e: Exception) {
                Toast.makeText(this, "导入 $name 失败", Toast.LENGTH_SHORT).show()
            }
        }
        if (imported > 0) Toast.makeText(this, "已导入 $imported 个文件", Toast.LENGTH_SHORT).show()
        refreshList()
    }

    private fun queryDisplayName(uri: Uri): String? {
        return try {
            contentResolver.query(uri, null, null, null, null)?.use { c ->
                if (c.moveToFirst()) c.getString(c.getColumnIndexOrThrow("_display_name")) else null
            }
        } catch (e: Exception) {
            uri.lastPathSegment // 兜底
        }
    }

    private fun refreshList() {
        tvCurrent.text = "当前模型：${Pipeline.modelParam} + ${Pipeline.modelBin}"
        listBox.removeAllViews()
        buildOnlineList()

        val models = Pipeline.listModels(this)
        if (models.isEmpty()) {
            val hint = TextView(this).apply {
                text = "本地还没有模型文件。\n" +
                        "可在上方「在线模型」下载，或点「导入模型文件」从存储选择。\n" +
                        "也可 adb push 到 /data/data/com.myolo.pcontrol/files/models/"
                textSize = 14f
                setPadding(16, 16, 16, 16)
            }
            listBox.addView(hint)
        }

        for ((param, bin) in models) {
            val active = param == Pipeline.modelParam
            val row = TextView(this).apply {
                text = (if (active) "● " else "○ ") + param +
                        "\n    点击启用 · 长按删除（当前模型后需重新加载）"
                textSize = 14f
                setPadding(16, 14, 16, 14)
            }
            row.setOnClickListener { enableModel(param, bin) }
            row.setOnLongClickListener {
                Pipeline.deleteModel(this, param, bin)
                Toast.makeText(this, "已删除 $param", Toast.LENGTH_SHORT).show()
                refreshList(); true
            }
            listBox.addView(row)
        }
    }

    private fun enableModel(param: String, bin: String) {
        progress.visibility = ProgressBar.VISIBLE
        Thread {
            val ok = Pipeline.setActiveModel(this, param, bin)
            runOnUiThread {
                progress.visibility = ProgressBar.GONE
                Toast.makeText(
                    this,
                    if (ok) "已启用 $param" else "加载失败：模型不兼容或文件损坏",
                    Toast.LENGTH_LONG
                ).show()
                refreshList()
            }
        }.start()
    }

    override fun onResume() {
        super.onResume()
        refreshList()
    }
}
