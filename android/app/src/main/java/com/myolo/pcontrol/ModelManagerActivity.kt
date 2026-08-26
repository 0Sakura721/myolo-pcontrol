package com.myolo.pcontrol

import android.net.Uri
import android.os.Bundle
import android.view.LayoutInflater
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
        val inflater = LayoutInflater.from(this)
        for (item in ModelCatalog.ITEMS) {
            val row = inflater.inflate(R.layout.item_online_model, onlineBox, false)
            row.findViewById<TextView>(R.id.tvOnlineName).text =
                (if (item.available) "📥 " else "🚫 ") + item.displayName + "  (~${item.sizeMb}MB)"
            row.findViewById<TextView>(R.id.tvOnlineDesc).text = item.desc
            val state = row.findViewById<TextView>(R.id.tvOnlineState)
            if (item.available) {
                state.text = getString(R.string.model_online_state_download)
                state.setTextColor(getColor(R.color.md_primary))
            } else {
                state.text = getString(R.string.model_online_state_unavail)
                state.setTextColor(getColor(R.color.md_onSurfaceVariant))
            }
            row.setOnClickListener {
                if (item.available) downloadModel(item)
                else Toast.makeText(this, "该模型暂未上架：请用仓库 tools/export_model.py 自行导出", Toast.LENGTH_LONG).show()
            }
            onlineBox.addView(row)
        }
    }

    private fun downloadModel(item: ModelCatalog.ModelItem) {
        progress.visibility = ProgressBar.VISIBLE
        Toast.makeText(this, "正在获取下载地址（GitHub Releases API）...", Toast.LENGTH_SHORT).show()
        Thread {
            // 动态源：先调 GitHub Releases API 解析最新资产下载地址（参照 Kaze-SLauncher CoreSources）
            val target = try {
                ModelCatalog.fetchAssetUrls()[item.id]
            } catch (e: Exception) {
                null
            }
            if (target == null) {
                runOnUiThread {
                    progress.visibility = ProgressBar.GONE
                    Toast.makeText(this, "获取下载地址失败：请检查网络后重试", Toast.LENGTH_LONG).show()
                }
                return@Thread
            }
            val dir = File(filesDir, "models").apply { mkdirs() }
            var ok = true
            try {
                download(target.paramUrl, File(dir, "${item.id}.param"))
                download(target.binUrl, File(dir, "${item.id}.bin"), minBytes = 100 * 1024)
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
                text = getString(R.string.model_local_empty)
                textSize = 14f
                setPadding(16, 16, 16, 16)
            }
            listBox.addView(hint)
        }

        val inflater = LayoutInflater.from(this)
        for ((param, bin) in models) {
            val active = param == Pipeline.modelParam
            val row = inflater.inflate(R.layout.item_local_model, listBox, false)
            row.findViewById<TextView>(R.id.tvLocalName).text = param
            val state = row.findViewById<TextView>(R.id.tvLocalState)
            if (active) {
                state.text = getString(R.string.model_local_active)
                state.setTextColor(getColor(R.color.status_connected))
            } else {
                state.text = ""
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
