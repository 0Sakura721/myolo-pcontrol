# myolo-pcontrol 电脑端（PC）模块

电脑端通过 TCP 接收 Android 端发来的鼠标控制指令并执行。

## 功能

- 多线程 TCP 服务端，支持多客户端。
- 用 `pynput` 控制真实鼠标（移动 / 点击 / 滚动 / 拖拽）。
- 归一化坐标(0~1)映射到真实屏幕分辨率。
- move 指令带指数移动平均(EMA)平滑去抖动。

## 文件结构

```
pc/
  requirements.txt      依赖列表
  protocol.py           帧协议与指令编解码
  mouse_controller.py   鼠标控制逻辑
  server.py             主入口（TCP 服务，CLI 模式）
  gui.py                桌面控制端（PySide6 GUI 模式，可选）
  desktop.spec          PyInstaller 打包配置（打 exe 用，可选）
  README.md             本说明
```

电脑端提供两种运行模式（功能一致，核心复用同一套协议与鼠标控制逻辑）：
- `server.py`：无界面命令行（CLI）模式。
- `gui.py`：带界面的桌面控制端（可视化监听端口、EMA 系数、坐标倍率设置，实时显示连接数与指令日志）。

## 安装依赖

Python 3.8+ 与 `pip`。

```bash
cd pc
pip install -r requirements.txt
```

> 说明：Windows 上屏幕尺寸通过 `ctypes` 调用 `GetSystemMetrics` 获取，
> 非 Windows 平台回退到 1920x1080，无需额外依赖。

## 启动命令

```bash
cd pc
python server.py                  # 默认 0.0.0.0:9999
python server.py --host 192.168.1.100 --port 9999
python server.py --alpha 0.3 --scale 1
```

### 命令行参数

| 参数 | 默认值 | 说明 |
| --- | --- | --- |
| `--host` | `0.0.0.0` | 监听地址 |
| `--port` | `9999` | 监听端口 |
| `--alpha` | `0.3` | EMA 平滑系数（0~1），越大越跟手 |
| `--scale` | `1` | 坐标缩放倍率，作用于归一化坐标 |

## 桌面 GUI 启动（python gui.py）

需要安装了图形界面依赖。先安装依赖：

```bash
cd pc
pip install -r requirements.txt
python gui.py
```

界面说明：

- **监听设置**：监听端口、EMA 平滑系数（alpha）、坐标缩放倍率，可在启动前调节。
- **服务控制**：「启动服务 / 停止服务」按钮；「当前连接数」实时显示；
  「暂停鼠标控制」复选框（或按键盘 `空格` 键）可临时暂停鼠标动作，收到指令仅回执不控制。
- **指令日志**：逐条显示收到的指令与执行结果，格式如
  `[12:00:01] 192.168.1.5:54321  move x=0.42 y=0.87 -> ok`。

> 说明：GUI 模式与 `server.py` 复用同一套帧协议（`protocol.py`）与鼠标控制逻辑（`mouse_controller.py`），
> 参数含义与下表完全一致。关闭窗口时会干净地停止所有线程与 socket。

## 打包 exe（pyinstaller desktop.spec）

需要安装 PyInstaller（可选依赖）：

```bash
cd pc
pip install pyinstaller
pyinstaller desktop.spec
```

- 产物：`dist/myolo-pcontrol-desktop.exe`（单文件，无控制台窗口）。
- 也可以直接用命令行方式：
  ```bash
  pyinstaller -F -w gui.py --name myolo-pcontrol-desktop
  ```
  其中的 `-F`（onefile 单文件）、`-w`（windowed，不弹控制台窗口）。
- `desktop.spec` 已隐含引入 `pynput`；若调试时需要看到控制台输出，
  把 `desktop.spec` 里的 `console=False` 改为 `True` 重新打包即可。

## 帧协议

帧格式：`[4 字节大端无符号长度][载荷]`。

- 载荷为 JSON 字节串。
- 先读 4 字节长度，再读满该长度的载荷。

## 指令格式

指令为 JSON 对象，字段约定如下（与 Android 端一致）：

```json
{"op":"move","x":0.42,"y":0.87,"button":"left","delta":-120,"t":1690000000000}
```

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `op` | string | 指令操作，见下表 |
| `x` | number | 归一化横坐标 0~1 |
| `y` | number | 归一化纵坐标 0~1 |
| `button` | string | 按钮：`left` / `right` / `middle` |
| `delta` | int | scroll 的滚动量（整数，正向上负向下） |
| `t` | number | 毫秒时间戳（可选） |

### op 指令一览

| op | 说明 |
| --- | --- |
| `move` | 移动到绝对坐标（带 EMA 平滑） |
| `click` | 移动后点击 `button` |
| `scroll` | 按 `delta` 滚动 |
| `drag` | 从当前位置按住拖拽到 x,y 再释放 |
| `none` | 心跳，不动作 |
| `ping` | 心跳，不动作，服务端回 `{"op":"pong"}` |

未知字段会被忽略；未知 op 会被忽略且不抛异常。

## TCP / WiFi 说明

- 服务端默认监听 `0.0.0.0:9999`，即局域网内所有网卡。
- 与手机连同一 WiFi 后，用电脑的局域网 IP（如 `192.168.1.100`）连接。
- 查看电脑局域网 IP：Windows 用 `ipconfig`，查找 IPv4 地址。
- 若连接失败，请检查 Windows 防火墙是否放行该端口。

## 坐标映射说明

- Android 端发送的 `x`、`y` 均为 0~1 归一化坐标。
- 服务端映射到真实屏幕：`x_abs = x_norm * screen_width`，`y_abs = y_norm * screen_height`。
- 屏幕尺寸取自真实分辨率：Windows 用 `GetSystemMetrics(0/1)`，其它平台回退 1920x1080。
- move 指令用 EMA 平滑连续坐标，`MOVE_THRESHOLD` 跳过过小位移防抖动。
