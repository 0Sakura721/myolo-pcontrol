"""帧协议与指令编解码。

帧格式：[4 字节大端无符号长度][载荷]
载荷为 JSON 字节串。
本模块提供下列能力：
  - encode(commands_payload)     -> 为载荷增加 4 字节大端长度前缀
  - read_frame(sock)             -> 从 socket 精确读取一帧（先读 4 字节长度，再读满该长度），处理短读
  - decode_command(json_bytes)   -> 把 JSON 字节串解析为指令 dict
"""

import json
import struct

# 长度前缀字节数
LENGTH_FIELD_SIZE = 4


def encode(commands_payload: bytes) -> bytes:
    """为载荷增加 4 字节大端无符号长度前缀。

    :param commands_payload: 待发送的载荷字节串（JSON 字节串）
    :return: 带长度前缀的整帧字节串
    """
    length = len(commands_payload)
    return struct.pack(">I", length) + commands_payload


def _recv_exact(sock, n: int) -> bytes:
    """从 socket 精确读取 n 个字节，处理短读（返回不足 n 时抛异常）。

    :param sock: socket 对象
    :param n: 期望读取的字节数
    :return: 读取到的 n 个字节
    :raises EOFError: 连接在读完 n 字节前被对端关闭
    """
    chunks = bytearray()
    while len(chunks) < n:
        chunk = sock.recv(n - len(chunks))
        if not chunk:
            # 对端关闭且尚未读到足够字节
            raise EOFError("连接被对端关闭，读取到不完整的数据")
        chunks.extend(chunk)
    return bytes(chunks)


def read_frame(sock) -> bytes:
    """从 socket 精确读取一帧。

    先读 4 字节大端长度，再读满该长度的载荷字节。

    :param sock: socket 对象
    :return: 帧载荷字节串（不含长度前缀）
    :raises EOFError: 读取失败或连接被关闭
    """
    head = _recv_exact(sock, LENGTH_FIELD_SIZE)
    length = struct.unpack(">I", head)[0]
    return _recv_exact(sock, length)


def decode_command(json_bytes: bytes) -> dict:
    """把 JSON 字节串解析为指令 dict。

    :param json_bytes: JSON 字节串
    :return: 指令 dict
    :raises ValueError: JSON 解析失败时抛 ValueError（由调用方容错处理）
    """
    return json.loads(json_bytes.decode("utf-8"))
