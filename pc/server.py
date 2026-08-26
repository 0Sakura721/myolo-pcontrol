"""电脑端主入口：多线程 TCP 服务端。

默认监听 0.0.0.0:9999（可用 --host / --port 覆盖）。
每个连接起一个线程处理，支持多客户端。
解出指令后调用 MouseController 执行；对 ping 回复 {"op":"pong"}。
记录收到/执行的日志（含指令），优雅处理 socket 关闭与异常，不掉线程。

命令行参数：
  --host            监听地址（默认 0.0.0.0）
  --port            监听端口（默认 9999）
  --alpha           EMA 平滑系数（默认 0.3）
  --scale           坐标缩放倍率（默认 1）
  --stream-fps      屏幕推流默认帧率（默认 10）
  --stream-quality  屏幕推流默认 JPEG 质量（默认 70）
"""

import argparse
import logging
import socket
import threading

from mouse_controller import MouseController
from protocol import decode_command, read_frame
from screen_stream import ScreenStreamer, send_json_frame

# 日志配置
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("myolo-pcontrol-server")


def handle_client(conn, addr, controller: MouseController, stream_fps: int = 10, stream_quality: int = 70):
    """处理单个客户端连接的线程目标函数。

    :param conn: 已连接的 socket 对象
    :param addr: 客户端地址
    :param controller: 共享的鼠标控制器
    :param stream_fps: 屏幕推流默认帧率（可被订阅消息覆盖）
    :param stream_quality: 屏幕推流默认 JPEG 质量（可被订阅消息覆盖）
    """
    # 客户端地址字符串
    client_id = f"{addr[0]}:{addr[1]}"
    logger.info("客户端 %s 已连接", client_id)
    # 当前连接的屏幕推流器（无订阅时为 None）
    streamer = None
    # 该连接的发送锁：屏幕帧线程与回执线程共用，防止并发 sendall 帧错位
    send_lock = threading.Lock()
    try:
        while True:
            # 读取一帧（阻塞等待数据）
            payload = read_frame(conn)
            if not payload:
                break

            # 指令解码（容错：JSON 解析失败不中断连接）
            try:
                cmd = decode_command(payload)
            except (ValueError, UnicodeDecodeError) as e:
                logger.warning("客户端 %s 发送了无法解析的指令: %s", client_id, e)
                continue

            op = cmd.get("op", "none")
            logger.info("收到来自 %s 的指令: %s", client_id, cmd)

            # 屏幕推流订阅（控制类指令，不走鼠标控制器）
            if op == "subscribe_screen":
                if streamer is None or not streamer.is_alive():
                    streamer = ScreenStreamer(
                        conn,
                        fps=cmd.get("fps", stream_fps),
                        quality=cmd.get("quality", stream_quality),
                        send_lock=send_lock,
                    )
                    streamer.start()
                    logger.info(
                        "客户端 %s 已订阅屏幕推流 (fps=%s, quality=%s)",
                        client_id, streamer.fps, streamer.quality,
                    )
                resp = {"op": "ok"}
            elif op == "unsubscribe_screen":
                if streamer is not None:
                    streamer.stop()
                    streamer = None
                    logger.info("客户端 %s 已取消屏幕推流订阅", client_id)
                resp = {"op": "ok"}
            else:
                # 执行指令（容错：单条指令异常不中断连接）
                try:
                    resp = controller.handle_command(cmd)
                except Exception as e:
                    logger.error("执行指令 %s 失败: %s", cmd, e)
                    resp = {"op": "error", "error": str(e)}

            # 回执统一走带类型字节(0x00)的 JSON 帧
            try:
                send_json_frame(conn, resp, send_lock)
            except OSError as e:
                logger.error("发送响应给 %s 失败: %s", client_id, e)
                break

    except EOFError:
        logger.info("客户端 %s 连接被正常关闭", client_id)
    except socket.timeout:
        logger.info("客户端 %s 连接超时", client_id)
    except OSError as e:
        logger.warning("客户端 %s 连接异常: %s", client_id, e)
    finally:
        # 连接断开：停止推流
        if streamer is not None:
            streamer.stop()
        try:
            conn.close()
        except OSError:
            pass
        logger.info("客户端 %s 断开连接", client_id)


def run_server(host: str, port: int, alpha: float, scale: float,
               stream_fps: int = 10, stream_quality: int = 70):
    """启动 TCP 服务主循环。"""
    controller = MouseController(alpha=alpha, scale=scale)

    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    # 允许端口复用，避免重启时报地址占用
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind((host, port))
    server.listen(5)
    logger.info(
        "服务端已启动，监听 %s:%s (alpha=%s, scale=%s, stream_fps=%s, stream_quality=%s)",
        host, port, alpha, scale, stream_fps, stream_quality,
    )

    try:
        while True:
            # 接受新连接
            conn, addr = server.accept()
            # 每个连接起一个线程处理，支持多客户端
            thread = threading.Thread(
                target=handle_client,
                args=(conn, addr, controller, stream_fps, stream_quality),
                daemon=True,
            )
            thread.start()
    except KeyboardInterrupt:
        logger.info("收到中断信号，服务端停止")
    finally:
        server.close()
        logger.info("服务端已关闭")


def main():
    """解析命令行参数并启动服务。"""
    parser = argparse.ArgumentParser(description="myolo-pcontrol 电脑端 TCP 服务")
    parser.add_argument("--host", default="0.0.0.0", help="监听地址（默认 0.0.0.0）")
    parser.add_argument("--port", type=int, default=9999, help="监听端口（默认 9999）")
    parser.add_argument("--alpha", type=float, default=0.3, help="EMA 平滑系数（默认 0.3）")
    parser.add_argument("--scale", type=float, default=1.0, help="坐标缩放倍率（默认 1）")
    parser.add_argument("--stream-fps", type=int, default=10, help="屏幕推流默认帧率（默认 10）")
    parser.add_argument("--stream-quality", type=int, default=70, help="屏幕推流默认 JPEG 质量（默认 70）")
    args = parser.parse_args()

    run_server(args.host, args.port, args.alpha, args.scale, args.stream_fps, args.stream_quality)


if __name__ == "__main__":
    main()
