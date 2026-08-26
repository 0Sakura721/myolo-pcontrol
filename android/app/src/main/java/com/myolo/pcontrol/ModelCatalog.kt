package com.myolo.pcontrol

/**
 * 在线模型商店：可下载的 NCNN 模型清单（FP16，.param/.bin 托管在 GitHub Releases）。
 * 在软件内点击即在线下载（点哪个下哪个，不预下载）。
 * 新增模型：导出（tools/export_model.py）→ 上传到仓库 Release → 在 [ITEMS] 加条目。
 */
object ModelCatalog {

    data class ModelItem(
        val id: String,          // 模型文件名前缀（保存为 <id>.param / <id>.bin）
        val displayName: String, // 界面显示名
        val sizeMb: Int,         // bin 约略大小（MB）
        val desc: String,        // 说明
        val available: Boolean = true, // 是否已上架可下载
        val paramUrl: String = "",
        val binUrl: String = ""
    )

    private const val BASE =
        "https://github.com/0Sakura721/myolo-pcontrol/releases/latest/download/"

    val ITEMS: List<ModelItem> = listOf(
        item("yolo26n_ncnn", "YOLOv26n NCNN (端到端, 推荐)", 5,
            "无 NMS 端到端设计，COCO 80 类；中端旗舰首选，实测 8-50 FPS 视机型"),
        item("yolo26s_ncnn", "YOLOv26s NCNN", 19,
            "精度更高；中高端机型/大屏使用"),
        item("yolo11n_ncnn", "YOLOv11n NCNN", 5,
            "前代轻量主力，兼容性与 v8 类似"),
        item("yolov8n_ncnn", "YOLOv8n NCNN", 6,
            "生态最成熟，教程/社区支持最多"),
        item("yolov10n_ncnn", "YOLOv10n NCNN", 5,
            "轻量新版，无 NMS 变体"),
        item("yolov9t_ncnn", "YOLOv9t NCNN", 4,
            "轻量（t=tiny），低端机型友好"),
        item("yolov5nu_ncnn", "YOLOv5nu NCNN", 5,
            "v5 官方新版，生态成熟；低端机可选"),
        item("yolo26m_ncnn", "YOLOv26m NCNN (暂未上架)", 42,
            "高精度大模型；本版本体量大，暂不提供在线下载，可用 tools/export_model.py 自行导出", false),
        item("yolo26l_ncnn", "YOLOv26l NCNN (暂未上架)", 50,
            "高精度大模型；暂不提供在线下载，可自行导出", false),
        item("yolo26x_ncnn", "YOLOv26x NCNN (暂未上架)", 113,
            "最大精度研究用；暂不提供在线下载，可自行导出", false)
    )

    private fun item(
        id: String, name: String, sizeMb: Int, desc: String, available: Boolean = true
    ): ModelItem {
        val item = ModelItem(id, name, sizeMb, desc, available)
        // 仅已上架模型生成可下载 URL
        return if (available) item.copy(paramUrl = BASE + "$id.param", binUrl = BASE + "$id.bin")
        else item
    }
}
