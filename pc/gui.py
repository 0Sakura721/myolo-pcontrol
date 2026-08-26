"""myolo-pcontrol 电脑端 —— Windows 桌面控制端（PySide6 GUI）。

在 server.py 的基础上提供图形界面：启动/停止 TCP 服务、设置监听端口/EMA 系数/坐标倍率、
实时显示连接数、本机局域网 IP 与屏幕推流状态；日志采用「摘要/逐条」混合模式，
把高频 move 指令合并为摘要，避免 10fps 刷屏。

复用现有实现，不重写核心：
  - MouseController（mouse_controller.py）：真实鼠标控制逻辑。
  - protocol.read_frame / decode_command / encode：帧协议读取与指令编解码。
  - screen_stream.ScreenStreamer / send_json_frame：屏幕推流（GUI 只读其状态，不改动）。

线程模型：网络与鼠标操作全部放在后台工作线程（ServerWorker），通过 Qt 信号把日志
/连接数/推流状态/运行状态传递回 UI 线程刷新，避免阻塞与卡死界面。

界面按「①先启动服务 → ②手机填 IP 连接 → ③控制」的操作流组织，降低上手门槛。

运行：  python gui.py
"""

import socket
import threading
import time
from datetime import datetime

from PySide6.QtCore import Qt, QObject, Signal, Slot
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPlainTextEdit,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

# 复用现有模块（与 server.py 保持同一套实现，不改动它们）
from mouse_controller import MouseController
from protocol import decode_command, read_frame
from screen_stream import ScreenStreamer, send_json_frame

# 默认监听参数，与 server.py 保持一致
DEFAULT_HOST = "0.0.0.0"
DEFAULT_PORT = 9999
DEFAULT_ALPHA = 0.3
DEFAULT_SCALE = 1.0

# 连续 move 指令合并为摘要日志的最小间隔（秒）
LOG_SUMMARY_INTERVAL = 3.0

VERSION = "1.2"

# ----------------------------------------------------------------------
# 全局 QSS 样式表：浅色科技风
# ----------------------------------------------------------------------
GLOBAL_QSS = """
* {
    font-family: "Microsoft YaHei", "PingFang SC", "Segoe UI", sans-serif;
}
QMainWindow, QWidget {
    background-color: #f5f6fa;
    font-size: 10pt;
    color: #1f2937;
}

/* ---------- 卡片（QGroupBox） ---------- */
QGroupBox {
    background-color: #ffffff;
    border: 1px solid #e5e7eb;
    border-radius: 10px;
    margin-top: 18px;
    padding: 16px 12px 12px 12px;
    font-size: 10.5pt;
    font-weight: 600;
    color: #111827;
}
QGroupBox::title {
    subcontrol-origin: margin;
    subcontrol-position: top left;
    left: 14px;
    top: 0px;
    padding: 0 6px;
}

QLabel { background: transparent; }
QGroupBox QLabel { background: transparent; }

/* ---------- 通用按钮 ---------- */
QPushButton {
    background-color: #ffffff;
    border: 1px solid #d1d5db;
    border-radius: 8px;
    padding: 8px 16px;
    font-size: 10pt;
    font-weight: 600;
    color: #374151;
}
QPushButton:hover { background-color: #f3f4f6; border-color: #9ca3af; }
QPushButton:pressed { background-color: #e5e7eb; }
QPushButton:disabled { background-color: #f3f4f6; color: #9ca3af; border-color: #e5e7eb; }

/* 主按钮（启动） */
QPushButton#primaryBtn {
    background-color: #3b82f6;
    color: #ffffff;
    border: none;
    padding: 10px 24px;
    font-size: 10.5pt;
    border-radius: 8px;
}
QPushButton#primaryBtn:hover { background-color: #2563eb; }
QPushButton#primaryBtn:pressed { background-color: #1d4ed8; }
QPushButton#primaryBtn:disabled { background-color: #93c5fd; color: #eef2ff; }

/* 危险按钮（停止） */
QPushButton#dangerBtn {
    background-color: #ffffff;
    color: #dc2626;
    border: 1px solid #fca5a5;
}
QPushButton#dangerBtn:hover { background-color: #fef2f2; border-color: #dc2626; }
QPushButton#dangerBtn:pressed { background-color: #fee2e2; }
QPushButton#dangerBtn:disabled { background-color: #f3f4f6; color: #fca5a5; border-color: #e5e7eb; }

/* 轻量按钮（清空日志等） */
QPushButton#ghostBtn {
    background-color: transparent;
    color: #6b7280;
    border: none;
    padding: 6px 12px;
    font-size: 9.5pt;
}
QPushButton#ghostBtn:hover { color: #374151; background-color: #f3f4f6; border-radius: 6px; }
QPushButton#ghostBtn:pressed { background-color: #e5e7eb; }

/* ---------- 输入控件 ---------- */
QSpinBox, QDoubleSpinBox, QPlainTextEdit {
    background-color: #ffffff;
    border: 1px solid #d1d5db;
    border-radius: 8px;
    padding: 6px 8px;
    font-size: 10pt;
    color: #1f2937;
}
QSpinBox, QDoubleSpinBox { min-width: 90px; }
QSpinBox:hover, QDoubleSpinBox:hover, QPlainTextEdit:hover { border-color: #9ca3af; }
QSpinBox:focus, QDoubleSpinBox:focus, QPlainTextEdit:focus { border-color: #3b82f6; }

QSpinBox::up-button, QDoubleSpinBox::up-button,
QSpinBox::down-button, QDoubleSpinBox::down-button {
    background: #f3f4f6;
    border: none;
    width: 18px;
    border-radius: 4px;
}
QSpinBox::up-button:hover, QDoubleSpinBox::up-button:hover,
QSpinBox::down-button:hover, QDoubleSpinBox::down-button:hover { background: #e5e7eb; }

/* ---------- 复选框 ---------- */
QCheckBox { font-size: 10pt; spacing: 8px; }
QCheckBox::indicator {
    width: 18px;
    height: 18px;
    border: 1px solid #d1d5db;
    border-radius: 4px;
    background: #ffffff;
}
QCheckBox::indicator:hover { border-color: #9ca3af; }
QCheckBox::indicator:checked {
    background-color: #3b82f6;
    border-color: #3b82f6;
}

/* ---------- 日志区 ---------- */
QPlainTextEdit {
    background-color: #fafafb;
    font-family: "Consolas", "Courier New", monospace;
    font-size: 9.5pt;
}

/* ---------- 状态栏 ---------- */
QStatusBar {
    background: #ffffff;
    border-top: 1px solid #e5e7eb;
    color: #6b7280;
    font-size: 9.5pt;
}
QStatusBar::item { border: none; }

/* ---------- 标题区 ---------- */
QLabel#appTitle { font-size: 20pt; font-weight: 800; color: #111827; }
QLabel#appSubtitle { font-size: 10.5pt; color: #6b7280; }
QLabel#versionTag { font-size: 9.5pt; color: #9ca3af; }

/* ---------- 本机 IP ---------- */
QLabel#ipLabel {
    font-family: "Consolas", "Courier New", monospace;
    font-size: 15pt;
    font-weight: 700;
    color: #3b82f6;
    background: #eff6ff;
    border: 1px solid #bfdbfe;
    border-radius: 8px;
    padding: 10px 12px;
}

/* ---------- 提示小字 ---------- */
QLabel#hintLabel { color: #6b7280; font-size: 9.5pt; }

/* ---------- 服务状态徽标 ---------- */
QLabel#stateBadge {
    border-radius: 11px;
    padding: 4px 14px;
    font-size: 9.5pt;
    font-weight: 700;
    color: #ffffff;
}
QLabel#stateBadge[running="false"] { background-color: #9ca3af; }
QLabel#stateBadge[running="true"]  { background-color: #16a34a; }
"""


def _is_private_ip(ip: str) -> bool:
    """判断是否属于常见局域网私有地址段（192.168./10./172.16-31.）。"""
    if ip.startswith("192.168.") or ip.startswith("10."):
        return True
    if ip.startswith("172."):
        try:
            second = int(ip.split(".")[1])
            return 16 <= second <= 31
        except (ValueError, IndexError):
            return False
    return False


def _get_local_ips() -> list:
    """枚举本机可用于手机连接的局域网 IPv4 地址。

    优先取「默认路由出口」IP（UDP connect 到 8.8.8.8 仅用于取路由，不真正发包），
    再用 getaddrinfo(主机名) 补充其它网卡的 IPv4；最后过滤私有地址段并按序去重。
    """
    ordered = []
    # 法一：UDP connect 取默认出口 IP（离线/无默认路由时抛 OSError，需容错）
    try:
        probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        probe.connect(("8.8.8.8", 80))
        ordered.append(probe.getsockname()[0])
        probe.close()
    except OSError:
        pass
    # 法二：按主机名枚举所有 IPv4（覆盖多网卡/虚拟网卡特例）
    try:
        for info in socket.getaddrinfo(
            socket.gethostname(), None, socket.AF_INET, socket.SOCK_STREAM
        ):
            ip = info[4][0]
            if ip not in ordered:
                ordered.append(ip)
    except socket.gaierror:
        pass

    # 只保留私有地址段（可被手机直接访问）
    private = [ip for ip in ordered if _is_private_ip(ip)]
    if private:
        return private
    # 无内网地址时回退到非回环地址，最后才用 127.0.0.1
    non_loop = [ip for ip in ordered if not ip.startswith("127.")]
    return non_loop or ["127.0.0.1"]


def _fmt_cmd(cmd: dict) -> str:
    """把一条指令 dict 格式化为可读字符串。

    例如 {"op":"move","x":0.42,"y":0.87} -> "move x=0.42 y=0.87"
    未知字段不展开，只展示常用字段，保证日志简洁可读。
    """
    op = cmd.get("op", "none")
    parts = [op]
    # 归一化坐标
    if "x" in cmd:
        parts.append(f"x={cmd['x']}")
    if "y" in cmd:
        parts.append(f"y={cmd['y']}")
    # 按钮 / 滚动量 / 目标坐标（拖拽用）
    if "button" in cmd:
        parts.append(f"button={cmd['button']}")
    if "delta" in cmd:
        parts.append(f"delta={cmd['delta']}")
    if "x2" in cmd:
        parts.append(f"x2={cmd['x2']}")
    if "y2" in cmd:
        parts.append(f"y2={cmd['y2']}")
    return " ".join(parts)


def _now_hms() -> str:
    """返回当前时间的 HH:MM:SS 字符串。"""
    return datetime.now().strftime("%H:%M:%S")


class ServerWorker(QObject):
    """后台 TCP 服务工作线程。

    此对象常驻主线程，但其 _run / _handle_client 在独立线程里执行；
    通过 Qt 信号把结果安全地带回 UI 线程。
    """

    # 日志行信号（带时间戳整行文本）
    log_emit = Signal(str)
    # 当前连接数变化信号
    conn_emit = Signal(int)
    # 运行状态信号（True=运行中，False=已停止）
    state_emit = Signal(bool)
    # 屏幕推流状态信号：(是否有活跃推流, 当前推流帧率)
    stream_emit = Signal(bool, int)

    def __init__(self, port: int, alpha: float, scale: float,
                 stream_enabled: bool = True, stream_fps: int = 10, stream_quality: int = 70):
        super().__init__()
        self.port = port
        self.alpha = alpha
        self.scale = scale
        self.stream_enabled = stream_enabled      # 是否接受屏幕推流订阅
        self.stream_fps = stream_fps              # 推流默认帧率（新订阅可覆盖）
        self.stream_quality = stream_quality      # 推流默认 JPEG 质量（新订阅可覆盖）
        self._running = False          # 是否继续运行
        self._paused = False           # 暂停鼠标控制（界面可切换）
        self._worker_thread = None     # 服务线程
        self._server = None            # 监听 socket
        self._clients = {}             # conn -> thread，用于计数与强制断开
        # 活跃推流计数（跨连接累计，供状态栏显示）
        self._stream_count = 0
        self._stream_fps_current = 0
        self._stream_lock = threading.Lock()

    # ------------------------------------------------------------------
    # 供 UI 调用的控制接口（均安全，不会阻塞 UI）
    # ------------------------------------------------------------------
    def start(self):
        """启动服务线程（若已在运行则忽略）。

        state_emit(True) 由 _run 在绑定成功后发出，确保状态栏读取到真实的 _running。
        """
        if self._running:
            return
        self._worker_thread = threading.Thread(target=self._run, daemon=True)
        self._worker_thread.start()

    def stop(self):
        """请求停止服务，并立即关闭 socket 以解除阻塞。"""
        self._running = False
        # 关闭监听 socket：会触发 accept() 抛 OSError，从而退出循环
        if self._server is not None:
            try:
                self._server.close()
            except OSError:
                pass
        # 关闭所有客户端连接：会触发各自线程里 read_frame 抛 OSError/EOFError 退出
        for conn in list(self._clients.keys()):
            try:
                conn.close()
            except OSError:
                pass
        # 若工作线程尚未退出，等待片刻
        if self._worker_thread is not None and self._worker_thread is not threading.current_thread():
            self._worker_thread.join(timeout=2.0)

    def set_paused(self, paused: bool):
        """设置/取消暂停鼠标控制。暂停时收到指令只回执，不实际移动鼠标。"""
        self._paused = paused

    # ------------------------------------------------------------------
    # 推流状态上报（线程安全，供状态栏显示）
    # ------------------------------------------------------------------
    def _stream_started(self, fps: int):
        """记录新增一个活跃推流并上报状态。"""
        with self._stream_lock:
            self._stream_count += 1
            self._stream_fps_current = fps
        self.stream_emit.emit(self._stream_count > 0, self._stream_fps_current)

    def _stream_stopped(self):
        """记录移除一个活跃推流并上报状态。"""
        with self._stream_lock:
            if self._stream_count > 0:
                self._stream_count -= 1
        self.stream_emit.emit(self._stream_count > 0, self._stream_fps_current)

    # ------------------------------------------------------------------
    # 服务线程主体
    # ------------------------------------------------------------------
    def _run(self):
        """服务主循环：绑定端口、接受连接（复刻 server.py 的流程）。"""
        controller = MouseController(alpha=self.alpha, scale=self.scale)

        try:
            self._server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self._server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self._server.bind((DEFAULT_HOST, self.port))
            self._server.listen(5)
        except OSError as e:
            # 端口被占用等错误
            self.log_emit.emit(f"[{_now_hms()}] 启动失败（端口 {self.port} 可能被占用）: {e}")
            self._running = False
            self.state_emit.emit(False)
            return

        # 设置超时，让 accept() 周期性返回以检查 self._running
        self._server.settimeout(0.5)
        self._running = True
        self.log_emit.emit(
            f"[{_now_hms()}] 服务已启动，监听 {DEFAULT_HOST}:{self.port} "
            f"(alpha={self.alpha}, scale={self.scale})"
        )
        # 绑定成功后上报运行态（此时 _running 已为 True，状态栏才能正确显示）
        self.state_emit.emit(True)

        try:
            while self._running:
                try:
                    conn, addr = self._server.accept()
                except socket.timeout:
                    # 到点检查是否停止
                    continue
                except OSError:
                    # socket 被关闭（stop() 调用），退出
                    break

                client_id = f"{addr[0]}:{addr[1]}"
                self.log_emit.emit(f"[{_now_hms()}] {client_id} 已连接")
                t = threading.Thread(
                    target=self._handle_client,
                    args=(conn, client_id, controller),
                    daemon=True,
                )
                self._clients[conn] = t
                self.conn_emit.emit(len(self._clients))
                t.start()
        finally:
            # 清理：关闭监听 socket 与残余客户端连接
            if self._server is not None:
                try:
                    self._server.close()
                except OSError:
                    pass
            for conn in list(self._clients.keys()):
                try:
                    conn.close()
                except OSError:
                    pass
            self._clients.clear()
            self.conn_emit.emit(0)
            self._running = False
            self.log_emit.emit(f"[{_now_hms()}] 服务已停止")
            self.state_emit.emit(False)

    def _handle_client(self, conn, client_id: str, controller: MouseController):
        """处理单个客户端连接：读帧、解码、执行、回执（复刻 server.py）。

        日志采用「摘要」模式：连续 move 指令只在达到 LOG_SUMMARY_INTERVAL 间隔或
        出现其它指令时才合并刷一条；click/scroll/drag/ping/订阅等逐条记录。
        """
        # 当前连接的屏幕推流器（无订阅时为 None）
        streamer = None
        # 该连接的发送锁：屏幕帧线程与回执线程共用，防止并发 sendall 帧错位
        send_lock = threading.Lock()
        # 连续 move 摘要统计（每连接独立，避免跨线程共享）
        move_pending = 0
        batch_start = 0.0
        try:
            while self._running:
                # 阻塞读取一帧；连接被关闭时 read_frame 抛 EOFError/OSError
                payload = read_frame(conn)
                if not payload:
                    break

                # JSON 解码容错：解析失败跳过该条，不中断连接
                try:
                    cmd = decode_command(payload)
                except (ValueError, UnicodeDecodeError) as e:
                    self.log_emit.emit(
                        f"[{_now_hms()}] {client_id} 无法解析的指令: {e}"
                    )
                    continue

                op = cmd.get("op", "none")

                # 屏幕推流订阅（控制类指令，不走鼠标控制器）
                if op == "subscribe_screen":
                    if self.stream_enabled:
                        if streamer is None:
                            streamer = ScreenStreamer(
                                conn,
                                fps=cmd.get("fps", self.stream_fps),
                                quality=cmd.get("quality", self.stream_quality),
                                send_lock=send_lock,
                            )
                            streamer.start()
                            self._stream_started(streamer.fps)
                            self.log_emit.emit(
                                f"[{_now_hms()}] {client_id} 已订阅屏幕推流 "
                                f"(fps={streamer.fps}, quality={streamer.quality})"
                            )
                        elif not streamer.is_alive():
                            # 旧推流线程已自行退出：先卸载计数，再重建
                            self._stream_stopped()
                            streamer = ScreenStreamer(
                                conn,
                                fps=cmd.get("fps", self.stream_fps),
                                quality=cmd.get("quality", self.stream_quality),
                                send_lock=send_lock,
                            )
                            streamer.start()
                            self._stream_started(streamer.fps)
                            self.log_emit.emit(
                                f"[{_now_hms()}] {client_id} 已订阅屏幕推流 "
                                f"(fps={streamer.fps}, quality={streamer.quality})"
                            )
                        resp = {"op": "ok"}
                    else:
                        self.log_emit.emit(
                            f"[{_now_hms()}] {client_id} 请求屏幕推流，但推流未启用"
                        )
                        resp = {"op": "error", "error": "screen_stream_disabled"}
                elif op == "unsubscribe_screen":
                    if streamer is not None:
                        streamer.stop()
                        streamer = None
                        self._stream_stopped()
                        self.log_emit.emit(
                            f"[{_now_hms()}] {client_id} 已取消屏幕推流订阅"
                        )
                    resp = {"op": "ok"}
                elif self._paused:
                    # 暂停则只回执，不实际控制鼠标
                    resp = {"op": "paused"}
                else:
                    # 执行指令（容错：单条失败不中断连接）
                    try:
                        resp = controller.handle_command(cmd)
                    except Exception as e:
                        self.log_emit.emit(
                            f"[{_now_hms()}] {client_id} 执行 {op} 失败: {e}"
                        )
                        resp = {"op": "error", "error": str(e)}

                # 摘要日志：连续 move 合并，其它指令逐条记录
                if op == "move":
                    now = time.time()
                    if move_pending == 0:
                        batch_start = now
                    move_pending += 1
                    # 距本次摘要开始超过间隔就刷一条汇总，避免 10fps 刷屏
                    if now - batch_start >= LOG_SUMMARY_INTERVAL:
                        self.log_emit.emit(
                            f"[{_now_hms()}] move 已连续执行 {move_pending} 次 -> ok"
                        )
                        move_pending = 0
                        batch_start = now
                else:
                    # 非 move 指令：先刷掉堆积的 move 摘要，再逐条记录
                    if move_pending > 0:
                        self.log_emit.emit(
                            f"[{_now_hms()}] move 已连续执行 {move_pending} 次 -> ok"
                        )
                        move_pending = 0
                    self.log_emit.emit(
                        f"[{_now_hms()}] {client_id}  {_fmt_cmd(cmd)} -> {resp.get('op')}"
                    )

                # 回执统一走带类型字节(0x00)的 JSON 帧
                try:
                    send_json_frame(conn, resp, send_lock)
                except OSError as e:
                    self.log_emit.emit(
                        f"[{_now_hms()}] {client_id} 发送响应失败: {e}"
                    )
                    break

        except EOFError:
            pass  # 正常关闭
        except socket.timeout:
            pass
        except OSError:
            pass  # 连接被 stop() 或对方关闭
        finally:
            # 连接断开：停止推流
            if streamer is not None:
                streamer.stop()
                self._stream_stopped()
            # 连接断开时刷掉残余的 move 摘要
            if move_pending > 0:
                self.log_emit.emit(
                    f"[{_now_hms()}] move 已连续执行 {move_pending} 次 -> ok"
                )
            self.log_emit.emit(f"[{_now_hms()}] {client_id} 断开连接")
            try:
                conn.close()
            except OSError:
                pass
            # 从客户端表移除并刷新连接计数
            if conn in self._clients:
                del self._clients[conn]
                self.conn_emit.emit(len(self._clients))


class MainWindow(QMainWindow):
    """桌面控制端主窗口。"""

    def __init__(self):
        super().__init__()
        self.setWindowTitle("myolo-pcontrol 桌面控制端 v%s（手机远程控制电脑鼠标）" % VERSION)
        self.resize(920, 680)
        self.setMinimumSize(800, 600)

        # 当前运行中的工作线程（未启动时为 None）
        self._worker = None
        self._conn_count = 0
        self._stream_active = False
        self._stream_fps = 0
        # 本机局域网 IP（启动时枚举一次）
        self._local_ips = _get_local_ips()
        self._primary_ip = self._local_ips[0] if self._local_ips else "未知"

        self._build_ui()
        self._refresh_status()

    # ------------------------------------------------------------------
    # 界面搭建
    # ------------------------------------------------------------------
    def _build_ui(self):
        self.setStyleSheet(GLOBAL_QSS)

        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(16, 14, 16, 8)
        root.setSpacing(12)

        # --- 顶部标题区 ---
        header = QVBoxLayout()
        header.setSpacing(2)
        title_row = QHBoxLayout()
        self._app_title = QLabel("myolo-pcontrol")
        self._app_title.setObjectName("appTitle")
        self._version_tag = QLabel("v" + VERSION)
        self._version_tag.setObjectName("versionTag")
        title_row.addWidget(self._app_title)
        title_row.addStretch()
        title_row.addWidget(self._version_tag, 0, Qt.AlignTop)
        header.addLayout(title_row)
        self._app_subtitle = QLabel("手机画面 → YOLO 推理 → 电脑鼠标")
        self._app_subtitle.setObjectName("appSubtitle")
        header.addWidget(self._app_subtitle)
        root.addLayout(header)

        # --- 第 1 步 · 启动服务 ---
        step1 = QGroupBox("第 1 步 · 启动服务")
        s1 = QVBoxLayout(step1)
        s1.setSpacing(10)
        self._service_form = QFormLayout()
        self._service_form.setVerticalSpacing(8)
        self._service_form.setLabelAlignment(Qt.AlignLeft)

        self._port_spin = QSpinBox()
        self._port_spin.setRange(1, 65535)
        self._port_spin.setValue(DEFAULT_PORT)
        self._service_form.addRow("监听端口", self._port_spin)

        self._alpha_spin = QDoubleSpinBox()
        self._alpha_spin.setRange(0.05, 1.0)
        self._alpha_spin.setSingleStep(0.05)
        self._alpha_spin.setValue(DEFAULT_ALPHA)
        self._service_form.addRow("EMA 平滑系数 (alpha)", self._alpha_spin)

        self._scale_spin = QDoubleSpinBox()
        self._scale_spin.setRange(0.1, 5.0)
        self._scale_spin.setSingleStep(0.1)
        self._scale_spin.setValue(DEFAULT_SCALE)
        self._service_form.addRow("坐标缩放倍率", self._scale_spin)
        s1.addLayout(self._service_form)

        # 状态徽标 + 暂停开关
        badge_row = QHBoxLayout()
        self._state_badge = QLabel("● 未启动")
        self._state_badge.setObjectName("stateBadge")
        self._state_badge.setProperty("running", False)
        badge_row.addWidget(self._state_badge)
        badge_row.addStretch()
        self._pause_cb = QCheckBox("暂停鼠标控制（快捷键：空格）")
        self._pause_cb.stateChanged.connect(self._on_pause_toggled)
        badge_row.addWidget(self._pause_cb)
        s1.addLayout(badge_row)

        # 启动 / 停止按钮
        btn_row = QHBoxLayout()
        self._start_btn = QPushButton("启动服务")
        self._start_btn.setObjectName("primaryBtn")
        self._start_btn.clicked.connect(self._on_start)
        self._stop_btn = QPushButton("停止服务")
        self._stop_btn.setObjectName("dangerBtn")
        self._stop_btn.setEnabled(False)
        self._stop_btn.clicked.connect(self._on_stop)
        btn_row.addWidget(self._start_btn)
        btn_row.addWidget(self._stop_btn)
        btn_row.addStretch()
        s1.addLayout(btn_row)
        root.addWidget(step1)

        # --- 第 2 步 · 手机端连接 ---
        step2 = QGroupBox("第 2 步 · 手机端连接")
        s2 = QVBoxLayout(step2)
        s2.setSpacing(10)
        ip_row = QHBoxLayout()
        self._ip_label = QLabel()
        self._ip_label.setObjectName("ipLabel")
        self._ip_label.setWordWrap(True)
        self._ip_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self._set_ip_text()
        ip_row.addWidget(self._ip_label, 1)
        self._copy_ip_btn = QPushButton("复制")
        self._copy_ip_btn.setToolTip("复制本机局域网 IP 到剪贴板，方便填入手机端")
        self._copy_ip_btn.clicked.connect(self._copy_ip)
        ip_row.addWidget(self._copy_ip_btn, 0, Qt.AlignTop)
        s2.addLayout(ip_row)

        meta_row = QHBoxLayout()
        self._conn_label = QLabel(f"当前连接数：{self._conn_count}")
        meta_row.addWidget(self._conn_label)
        meta_row.addStretch()
        s2.addLayout(meta_row)

        self._conn_hint = QLabel("在手机 App 填写上方 IP 与端口（默认 9999）后点击连接")
        self._conn_hint.setObjectName("hintLabel")
        self._conn_hint.setWordWrap(True)
        s2.addWidget(self._conn_hint)
        root.addWidget(step2)

        # --- 第 3 步 · 屏幕推流 ---
        step3 = QGroupBox("第 3 步 · 屏幕推流")
        s3 = QVBoxLayout(step3)
        s3.setSpacing(10)
        stream_form = QFormLayout()
        stream_form.setVerticalSpacing(8)
        stream_form.setLabelAlignment(Qt.AlignLeft)

        self._stream_cb = QCheckBox("允许屏幕推流（手机端订阅即推流）")
        self._stream_cb.setChecked(True)
        stream_form.addRow("开关", self._stream_cb)

        self._stream_fps_spin = QSpinBox()
        self._stream_fps_spin.setRange(1, 30)
        self._stream_fps_spin.setValue(10)
        stream_form.addRow("帧率 (fps)", self._stream_fps_spin)

        self._stream_quality_spin = QSpinBox()
        self._stream_quality_spin.setRange(1, 100)
        self._stream_quality_spin.setValue(70)
        self._stream_quality_spin.setToolTip("JPEG 压缩质量，仅影响新订阅的推流")
        stream_form.addRow("图像质量", self._stream_quality_spin)
        s3.addLayout(stream_form)

        self._stream_hint = QLabel("手机画面来源选『电脑画面流』时生效；帧率/质量仅对之后新订阅的连接生效")
        self._stream_hint.setObjectName("hintLabel")
        self._stream_hint.setWordWrap(True)
        s3.addWidget(self._stream_hint)
        root.addWidget(step3)

        # --- 指令日志 ---
        log_box = QGroupBox("指令日志")
        log_layout = QVBoxLayout(log_box)
        log_layout.setSpacing(8)
        log_bar = QHBoxLayout()
        self._log_note = QLabel("move 指令每 3 秒合并为一条摘要，click/scroll/drag 逐条记录")
        self._log_note.setObjectName("hintLabel")
        log_bar.addWidget(self._log_note)
        log_bar.addStretch()
        self._clear_log_btn = QPushButton("清空日志")
        self._clear_log_btn.setObjectName("ghostBtn")
        log_bar.addWidget(self._clear_log_btn)
        log_layout.addLayout(log_bar)

        self._log_view = QPlainTextEdit()
        self._log_view.setReadOnly(True)
        self._log_view.setMaximumBlockCount(2000)  # 限制日志条数，避免内存膨胀
        log_layout.addWidget(self._log_view)
        self._clear_log_btn.clicked.connect(self._log_view.clear)
        root.addWidget(log_box, 1)

        # 首次打开显示欢迎指引
        self._append_log("[欢迎] 欢迎！按上方步骤：1 启动服务 → 2 手机填 IP 连接 → 3 开始推流/使用")

        # --- 状态栏 ---
        self._status_label = QLabel("未启动")
        self.statusBar().addPermanentWidget(self._status_label)
        self.statusBar().showMessage("就绪", 3000)

        # 空格键快捷暂停/恢复鼠标控制（翻转复选框，由 stateChanged 统一处理）
        self._space_shortcut = QShortcut(QKeySequence(Qt.Key_Space), self)
        self._space_shortcut.activated.connect(self._toggle_pause)

    # ------------------------------------------------------------------
    # 槽函数（UI 线程执行）
    # ------------------------------------------------------------------
    @Slot()
    def _on_start(self):
        """读取设置并启动服务。"""
        if self._worker is not None and self._worker._running:
            return
        # 禁用设置，避免运行中修改无效
        self._set_settings_enabled(False)

        self._worker = ServerWorker(
            port=self._port_spin.value(),
            alpha=self._alpha_spin.value(),
            scale=self._scale_spin.value(),
            stream_enabled=self._stream_cb.isChecked(),
            stream_fps=self._stream_fps_spin.value(),
            stream_quality=self._stream_quality_spin.value(),
        )
        # 跨线程信号 → UI 线程槽
        self._worker.log_emit.connect(self._append_log)
        self._worker.conn_emit.connect(self._update_conn)
        self._worker.state_emit.connect(self._on_state_change)
        self._worker.stream_emit.connect(self._on_stream_change)

        self._start_btn.setEnabled(False)
        self._stop_btn.setEnabled(True)
        self.statusBar().showMessage(f"正在监听 {DEFAULT_HOST}:{self._port_spin.value()}", 3000)
        self._worker.start()

    @Slot()
    def _on_stop(self):
        """停止服务。"""
        if self._worker is not None:
            self._worker.stop()
        self._start_btn.setEnabled(True)
        self._stop_btn.setEnabled(False)
        self._set_settings_enabled(True)
        self._update_conn(0)

    @Slot()
    def _toggle_pause(self):
        """翻转暂停复选框；复选框的 stateChanged 会再回调 _on_pause_toggled 应用状态。"""
        self._pause_cb.setChecked(not self._pause_cb.isChecked())

    @Slot()
    def _on_pause_toggled(self):
        """切换暂停状态（复选框与空格快捷键共用）。"""
        paused = self._pause_cb.isChecked()
        if self._worker is not None:
            self._worker.set_paused(paused)
        state = "已暂停鼠标控制" if paused else "已恢复鼠标控制"
        self._append_log(f"[{_now_hms()}] {state}")
        self.statusBar().showMessage(state, 3000)

    @Slot(str)
    def _append_log(self, line: str):
        """追加一行日志到日志框。"""
        self._log_view.appendPlainText(line)
        # 滚动到底部显示最新
        scrollbar = self._log_view.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())

    @Slot(int)
    def _update_conn(self, count: int):
        """刷新连接数显示。"""
        self._conn_count = count
        self._conn_label.setText(f"当前连接数：{count}")
        self._refresh_status()

    @Slot(bool)
    def _on_state_change(self, running: bool):
        """根据运行状态更新状态徽标与状态栏提示。"""
        self._set_state_badge(running)
        self.statusBar().showMessage("服务运行中" if running else "服务已停止", 3000)
        self._refresh_status()

    @Slot(bool, int)
    def _on_stream_change(self, active: bool, fps: int):
        """接收推流状态变化并刷新状态栏。"""
        self._stream_active = active
        self._stream_fps = fps
        self._refresh_status()

    @Slot()
    def _copy_ip(self):
        """复制主用局域网 IP 到剪贴板。"""
        if self._primary_ip != "未知":
            QApplication.clipboard().setText(self._primary_ip)
            self.statusBar().showMessage(f"已复制本机 IP：{self._primary_ip}", 3000)

    def _set_state_badge(self, running: bool):
        """更新服务状态徽标的文案与配色（通过动态属性触发 QSS 重绘）。"""
        self._state_badge.setProperty("running", running)
        self._state_badge.setText("● 运行中" if running else "● 未启动")
        # 强制重算样式，让 [running=...] 选择器生效
        self._state_badge.style().unpolish(self._state_badge)
        self._state_badge.style().polish(self._state_badge)

    def _refresh_status(self):
        """刷新底部状态栏文本：监听地址 · 连接数 · 推流状态。"""
        if self._worker is not None and self._worker._running:
            listen = f"监听 {DEFAULT_HOST}:{self._port_spin.value()}"
            stream_txt = f"推流 开({self._stream_fps}fps)" if self._stream_active else "推流 关"
        else:
            listen = "未启动"
            stream_txt = "推流 关"
        parts = [listen, f"连接数 {self._conn_count}", stream_txt]
        self._status_label.setText(" · ".join(parts))

    def _set_ip_text(self):
        """更新本机 IP 显示文本（可能有多个，换行列出）。"""
        if not self._local_ips:
            self._ip_label.setText("未检测到局域网 IP")
        else:
            self._ip_label.setText("\n".join(self._local_ips))

    def _set_settings_enabled(self, enabled: bool):
        """启用/禁用监听与推流设置输入框（设置区只在停止态可编辑）。"""
        self._port_spin.setEnabled(enabled)
        self._alpha_spin.setEnabled(enabled)
        self._scale_spin.setEnabled(enabled)
        self._stream_cb.setEnabled(enabled)
        self._stream_fps_spin.setEnabled(enabled)
        self._stream_quality_spin.setEnabled(enabled)
        # 本机 IP 与复制按钮属只读信息，始终可用

    def closeEvent(self, event):
        """关闭窗口时干净地停止所有线程与 socket。"""
        if self._worker is not None:
            self._worker.stop()
        super().closeEvent(event)


def main():
    """程序入口。"""
    import sys

    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
