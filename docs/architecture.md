# 技术方案

本文为 `myolo-pcontrol` 的完整技术设计。目标：开发一款 Android 应用，通过手机摄像头或屏幕内容，利用 YOLO 目标检测识别特定目标，通过局域网/USB 将指令传输至电脑端，实现对电脑鼠标的远程控制。

## 1. 系统架构

```
+---------------------------+         +--------------------------+         +---------------------+
|        Android 端          |         |       通信层              |         |      电脑端          |
| 屏幕捕获(MediaProjection)  |         |  WiFi 局域网 TCP Socket   |         |  Socket 服务端       |
|   ↓                        |         |  USB ADB Forward          |         |   ↓                |
| YOLO-NCNN 推理(Vulkan)     |  ────►  |  USB 网络共享             |  ────►  |  指令解析(JSON/Proto) |
|   ↓                        |         |  4字节长度前缀+载荷       |         |   ↓                |
| 指令编码(CommandEncoder)    |         |  断线重连/心跳包          |         |  坐标映射→鼠标控制    |
+---------------------------+         +--------------------------+         +---------------------+
```

## 2. Android 端

### 2.1 屏幕捕获
- `MediaProjection + VirtualDisplay + ImageReader`
- 分辨率：640×480 或 320×240（降低推理负担）
- `PIXEL_FORMAT_RGBA_8888`，复用 Bitmap 防止频繁内存申请
- `maxImages = 2-3`，异步处理不阻塞 UI 线程

### 2.2 NCNN 推理
```cpp
ncnn::Net net;
net.opt.use_vulkan_compute = true;          // 启用 Vulkan
net.load_param("yolo26n.param");
net.load_model("yolo26n.bin");
```
实测 Mali-G78 上 Vulkan 加速可提升 3-5 倍推理速度。

### 2.3 设备分级与推理后端
| 等级 | 条件 | 后端 | 模型 | 关键配置 |
|------|------|------|------|----------|
| 高端(带NPU) | 骁龙8系/麒麟9系, 8GB+ | SNPE/HiAI/NeuroPilot | 厂商格式(.dlc/.hiai) | 专用 SDK |
| 高端(无NPU) | 高性能GPU | NCNN+Vulkan | .param+.bin | `use_vulkan_compute=true` |
| 中端 | Vulkan+4-6GB | NCNN+Vulkan | INT8 量化 | `use_fp16_packed=true` |
| 低端 | Vulkan 弱+<4GB | NCNN+CPU(ARM NEON) | INT8 量化 | `use_vulkan_compute=false` |

启动时检测 NPU 可用性、Vulkan 版本与扩展、CPU 与内存，自动分级。

### 2.4 后处理与指令编码
- 解析检测框 → NMS/无 NMS(端到端) → 置信度过滤(0.5)
- 归一化坐标（0~1）随指令发送，由电脑端映射到屏幕分辨率
- 指令格式：JSON（调试）/ Protobuf（生产）

## 3. 通信层

| 方案 | 实现 | 延迟 | 适用 |
|------|------|------|------|
| WiFi 局域网 | TCP Socket + 4 字节长度前缀 | ~10-50ms | 日常 |
| USB ADB Forward | `adb forward tcp:9999 tcp:9999` | ~5-20ms | 极致低延迟 |
| USB 网络共享 | 手机开启 USB 共享网络 | ~10-30ms | 无需 ADB |

协议：`[4 字节长度][载荷]`，支持断线重连与心跳包。

## 4. 电脑端

- Python socket server 监听端口，多线程处理
- 指令解析：解码 JSON/Protobuf，提取坐标与操作类型
- 坐标映射：`x_abs = x_norm × screen_width`
- 鼠标控制：`pynput`（低延迟）或 `pyautogui`
- 轨迹平滑：指数移动平均（EMA）或卡尔曼滤波

## 5. YOLO 模型选型

| 版本 | NCNN | 模型(FP16) | 说明 |
|------|------|-----------|------|
| YOLOv26n | ✅ 官方最完善 | ~3.5MB | 端到端设计，无 NMS |
| YOLOv8n | ✅ | ~6MB | export(format='ncnn') 一键导出 |
| YOLOv11n | ✅ | ~5MB | 注意命名 |

按手机档位推荐：低端 YOLOv26n INT8@320（8-12 FPS）；中端 FP16@416（18-25）；高端 FP16@640（35-50+）。

### 导出命令
```bash
from ultralytics import YOLO
model = YOLO("yolo26n.pt")
model.export(format="ncnn", imgsz=640, half=True)   # FP16 推荐
# INT8 需先 FP16 导出，再用 ncnn2int8 量化
```

## 6. 模型准备（构建 Android 前）

1. `pip install ultralytics` 并导出 `yolo26n` 的 NCNN 模型（`.param` + `.bin`）。
2. 从 [ncnn](https://github.com/Tencent/ncnn/releases) 下载对应 ABI 的预编译库，或从源码编译。
3. 拷贝到：
   - 头文件 → `app/src/main/cpp/libncnn/include/`（解压 `ncnn-*-android-vulkan-shared` 包取 `<abi>/include`，内含 `ncnn/` 子目录）
   - 推理库 → `app/src/main/jniLibs/<abi>/`（`libncnn.so`，shared 包中位于 `<abi>/lib/`）
   - 模型 → 安装 APK 后 `adb push model.param /data/data/com.myolo.pcontrol/files/models/`、`adb push model.bin /data/data/com.myolo.pcontrol/files/models/`

> 模型与 `.so` 体积大，已 `.gitignore`，不随仓库分发。

## 7. 开发路线

| 阶段 | 时间 | 任务 |
|------|------|------|
| Phase 1 | Day 1-3 | 环境 + NCNN + 导出 YOLOv26n NCNN 模型 |
| Phase 2 | Day 4-10 | Android：屏幕捕获 + NCNN 推理 + 设备分级 + 指令编码 + Socket |
| Phase 3 | Day 11-14 | 电脑端：Socket 服务 + 指令解析 + 鼠标控制 + 平滑 |
| Phase 4 | Day 15-21 | 联调 + 多设备兼容 + 延迟优化 + 功耗控制 |

## 8. 注意事项

- 权限：`MediaProjection`、`INTERNET`、`CAMERA`
- 线程：捕获、推理、网络均需在子线程
- 功耗：持续推理发热，需动态降频
- 版本：推荐 ultralytics 8.4.0
- 坐标系：注意手机横竖屏与电脑屏幕坐标映射
- NPU：厂商 SDK 需单独集成，作为可选项
