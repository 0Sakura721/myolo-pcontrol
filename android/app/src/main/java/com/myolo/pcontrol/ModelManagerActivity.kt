package com.myolo.pcontrol

import android.net.Uri
import android.os.Bundle
import android.widget.Button
import android.widget.LinearLayout
import android.widget.ProgressBar
import android.widget.ScrollView
import android.widget.TextView
import android.widget.Toast
import androidx.activity.result.contract.ActivityResultContracts
import androidx.appcompat.app.AppCompatActivity
import com.myolo.pcontrol.pipeline.Pipeline
import java.io.File

/**
 * 模型管理页：导入 .param/.bin（系统文件选择器，可多选）、
 * 启用某个模型（点击）、删除（长按）、显示当前模型与加载结果。
 * 模型保存路径：/data/data/com.myolo.pcontrol/files/models/
 */
class ModelManagerActivity : AppCompatActivity() {

    private lateinit var tvCurrent: TextView
    private lateinit var listBox: LinearLayout
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
        progress = findViewById(R.id.modelProgress)
        val btnImport = findViewById<Button>(R.id.btnImportModel)
        val btnRefresh = findViewById<Button>(R.id.btnRefreshModel)

        btnImport.setOnClickListener {
            importLauncher.launch(arrayOf("*/*")) // 系统文件选择器，用户挑 .param/.bin
        }
        btnRefresh.setOnClickListener { refreshList() }
        refreshList()
    }

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

        val models = Pipeline.listModels(this)
        if (models.isEmpty()) {
            val hint = TextView(this).apply {
                text = "还没有模型文件。\n" +
                        "点「导入模型文件」从存储选择 .param / .bin，\n" +
                        "或用 adb push 到 /data/data/com.myolo.pcontrol/files/models/"
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
