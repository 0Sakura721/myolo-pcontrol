package com.myolo.pcontrol

import org.json.JSONObject
import java.net.HttpURLConnection
import java.net.URL

/**
 * 模型商店（在线下载源，参照 Kaze-SLauncher CoreSources 的「API 动态解析」模式）：
 * 不硬编码文件直链——下载前调用 GitHub Releases API 获取最新 release 的资产清单，
 * 从中解析对应 .param/.bin 的 download URL（随仓库 Release 动态更新，失败时提示网络问题）。
 */
object ModelCatalog {

    data class ModelItem(
        val id: String,          // 资产名前缀：<id>.param / <id>.bin
        val displayName: String,
        val sizeMb: Int,         // bin 约略大小（参考）
        val desc: String,
        val available: Boolean = true
    )

    /** 商店清单（描述部分静态；下载地址动态解析） */
    val ITEMS: List<ModelItem> = listOf(
        item("yolo26n_ncnn", "YOLOv26n NCNN (端到端, 推荐)", 5,
            "无 NMS 端到端设计，COCO 80 类；中端旗舰首选"),
        item("yolo26s_ncnn", "YOLOv26s NCNN", 19, "精度更高；中高端机型/大屏使用"),
        item("yolo11n_ncnn", "YOLOv11n NCNN", 5, "前代轻量主力，兼容性与 v8 类似"),
        item("yolov8n_ncnn", "YOLOv8n NCNN", 6, "生态最成熟，教程/社区支持最多"),
        item("yolov10n_ncnn", "YOLOv10n NCNN", 5, "轻量新版，无 NMS 变体"),
        item("yolov9t_ncnn", "YOLOv9t NCNN", 4, "轻量（t=tiny），低端机型友好"),
        item("yolov5nu_ncnn", "YOLOv5nu NCNN", 5, "v5 官方新版，生态成熟；低端机可选"),
        item("yolo26m_ncnn", "YOLOv26m NCNN (暂未上架)", 42,
            "高精度大模型；暂不提供在线下载，可用 tools/export_model.py 自行导出", false),
        item("yolo26l_ncnn", "YOLOv26l NCNN (暂未上架)", 50,
            "高精度大模型；暂不提供在线下载，可自行导出", false),
        item("yolo26x_ncnn", "YOLOv26x NCNN (暂未上架)", 113,
            "最大精度研究用；暂不提供在线下载，可自行导出", false)
    )

    private fun item(id: String, name: String, sizeMb: Int, desc: String, available: Boolean = true) =
        ModelItem(id, name, sizeMb, desc, available)

    // ------------------------------------------------------------------
    // GitHub Releases API 动态源（参照 Kaze-SLauncher CoreSources 风格）
    // ------------------------------------------------------------------
    private const val RELEASES_API =
        "https://api.github.com/repos/0Sakura721/myolo-pcontrol/releases/latest"
    private const val UA = "myolo-pcontrol/1.0 (Android)"

    data class DownloadTarget(val paramUrl: String, val binUrl: String)

    /** 查询最新 release 资产清单，返回 id → (.param/.bin download URL) */
    fun fetchAssetUrls(): Map<String, DownloadTarget> {
        var conn = URL(RELEASES_API).openConnection() as HttpURLConnection
        conn.instanceFollowRedirects = true
        conn.connectTimeout = 15_000
        conn.readTimeout = 30_000
        conn.setRequestProperty("User-Agent", UA)
        var redirects = 0
        while (redirects < 5 && conn.responseCode in listOf(301, 302, 303, 307, 308)) {
            val loc = conn.getHeaderField("Location") ?: break
            conn.disconnect()
            conn = URL(loc).openConnection() as HttpURLConnection
            conn.instanceFollowRedirects = true
            conn.connectTimeout = 15_000
            conn.readTimeout = 30_000
            conn.setRequestProperty("User-Agent", UA)
            redirects++
        }
        if (conn.responseCode != 200) throw RuntimeException("HTTP ${conn.responseCode}")
        val text = conn.inputStream.bufferedReader().use { it.readText() }.also { conn.disconnect() }

        val assets = JSONObject(text).getJSONArray("assets")
        val map = HashMap<String, DownloadTarget>()
        for (i in 0 until assets.length()) {
            val a = assets.getJSONObject(i)
            val name = a.getString("name")
            val url = a.getString("browser_download_url")
            when {
                name.endsWith(".param") -> {
                    val id = name.removeSuffix(".param")
                    map[id] = (map[id] ?: DownloadTarget("", "")).copy(paramUrl = url)
                }
                name.endsWith(".bin") -> {
                    val id = name.removeSuffix(".bin")
                    map[id] = (map[id] ?: DownloadTarget("", "")).copy(binUrl = url)
                }
            }
        }
        return map.filterValues { it.paramUrl.isNotBlank() && it.binUrl.isNotBlank() }
    }
}
