# myolo-pcontrol

YOLO 目标检测 + NCNN 手机端推理 + 局域网/USB 控制电脑鼠标的端云协同项目。

手机端用 YOLO(NCNN/Vulkan 加速)对屏幕或相机画面做目标检测，把检测结果编码成轻量指令，经局域网 WiFi 或 USB 传输到电脑端，由电脑端服务解析并控制鼠标。

```
手机屏幕/相机 → YOLOv26-NCNN 推理 → 指令编码 → TCP 传输（WiFi/ADB/USB网络共享）→ 电脑端解析 → 鼠标控制
```

## 三大模块

| 模块 | 职责 | 目录 |
|------|------|------|
| Android 端 | 屏幕捕获 → YOLO 推理 → 指令编码 → Socket 发送 | [`android/`](android/) |
| 通信层 | 局域网(WiFi) / USB(ADB Forward / USB 网络共享) 传输指令 | 内置在两端 |
| 电脑端 | 接收指令 → 解析 → 控制鼠标移动/点击 | [`pc/`](pc/) |

## 快速开始

### 电脑端（Python）

```bash
cd pc
pip install -r requirements.txt
python server.py            # 默认监听 0.0.0.0:9999
```

### Android 端

1. 构建：`cd android && gradle assembleDebug`
2. 放置 NCNN 预编译库与模型（见 [`docs/architecture.md`](docs/architecture.md) 的模型准备章节）：
   - `libncnn.so` → `app/src/main/jniLibs/<abi>/`
   - `libncnn` 头文件 → `app/src/main/cpp/libncnn/include/`
   - `model.param` / `model.bin` → 安装后 `adb push` 到 `/data/data/com.myolo.pcontrol/files/models/`
3. 安装 APK，填写电脑端 IP，点击「开始捕获」即可。

## 技术选型

- YOLO 版本：YOLOv26n（无 NMS 端到端设计，官方支持 NCNN 导出）
- 推理框架：NCNN + Vulkan（按设备分级回退到 ARM CPU / NPU）
- 量化：FP16（默认） / INT8（低端）
- 通信：TCP Socket + 4 字节长度前缀；载荷为 JSON（调试）/ Protobuf（生产）
- 鼠标控制：pynput
- 轨迹平滑：指数移动平均（EMA）

## 文档

- [`docs/architecture.md`](docs/architecture.md)：完整技术方案

## License

MIT
