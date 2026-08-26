"""屏幕截图推流模块。

把电脑屏幕截屏压缩成 JPEG，按帧格式发送给手机端（手机端做 YOLO 推理）。

帧格式（与 Android 端一致，服务端→客户端方向）：
  [4 字节大端长度][1 字节类型][载荷]
  类型 0x00：载荷为 JSON 字节串（指令回执 / 状态）
  类型 0x01：载荷为 JPEG 图片字节（屏幕帧）

客户端→服务端的请求仍是无类型前缀的 JSON 帧（见 protocol.encode），
本模块只负责服务端→客户端方向的「带类型字节」帧发送。

依赖 mss + Pillow；导入失败时仅给出 warning 提示，不崩溃。
"""

import io
import json
import logging
import threading

from protocol import encode

logger = logging.getLogger("myolo-pcontrol-screen")

# 帧类型字节
TYPE_JSON = 0x00
TYPE_JPEG = 0x01


def _clamp_int(value, default: int, lo: int, hi: int) -> int:
    """把 value 安全转成 int 并夹在 [lo, hi] 内；非法值回退 default。"""
    try:
        v = int(value)
    except (TypeError, ValueError):
        v = default
    return max(lo, min(hi, v))


def _send_typed_frame(conn, type_byte: int, payload: bytes, send_lock=None) -> bytes:
    """发送带类型字节的整帧 = [类型字节][4 字节大端长度(载荷大小)][载荷]。

    :param conn: socket 对象
    :param type_byte: 帧类型字节（0x00=JSON，0x01=JPEG）
    :param payload: 载荷字节串
    :param send_lock: 可选 per-connection 发送锁，避免与其它线程并发 sendall 时帧错位
    :return: 整帧字节串（便于测试/调试）
    """
    frame = bytes([type_byte]) + encode(payload)
    if send_lock is not None:
        with send_lock:
            conn.sendall(frame)
    else:
        conn.sendall(frame)
    return frame


def send_json_frame(conn, payload, send_lock=None) -> bytes:
    """发送类型 0x00 的 JSON 帧（服务端回执统一走这里）。

    :param conn: socket 对象
    :param payload: dict / JSON 字节串 / 字符串
    :param send_lock: 可选 per-connection 发送锁
    :return: 整帧字节串
    """
    if isinstance(payload, dict):
        payload = json.dumps(payload).encode("utf-8")
    elif not isinstance(payload, (bytes, bytearray)):
        payload = str(payload).encode("utf-8")
    return _send_typed_frame(conn, TYPE_JSON, bytes(payload), send_lock)


class ScreenStreamer(threading.Thread):
    """用 mss 抓屏 + Pillow 编码 JPEG，循环发送屏幕帧给客户端。

    在独立线程内运行；连接断开或调用 stop() 时静默退出。
    目标宽默认 640，高度等比缩放；fps / quality 均可配置并在非法值时回退默认。
    """

    def __init__(
        self,
        conn,
        fps=10,
        quality=70,
        width=640,
        send_lock=None,
    ):
        super().__init__(daemon=True)
        self.conn = conn
        self.fps = _clamp_int(fps, 10, 1, 60)
        self.quality = _clamp_int(quality, 70, 1, 100)
        self.width = _clamp_int(width, 640, 1, 10000)
        self.send_lock = send_lock
        self._stop_event = threading.Event()

    def stop(self):
        """请求停止推流（幂等，可重复调用）。"""
        self._stop_event.set()

    def run(self):
        try:
            import mss
            from PIL import Image
        except ImportError as e:
            logger.warning(
                "屏幕推流依赖缺失，无法推流: %s（请 pip install mss pillow）", e
            )
            return

        interval = 1.0 / self.fps
        try:
            with mss.mss() as sct:
                # monitors[0] 是全部显示器的联合虚拟屏；优先取主显示器（monitors[1]），
                # 只有单显示器回退到 monitors[0]。
                monitor = sct.monitors[1] if len(sct.monitors) > 1 else sct.monitors[0]

                while not self._stop_event.is_set():
                    try:
                        shot = sct.grab(monitor)
                        # mss 的 .rgb 已是 RGB 字节（无 alpha）
                        img = Image.frombytes("RGB", shot.size, shot.rgb)
                        # 等比缩放到目标宽（高度等比）
                        if img.width > self.width:
                            new_h = int(img.height * self.width / img.width)
                            img = img.resize((self.width, new_h), Image.LANCZOS)
                        img = img.convert("RGB")
                        buf = io.BytesIO()
                        img.save(buf, format="JPEG", quality=self.quality)
                        jpeg = buf.getvalue()
                        _send_typed_frame(self.conn, TYPE_JPEG, jpeg, self.send_lock)
                    except OSError:
                        # 连接断开：静默退出
                        break
                    except Exception as e:
                        logger.warning("推流时出错: %s", e)

                    self._stop_event.wait(interval)
        except Exception as e:
            # mss 初始化等不可恢复错误
            logger.warning("屏幕推流线程退出: %s", e)
