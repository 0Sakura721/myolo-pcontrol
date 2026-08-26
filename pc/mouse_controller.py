"""使用 pynput 控制鼠标。

负责把归一化坐标(0~1)映射到真实屏幕分辨率，并支持以下指令 op：
  - move   : 移动到绝对坐标
  - click  : 移动后点击 button（left/right/middle）
  - scroll : 按 delta 滚动
  - drag   : 从当前位置按住拖拽到 x,y 再释放
  - none   : 心跳，不动作
  - ping   : 心跳，不动作

轨迹平滑：对 move 使用指数移动平均(EMA)，alpha 参数可配置(默认 0.3)，
对连续坐标平滑去抖动。
"""

import ctypes
import platform
import time

from pynput.mouse import Button, Controller

# 系统名称，用于判断屏幕尺寸获取方式
_SYSTEM = platform.system()


def _get_screen_size() -> tuple:
    """获取屏幕宽高。

    Windows 使用 ctypes 调用 GetSystemMetrics 获取真实屏幕尺寸；
    其它平台回退到 1920x1080。
    """
    try:
        if _SYSTEM == "Windows":
            user32 = ctypes.windll.user32
            width = int(user32.GetSystemMetrics(0))  # SM_CXSCREEN
            height = int(user32.GetSystemMetrics(1))  # SM_CYSCREEN
            if width > 0 and height > 0:
                return width, height
    except Exception:
        pass
    # 回退默认值
    return 1920, 1080


class MouseController:
    """封装鼠标控制的控制器。

    使用 pynput.mouse.Controller 完成实际控制。
    """

    # 跳过过小位移的阈值（像素），防止抖动
    MOVE_THRESHOLD = 3.0

    def __init__(self, alpha: float = 0.3, scale: float = 1.0):
        """初始化控制器。

        :param alpha: EMA 平滑系数(0~1)，越大越跟手、越不平滑
        :param scale: 可选坐标缩放倍率，作用于归一化坐标映射，默认 1
        """
        self.alpha = alpha
        self.scale = scale
        self._controller = Controller()
        self._screen_width, self._screen_height = _get_screen_size()
        # EMA 平滑状态（保存当前平滑后的归一化坐标，None 表示未初始化）
        self._smooth_x = None
        self._smooth_y = None

    # ------------------------------------------------------------------
    # 坐标映射
    # ------------------------------------------------------------------
    def _map_to_abs(self, x_norm: float, y_norm: float) -> tuple:
        """把归一化坐标映射到真实屏幕绝对坐标。

        x_abs = x_norm * screen_width
        y_abs = y_norm * screen_height
        scale 倍率作用于归一化值后再映射。
        """
        x_norm_s = x_norm * self.scale
        y_norm_s = y_norm * self.scale
        x_abs = x_norm_s * self._screen_width
        y_abs = y_norm_s * self._screen_height
        return x_abs, y_abs

    # ------------------------------------------------------------------
    # EMA 平滑
    # ------------------------------------------------------------------
    def _ema(self, target_x: float, target_y: float) -> tuple:
        """对归一化坐标做指数移动平均，返回平滑后的坐标。

        首次调用时直接用目标值初始化平滑状态。
        """
        if self._smooth_x is None or self._smooth_y is None:
            self._smooth_x = target_x
            self._smooth_y = target_y
            return target_x, target_y
        self._smooth_x = self.alpha * target_x + (1 - self.alpha) * self._smooth_x
        self._smooth_y = self.alpha * target_y + (1 - self.alpha) * self._smooth_y
        return self._smooth_x, self._smooth_y

    def _reset_smooth(self):
        """重置 EMA 平滑状态。"""
        self._smooth_x = None
        self._smooth_y = None

    # ------------------------------------------------------------------
    # 按钮解析
    # ------------------------------------------------------------------
    @staticmethod
    def _parse_button(button: str):
        """把字符串按钮解析为 pynput 的 Button 枚举。"""
        if button == "right":
            return Button.right
        if button == "middle":
            return Button.middle
        return Button.left  # 默认左键

    # ------------------------------------------------------------------
    # 指令执行
    # ------------------------------------------------------------------
    def _do_move(self, x_norm: float, y_norm: float):
        """移动到归一化坐标，带 EMA 平滑与最小位移阈值。"""
        sx, sy = self._ema(x_norm, y_norm)
        x_abs, y_abs = self._map_to_abs(sx, sy)
        # 计算与当前位置的差值，跳过过小位移防抖动
        current = self._controller.position
        dx = abs(x_abs - current[0])
        dy = abs(y_abs - current[1])
        if dx < self.MOVE_THRESHOLD and dy < self.MOVE_THRESHOLD:
            return
        self._controller.position = (x_abs, y_abs)

    def _do_click(self, x_norm: float, y_norm: float, button: str):
        """移动后点击指定按钮。"""
        self._reset_smooth()
        x_abs, y_abs = self._map_to_abs(x_norm, y_norm)
        self._controller.position = (x_abs, y_abs)
        btn = self._parse_button(button)
        self._controller.click(btn)

    def _do_scroll(self, delta: int):
        """按 delta 滚动（正向上，负向下）。"""
        # pynput scroll 垂直方向为正向上
        self._controller.scroll(0, int(delta))

    def _do_drag(self, x_norm: float, y_norm: float, x2_norm: float = None, y2_norm: float = None):
        """从 (x,y) 按住拖拽到 (x2,y2)（缺省则拖到 x,y）再释放。"""
        self._reset_smooth()
        x_abs, y_abs = self._map_to_abs(x_norm, y_norm)
        self._controller.position = (x_abs, y_abs)
        self._controller.press(Button.left)
        if x2_norm is not None and y2_norm is not None:
            tx, ty = self._map_to_abs(x2_norm, y2_norm)
            self._controller.position = (tx, ty)
        # 给系统一点时间响应拖拽
        time.sleep(0.01)
        self._controller.release(Button.left)

    def handle_command(self, cmd: dict) -> dict:
        """执行一条指令，返回响应 dict。

        :param cmd: 指令 dict
        :return: 响应 dict，如 {"op":"pong"}
        """
        op = cmd.get("op", "none")
        # 未知字段容错：只读取需要的字段，多余字段忽略
        x = cmd.get("x", 0.5)
        y = cmd.get("y", 0.5)
        x2 = cmd.get("x2")
        y2 = cmd.get("y2")
        button = cmd.get("button", "left")
        delta = cmd.get("delta", 0)

        # 归一化系数保护，防止非法值导致异常
        try:
            x = float(x)
            y = float(y)
        except (TypeError, ValueError):
            x, y = 0.5, 0.5

        if op == "move":
            self._do_move(x, y)
        elif op == "click":
            self._do_click(x, y, button)
        elif op == "scroll":
            self._do_scroll(delta)
        elif op == "drag":
            self._do_drag(x, y, x2, y2)
        elif op in ("none", "ping"):
            # 心跳 / 无动作
            pass
        # 未知 op 忽略，不抛异常

        # ping 需要回复 pong
        resp = {"op": "pong"} if op == "ping" else {"op": "ok"}
        return resp
