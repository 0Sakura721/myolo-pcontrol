#include "ncnn_detector.h"

// NCNN 预编译库头文件（新结构：libncnn/include/ncnn/，需先解压 libncnn 到 src/main/cpp/libncnn/）
#include <ncnn/net.h>
#include <algorithm>
#include <cmath>

// 实际实现包装：持有 ncnn::Net
class NcnnDetectorImpl {
public:
    ncnn::Net net;
};

NcnnDetector::NcnnDetector()
    : net_(nullptr) {
}

NcnnDetector::~NcnnDetector() {
    destroy();
}

// 加载模型：GPU 选项（Vulkan），机型不支持时 ncnn 自动回退 CPU
bool NcnnDetector::load(const std::string& paramPath, const std::string& binPath, bool useGpu) {
    destroy();
    NcnnDetectorImpl* impl = new NcnnDetectorImpl();
    impl->net.opt.use_vulkan_compute = useGpu;
    impl->net.opt.num_threads = 4;
    impl->net.opt.use_fp16_packed = true;
    impl->net.opt.use_fp16_storage = true;
    impl->net.opt.use_fp16_arithmetic = true;

    if (impl->net.load_param(paramPath.c_str()) != 0) {
        delete impl;
        return false;
    }
    if (impl->net.load_model(binPath.c_str()) != 0) {
        delete impl;
        return false;
    }
    net_ = impl;
    return true;
}

// 推理：letterbox 到 640x640 → 归一化 → forward → 解码
std::vector<Box> NcnnDetector::detect(const uint8_t* rgba, int width, int height) {
    std::vector<Box> boxes;
    if (!net_) {
        return boxes;
    }
    NcnnDetectorImpl* impl = static_cast<NcnnDetectorImpl*>(net_);
    if (!rgba || width <= 0 || height <= 0) {
        return boxes;
    }

    const int targetSize = 640; // letterbox 目标边长

    // 等比例缩放 + 填充
    float scale = std::min(static_cast<float>(targetSize) / width,
                           static_cast<float>(targetSize) / height);
    int resizedW = static_cast<int>(width * scale);
    int resizedH = static_cast<int>(height * scale);
    int padW = targetSize - resizedW;
    int padH = targetSize - resizedH;
    int wPad = padW / 2;
    int hPad = padH / 2;

    // RGBA → ncnn::Mat，先缩放
    ncnn::Mat in = ncnn::Mat::from_pixels_resize(
        rgba, ncnn::Mat::PIXEL_RGBA, width, height, resizedW, resizedH);

    // letterbox 填充背景 114
    ncnn::Mat inPad;
    ncnn::copy_make_border(in, inPad, hPad, padH - hPad, wPad, padW - wPad,
                           ncnn::BORDER_CONSTANT, 114.f);

    // 归一化 1/255（均值 0，方差 1/255）
    const float normVals[3] = {1 / 255.f, 1 / 255.f, 1 / 255.f};
    inPad.substract_mean_normalize(nullptr, normVals);

    ncnn::Extractor ex = impl->net.create_extractor();
    ex.input("images", inPad);

    // 输出张量：配套的 yolo26n（ultralytics 导出）输出层为 out0（端到端 nms-free）。
    // 若换用其它模型（yolov8n 等），改为对应层名（如 output0/out）并核对布局。
    ncnn::Mat out;
    ex.extract("out0", out);

    // ---------- 通用解码（nms-free / 端到端策略）----------
    // 说明：此处按常见布局 [1, 4+num_classes, N]（通道优先，out.cstep 为通道步长）
    // 解码。若你的模型是 DFL 头（cx,cy,w,h 形变）或布局为 [1, N, 4+num_classes]，
    // 请依据模型实际输出 reshape 后的维度调整下面的索引与坐标还原逻辑。
    const float scoreThreshold = 0.5f;
    const int numClasses = 80; // TODO: 与模型类别数一致
    const int numCoord = 4;    // x1,y1,x2,y2

    const int num = out.w; // 候选框数量（列数）
    const float* ptr = static_cast<const float*>(out.data);
    const int stride = out.cstep; // 每通道元素数

    for (int i = 0; i < num; ++i) {
        // 在该列上取 4 个坐标通道
        float ox1 = ptr[0 * stride + i];
        float oy1 = ptr[1 * stride + i];
        float ox2 = ptr[2 * stride + i];
        float oy2 = ptr[3 * stride + i];

        // 找最大类别得分
        float bestScore = 0.f;
        int bestCls = -1;
        for (int c = 0; c < numClasses; ++c) {
            float s = ptr[(numCoord + c) * stride + i];
            if (s > bestScore) {
                bestScore = s;
                bestCls = c;
            }
        }
        if (bestCls < 0 || bestScore < scoreThreshold) {
            continue;
        }

        // letterbox 坐标 → 原图坐标
        float x1 = (ox1 - wPad) / scale;
        float y1 = (oy1 - hPad) / scale;
        float x2 = (ox2 - wPad) / scale;
        float y2 = (oy2 - hPad) / scale;
        x1 = std::max(0.f, std::min(static_cast<float>(width), x1));
        y1 = std::max(0.f, std::min(static_cast<float>(height), y1));
        x2 = std::max(0.f, std::min(static_cast<float>(width), x2));
        y2 = std::max(0.f, std::min(static_cast<float>(height), y2));

        Box b;
        b.x1 = x1 / width;   // 归一化 0~1
        b.y1 = y1 / height;
        b.x2 = x2 / width;
        b.y2 = y2 / height;
        b.score = bestScore;
        b.cls = bestCls;
        boxes.push_back(b);
    }

    // 端到端（nms-free）策略：模型权重已含去重，此处不做 NMS。
    // 若你的模型需要 NMS，请取消下面注释：
    /*
    std::sort(boxes.begin(), boxes.end(),
              [](const Box& a, const Box& b) { return a.score > b.score; });
    std::vector<Box> keep;
    std::vector<bool> removed(boxes.size(), false);
    for (size_t i = 0; i < boxes.size(); ++i) {
        if (removed[i]) continue;
        keep.push_back(boxes[i]);
        for (size_t j = i + 1; j < boxes.size(); ++j) {
            if (removed[j]) continue;
            // 计算 IoU，> 0.45 则抑制
            // (略：用两框交集/并集，详见 YOLO NMS 实现)
        }
    }
    boxes = keep;
    */

    return boxes;
}

void NcnnDetector::destroy() {
    if (net_) {
        delete static_cast<NcnnDetectorImpl*>(net_);
        net_ = nullptr;
    }
}
