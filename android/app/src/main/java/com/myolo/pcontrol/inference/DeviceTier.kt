package com.myolo.pcontrol.inference

import android.os.Build
import java.io.File

/** 设备性能分级 */
enum class Tier { LOW, MEDIUM, HIGH, NPU }

/** 各分级对应的后端推荐配置 */
data class BackendConfig(
    val tier: Tier,
    val useGpu: Boolean,
    val numThreads: Int,
    val description: String
)

/**
 * 设备分级：纯启发式，基于 CPU 核数 / 可用内存 / Vulkan 支持。
 * 各档推荐配置（写死，供 CMake/推理循环使用）：
 *  - LOW   ：CPU 2 线程，不用 GPU，输入 320x240，模型可缩小
 *  - MEDIUM：CPU 3 线程，可用 GPU，输入 640x480
 *  - HIGH  ：CPU 4 线程，GPU + fp16，输入 640x480
 *  - NPU   ：预留，NCNN 尚未开放 NPU 后端时实际回退 CPU
 */
object DeviceTier {
    val backend: BackendConfig by lazy { detect() }

    private fun detect(): BackendConfig {
        val cores = readCpuCores()
        val memBytes = Runtime.getRuntime().maxMemory()
        val memMb = (memBytes / (1024 * 1024)).toInt()
        val memGb = memMb / 1024f
        val vulkan = hasVulkan()

        val tier = when {
            cores >= 8 && memGb >= 4f -> if (vulkan) Tier.HIGH else Tier.MEDIUM
            cores >= 6 -> Tier.MEDIUM
            else -> Tier.LOW
        }
        // GPU 仅在 Vulkan 可用时开启；NCNN 会按机型自动回退
        val useGpu = vulkan
        val threads = when (tier) {
            Tier.HIGH -> 4
            Tier.MEDIUM -> 3
            Tier.LOW -> 2
            Tier.NPU -> 1
        }
        return BackendConfig(
            tier, useGpu, threads,
            "Tier=$tier cores=$cores mem=${memGb}GB vulkan=$vulkan"
        )
    }

    /** 读取 /proc/cpuinfo 的 processor 行数估算核数 */
    private fun readCpuCores(): Int {
        return try {
            val cpuinfo = File("/proc/cpuinfo").readText()
            cpuinfo.split("\n").count { it.startsWith("processor") }
        } catch (e: Exception) {
            Runtime.getRuntime().availableProcessors()
        }
    }

    /**
     * Vulkan 支持检测（启发式）：
     * 仅估算 arm64 机型大概率支持 Vulkan；更精确可用 SurfaceView + GLES 或
     * PackageManager 查询系统特性 android.hardware.vulkan.version 判定。
     */
    private fun hasVulkan(): Boolean {
        return Build.SUPPORTED_ABIS.any { it == "arm64-v8a" }
    }
}
