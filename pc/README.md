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
  server.py             主入口（TCP 服务）
  README.md             本说明
```

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
