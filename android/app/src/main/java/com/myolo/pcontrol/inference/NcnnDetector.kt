package com.myolo.pcontrol.inference

/**
 * NCNN 推理封装（Kotlin 单例）。
 * 通过 JNI 调用 C++ 实现，[create]/[destroy] 管理底层 ncnn::Net 生命周期。
 *
 * 使用约定：
 *  - 先 [create]（参数/模型文件必须在就位后调用），返回 true 表示加载成功。
 *  - [detect] 传入紧凑的 RGBA8888 字节数组（宽*高*4），返回 FloatArray。
 *      返回数组长度 = N*6，每组 [x1,y1,x2,y2,score,class]，坐标已归一化到 0~1。
 *  - 结束后调用 [destroy]，或在下次 create 前自动销毁旧实例。
 */
object NcnnDetector {
    init {
        // 加载 native 库（由 CMake 构建生成）
        System.loadLibrary("myolo_detector")
    }

    /**
     * 加载 .param/.bin 模型。
     * @param paramPath 模型结构文件绝对路径
     * @param binPath 模型权重文件绝对路径
     * @param useGpu 是否启用 Vulkan GPU 推理（机型不支持会自动回退 CPU）
     * @return 加载成功与否
     */
    external fun create(paramPath: String, binPath: String, useGpu: Boolean): Boolean

    /**
     * 执行推理。
     * @param rgba 紧凑 RGBA8888 像素缓冲（长度 = width*height*4）
     * @param width 图像宽
     * @param height 图像高
     * @return 归一化检测结果 [x1,y1,x2,y2,score,class]*N
     */
    external fun detect(rgba: ByteArray, width: Int, height: Int): FloatArray

    /** 释放底层网络资源 */
    external fun destroy()
}
