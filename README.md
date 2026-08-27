# myolo-pcontrol

YOLO 目标检测 + NCNN 手机端推理 + 局域网/USB 控制电脑鼠标的端云协同项目。

默认工作模式「电脑画面流」：电脑屏幕经 JPEG 推流到手机 → 手机 YOLO(NCNN/Vulkan) 推理 → 生成控制指令回传 → 电脑端执行鼠标动作；也支持「手机屏幕/相机」画面源。

```
电脑屏幕 ──JPEG推流──► 手机端 YOLO-NCNN 推理 ──指令──► 电脑端鼠标控制
（可选）手机屏幕/相机 → YOLOv26-NCNN 推理 → 指令编码 → TCP（WiFi/ADB）→ 鼠标控制
```

## 三步上手

1. **电脑端**：双击 `myolo-pcontrol-desktop.exe`（或 `python pc/gui.py`）→ 点「启动服务」（默认端口 9999，保持「屏幕推流」开启）。
2. **手机端**：安装 APK → 主界面填电脑局域网 IP → 「模型管理 → 模型商店」在线下载任一模型（如 YOLOv26n）并启用。
3. **开始**：画面来源选「电脑画面流」→ 点「连接」→ 「开始捕获」。检测到目标后鼠标自动跟随；点击/滚动按钮可用。

## 三大模块

| 模块 | 职责 | 目录 |
|------|------|------|
| Android 端 | 画面接收/捕获 → YOLO 推理 → 指令编码 → Socket | [`android/`](android/) |
| 通信层 | WiFi(TCP) / USB(ADB Forward / 网络共享)，断线重连+心跳+动态帧率 | 内置在两端 |
| 电脑端 | 屏幕推流 + 指令解析 + pynput 鼠标控制(EMA 平滑) | [`pc/`](pc/) |

## 快速开始（源码方式）

### 电脑端

```bash
cd pc
pip install -r requirements.txt   # PySide6 / pynput / mss / pillow
python gui.py                     # 桌面 GUI（推荐）
python server.py                  # 命令行模式
```

### Android 端

1. 构建：`cd android && gradle assembleDebug`（CI 已自动化：见 `.github/workflows/android-build.yml`，产物 artifact `app-debug`，固定签名可直接覆盖安装）
2. NCNN 库与头文件放置说明见 [`docs/architecture.md`](docs/architecture.md)。
3. 模型无需手动放置：App 内「模型管理 → 模型商店」在线下载（源为 GitHub Releases API 动态解析）；也可导入本地 .param/.bin 或 adb push 到 `/data/data/com.myolo.pcontrol/files/models/`。

## 技术选型

- YOLO 版本：YOLOv26n（端到端无 NMS）/ v26s、yolo11n、yolov8n、yolov10n、yolov9t、yolov5nu 可选（App 内在线下载）
- 推理框架：NCNN + Vulkan（按设备分级回退 ARM CPU / NPU 预留），FP16
- 通信：TCP Socket + 帧协议（客户端→服务端 JSON；服务端→客户端带类型字节 JSON/JPEG 帧）
- 动态调度：按设备档位选捕获分辨率/帧率；连续无目标自动降频，出现目标即恢复
- 鼠标控制：pynput + EMA 平滑 + 死区防抖
- 桌面端：PySide6 GUI（三步操作流、状态徽标、实时日志摘要）

## 文档

- [`docs/architecture.md`](docs/architecture.md)：完整技术方案（含档位表/协议/导出教程）

## 免责声明

本项目仅供学习、研究与技术交流使用，请勿用于任何违法违规用途（如未经授权的计算机控制、游戏作弊、远程侵入他人设备等）。使用本项目产生的一切后果由使用者自行承担。

## License

MIT
