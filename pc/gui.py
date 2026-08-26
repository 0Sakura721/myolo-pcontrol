"""myolo-pcontrol 电脑端 —— Windows 桌面控制端（PySide6 GUI）。

在 server.py 的基础上提供图形界面：启动/停止 TCP 服务、设置监听端口/EMA 系数/坐标倍率、
实时显示连接数、以日志列表展示每条收到的指令与执行结果。

复用现有实现，不重写核心：
  - MouseController（mouse_controller.py）：真实鼠标控制逻辑。
  - protocol.read_frame / decode_command / encode：帧协议读取与指令编解码。

线程模型：网络与鼠标操作全部放在后台工作线程（ServerWorker），通过 Qt 信号把日志
/连接数/运行状态传递回 UI 线程刷新，避免阻塞与卡死界面。

运行：  python gui.py
"""

import json
import socket
import threading
import time
from datetime import datetime

from PySide6.QtCore import Qt, QObject, Signal, Slot, QTimer
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
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
from protocol import decode_command, encode, read_frame

# 默认监听参数，与 server.py 保持一致
DEFAULT_HOST = "0.0.0.0"
DEFAULT_PORT = 9999
DEFAULT_ALPHA = 0.3
DEFAULT_SCALE = 1.0


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

    def __init__(self, port: int, alpha: float, scale: float):
        super().__init__()
        self.port = port
        self.alpha = alpha
        self.scale = scale
        self._running = False          # 是否继续运行
        self._paused = False           # 暂停鼠标控制（界面可切换）
        self._worker_thread = None     # 服务线程
        self._server = None            # 监听 socket
        self._clients = {}             # conn -> thread，用于计数与强制断开

    # ------------------------------------------------------------------
    # 供 UI 调用的控制接口（均安全，不会阻塞 UI）
    # ------------------------------------------------------------------
    def start(self):
        """启动服务线程（若已在运行则忽略）。"""
        if self._running:
            return
        self.state_emit.emit(True)
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
        """处理单个客户端连接：读帧、解码、执行、回执（复刻 server.py）。"""
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

                # 暂停则只回执，不实际控制鼠标
                if self._paused:
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

                self.log_emit.emit(
                    f"[{_now_hms()}] {client_id}  {_fmt_cmd(cmd)} -> {resp.get('op')}"
                )

                # 回执（ping 回 pong，其它回 ok / paused / error）
                resp_bytes = json.dumps(resp).encode("utf-8")
                try:
                    conn.sendall(encode(resp_bytes))
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
        self.setWindowTitle("myolo-pcontrol 桌面控制端")
        self.resize(760, 560)

        # 当前运行中的工作线程（未启动时为 None）
        self._worker = None
        self._conn_count = 0

        self._build_ui()

    # ------------------------------------------------------------------
    # 界面搭建
    # ------------------------------------------------------------------
    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)

        # --- 监听设置区 ---
        settings_box = QGroupBox("监听设置")
        form = QFormLayout(settings_box)
        self._port_spin = QSpinBox()
        self._port_spin.setRange(1, 65535)
        self._port_spin.setValue(DEFAULT_PORT)
        form.addRow("监听端口", self._port_spin)

        self._alpha_spin = QDoubleSpinBox()
        self._alpha_spin.setRange(0.05, 1.0)
        self._alpha_spin.setSingleStep(0.05)
        self._alpha_spin.setValue(DEFAULT_ALPHA)
        form.addRow("EMA 平滑系数 (alpha)", self._alpha_spin)

        self._scale_spin = QDoubleSpinBox()
        self._scale_spin.setRange(0.1, 5.0)
        self._scale_spin.setSingleStep(0.1)
        self._scale_spin.setValue(DEFAULT_SCALE)
        form.addRow("坐标缩放倍率", self._scale_spin)

        root.addWidget(settings_box)

        # --- 控制/状态区 ---
        ctrl_box = QGroupBox("服务控制")
        ctrl_layout = QVBoxLayout(ctrl_box)

        btn_row = QHBoxLayout()
        self._start_btn = QPushButton("启动服务")
        self._stop_btn = QPushButton("停止服务")
        self._stop_btn.setEnabled(False)
        self._start_btn.clicked.connect(self._on_start)
        self._stop_btn.clicked.connect(self._on_stop)
        btn_row.addWidget(self._start_btn)
        btn_row.addWidget(self._stop_btn)
        btn_row.addStretch()

        self._pause_cb = QCheckBox("暂停鼠标控制（快捷键：空格）")
        self._pause_cb.stateChanged.connect(self._on_pause_toggled)
        btn_row.addWidget(self._pause_cb)
        ctrl_layout.addLayout(btn_row)

        # 连接数显示
        self._conn_label = QLabel(f"当前连接数：{self._conn_count}")
        ctrl_layout.addWidget(self._conn_label)
        root.addWidget(ctrl_box)

        # --- 指令日志区 ---
        log_box = QGroupBox("指令日志")
        log_layout = QVBoxLayout(log_box)
        self._log_view = QPlainTextEdit()
        self._log_view.setReadOnly(True)
        self._log_view.setMaximumBlockCount(2000)  # 限制日志条数，避免内存膨胀
        log_layout.addWidget(self._log_view)
        root.addWidget(log_box, 1)

        # --- 状态栏 ---
        self._status_label = QLabel("未启动")
        self.statusBar().addPermanentWidget(self._status_label)
        # 用定时器定期刷新到最新日志（非必须，仅保证界面即时）
        # 状态栏默认显示一条提示
        self.statusBar().showMessage("就绪")

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
        )
        # 跨线程信号 → UI 线程槽
        self._worker.log_emit.connect(self._append_log)
        self._worker.conn_emit.connect(self._update_conn)
        self._worker.state_emit.connect(self._on_state_change)

        self._start_btn.setEnabled(False)
        self._stop_btn.setEnabled(True)
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
        self.statusBar().showMessage(state)

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

    @Slot(bool)
    def _on_state_change(self, running: bool):
        """根据运行状态更新状态栏与按钮。"""
        if running:
            self._status_label.setText("运行中")
            self.statusBar().showMessage("服务运行中")
        else:
            self._status_label.setText("未启动")
            self.statusBar().showMessage("服务已停止")

    def _set_settings_enabled(self, enabled: bool):
        """启用/禁用监听设置输入框。"""
        self._port_spin.setEnabled(enabled)
        self._alpha_spin.setEnabled(enabled)
        self._scale_spin.setEnabled(enabled)

    def closeEvent(self, event):
        """关闭窗口时干净地停止所有线程与 socket。"""
        if self._worker is not None:
            self._worker.stop()
        super().closeEvent(event)


def main():
    """程序入口。"""
    import sys
    from PySide6.QtWidgets import QApplication

    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
