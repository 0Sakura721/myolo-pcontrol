#ifndef NCNN_DETECTOR_H
#define NCNN_DETECTOR_H

#include <cstdint>
#include <string>
#include <vector>

// 检测框：坐标已归一化到 0~1（相对输入原图宽高）
struct Box {
    float x1, y1, x2, y2;
    float score;
    int cls;
};

// NCNN 检测器封装。用 void* 持有 ncnn::Net，避免在头文件暴露 ncnn 类型。
class NcnnDetector {
public:
    NcnnDetector();
    ~NcnnDetector();

    // 加载模型；paramPath/binPath 为 .param/.bin 文件路径
    bool load(const std::string& paramPath, const std::string& binPath, bool useGpu);

    // 输入紧凑 RGBA8888（宽*高*4），输出归一化检测框
    std::vector<Box> detect(const uint8_t* rgba, int width, int height);

    // 释放底层网络资源
    void destroy();

private:
    void* net_; // 实际为 ncnn::Net*
};

#endif // NCNN_DETECTOR_H
