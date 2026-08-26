package com.myolo.pcontrol

/**
 * 在线模型目录：可下载的 NCNN 模型清单（.param/.bin 托管在 GitHub Releases）。
 * 新增模型：导出后上传到仓库 Release，在 [ITEMS] 加入对应 URL 即可。
 */
object ModelCatalog {

    data class ModelItem(
        val id: String,          // 模型文件名前缀（保存为 <id>.param / <id>.bin）
        val displayName: String, // 界面显示名
        val sizeMb: Int,         // bin 约略大小（MB）
        val desc: String,        // 说明
        val paramUrl: String,
        val binUrl: String
    )

    private const val BASE =
        "https://github.com/0Sakura721/myolo-pcontrol/releases/latest/download/"

    val ITEMS: List<ModelItem> = listOf(
        ModelItem(
            id = "yolo26n_ncnn",
            displayName = "YOLOv26n NCNN (端到端, 推荐)",
            sizeMb = 5,
            desc = "ultralytics 官方导出，端到端无 NMS，COCO 80 类；旗舰/中端机首选",
            paramUrl = BASE + "yolo26n_ncnn.param",
            binUrl = BASE + "yolo26n_ncnn.bin"
        )
    )
}
