"""PDU-9 APP 端 TCP 通讯协议编解码（端口 1002）。

由 PDU-9 桌面控制软件的 ``src/shared/protocol.js`` 移植而来，
帧格式与各功能码的实测结论见《PDU-9 APP端&Can口&MQTT通讯协议.pdf》
及桌面软件 README 的"协议实测记录"一节。

帧格式::

    0xAA + 协议标识 "JR4\\0"(4B) + 参数长度(1 或 3B) + 参数 + 帧尾(0xBA/0xBB) [+ CRC16]
    参数 = 操作码(1B) + 功能码(1B) + 配置数据(N B)

帧尾 0xBA 表示无校验，0xBB 表示其后跟 2 字节 CRC16。设备回帧一律带 CRC，
算法为 CRC16/XMODEM（多项式 0x1021、初值 0x0000、无反转、无异或），
校验范围是帧头 0xAA 到帧尾 0xBB 的全部字节，传输时低字节在前。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Final

HEADER_BYTE: Final = 0xAA
PROTOCOL_ID: Final = b"JR4\x00"
TAIL_NO_CRC: Final = 0xBA
TAIL_WITH_CRC: Final = 0xBB

CHANNEL_COUNT: Final = 9


class Opcode:
    """操作码。"""

    READ: Final = 0x05
    WRITE: Final = 0x06
    READ_ACK: Final = 0x01
    WRITE_ACK: Final = 0x02


class Func:
    """功能码。"""

    SWITCH_MODE: Final = 0x01
    GET_STATUS: Final = 0x02
    SINGLE_CHANNEL: Final = 0x04
    READ_UUID: Final = 0x05
    NAME: Final = 0x06
    VERSION: Final = 0x07
    MODE_CHANNEL_TIME: Final = 0x0A
    BASIC_INFO: Final = 0x0B


class Mode:
    """场景模式编码。"""

    POWER_ON: Final = 0x00
    HUIKE: Final = 0x01
    YINGYUAN: Final = 0x02
    KTV: Final = 0x03
    HUIYI: Final = 0x04
    JIAOXUE: Final = 0x05
    ZHANTING: Final = 0x06
    OFF: Final = 0xFF


MODE_NAMES: Final[dict[int, str]] = {
    Mode.POWER_ON: "开机",
    Mode.HUIKE: "会客",
    Mode.YINGYUAN: "影院",
    Mode.KTV: "KTV",
    Mode.HUIYI: "会议",
    Mode.JIAOXUE: "教学",
    Mode.ZHANTING: "展厅",
    Mode.OFF: "关机",
}

# 界面上的场景按键。产品侧叫 M1–M6：M1–M5 对应 0x01–0x05，M6 就是关机(0xFF)。
BUTTON_MODES: Final[dict[str, int]] = {
    "M1": Mode.HUIKE,
    "M2": Mode.YINGYUAN,
    "M3": Mode.KTV,
    "M4": Mode.HUIYI,
    "M5": Mode.JIAOXUE,
    "M6": Mode.OFF,
}

# 显示用的场景名。0x00 开机和 0x06 展厅不做成按键，但设备可能被面板或桌面软件
# 切到这两个模式，所以这里仍给它们留了名字，免得界面上显示成空白。
MODE_LABELS: Final[dict[int, str]] = {
    Mode.POWER_ON: "开机",
    Mode.HUIKE: "M1",
    Mode.YINGYUAN: "M2",
    Mode.KTV: "M3",
    Mode.HUIYI: "M4",
    Mode.JIAOXUE: "M5",
    Mode.ZHANTING: "展厅",
    Mode.OFF: "M6",
}

MODE_BY_LABEL: Final[dict[str, int]] = {
    label: code for code, label in MODE_LABELS.items()
}

# 波特率档位码 → 实际波特率。写入时传的是档位码而不是波特率数值。
BAUD_RATES: Final[dict[int, int]] = {
    1: 2400,
    2: 4800,
    3: 9600,
    4: 14400,
    5: 19200,
    6: 38400,
    7: 43000,
    8: 57600,
    9: 76800,
    0x0A: 115200,
}

# 延时值 0xFFFF 不是"立即动作"，而是该路在此场景下不参与，含义随模式反转：
#   普通场景(0x01-0x06) 是"延时开"，0xFFFF = 该路保持关闭；
#   关机模式(0xFF) 是"延时关"，0xFFFF = 该路保持开启。
DELAY_DISABLED: Final = 0xFFFF


def crc16(data: bytes) -> int:
    """CRC16/XMODEM。"""
    crc = 0x0000
    for byte in data:
        crc ^= byte << 8
        for _ in range(8):
            crc = ((crc << 1) ^ 0x1021) & 0xFFFF if crc & 0x8000 else (crc << 1) & 0xFFFF
    return crc & 0xFFFF


def build_frame(
    opcode: int, func_code: int, data: bytes | list[int] = b"", *, with_crc: bool = True
) -> bytes:
    """组一帧。"""
    params = bytes([opcode, func_code]) + bytes(data)
    param_len = len(params)
    if param_len <= 254:
        len_bytes = bytes([param_len])
    else:
        len_bytes = bytes([0xFF, (param_len >> 8) & 0xFF, param_len & 0xFF])

    body = (
        bytes([HEADER_BYTE])
        + PROTOCOL_ID
        + len_bytes
        + params
        + bytes([TAIL_WITH_CRC if with_crc else TAIL_NO_CRC])
    )
    if not with_crc:
        return body

    checksum = crc16(body)
    # 低字节在前
    return body + bytes([checksum & 0xFF, (checksum >> 8) & 0xFF])


# ---- 编码 ----


def encode_switch_mode(mode: int) -> bytes:
    """1.1 切换场景模式。"""
    return build_frame(Opcode.WRITE, Func.SWITCH_MODE, [mode])


def encode_get_status() -> bytes:
    """1.2 获取状态。"""
    return build_frame(Opcode.READ, Func.GET_STATUS)


def encode_set_channel(channel_index: int, on: bool) -> bytes:
    """1.3 单路控制。channel_index 为 0-based，协议里的通道号是 1..9。"""
    return build_frame(
        Opcode.WRITE, Func.SINGLE_CHANNEL, [channel_index + 1, 0x01 if on else 0x00]
    )


def encode_read_uuid() -> bytes:
    """1.4 读 UUID。实测设备只返回 "0"，真实 UUID 需用 UDP 搜索获取。"""
    return build_frame(Opcode.READ, Func.READ_UUID)


def encode_read_name() -> bytes:
    """1.6 读主机名称。"""
    return build_frame(Opcode.READ, Func.NAME)


def encode_set_name(name: str) -> bytes:
    """1.5 修改主机名称。"""
    return build_frame(Opcode.WRITE, Func.NAME, name.encode("utf-8") + b"\x00")


def encode_get_version() -> bytes:
    """1.7 读版本。"""
    return build_frame(Opcode.READ, Func.VERSION)


def encode_read_basic_info() -> bytes:
    """1.13 读基本信息。"""
    return build_frame(Opcode.READ, Func.BASIC_INFO)


def encode_set_basic_info(
    serial_baud_code: int, rs485_baud_code: int, power_off_delay: int
) -> bytes:
    """1.12 设置基本信息。波特率传档位码(1..0x0A)，延时关机单位秒(0..120)。"""
    return build_frame(
        Opcode.WRITE,
        Func.BASIC_INFO,
        [serial_baud_code, rs485_baud_code, power_off_delay],
    )


def encode_read_mode_channel_time(mode: int) -> bytes:
    """1.11 读取某模式下 9 路通道的延时时间。"""
    return build_frame(Opcode.READ, Func.MODE_CHANNEL_TIME, [mode])


def encode_set_mode_channel_time(mode: int, delays: list[int]) -> bytes:
    """1.10 设置某模式下 9 路通道的延时时间，单位秒（或 DELAY_DISABLED）。"""
    data = [mode]
    for i in range(CHANNEL_COUNT):
        delay = delays[i] if i < len(delays) else 0
        data += [i + 1, (delay >> 8) & 0xFF, delay & 0xFF]  # 高 8 位在前
    return build_frame(Opcode.WRITE, Func.MODE_CHANNEL_TIME, data)


# ---- 解析 ----


@dataclass(slots=True)
class DeviceStatus:
    """1.2 状态回帧解析结果。"""

    mode: int
    switching: bool
    voltage: float
    current: float
    power: int
    energy: int
    device_type: int
    channels: list[bool] = field(default_factory=lambda: [False] * CHANNEL_COUNT)

    @property
    def mode_name(self) -> str | None:
        return MODE_NAMES.get(self.mode)


@dataclass(slots=True)
class VersionInfo:
    """1.7 版本回帧解析结果。"""

    device_type: int
    version: str
    power_on: bool


@dataclass(slots=True)
class BasicInfo:
    """1.13 基本信息回帧解析结果。"""

    serial_baud_code: int
    rs485_baud_code: int
    power_off_delay: int

    @property
    def serial_baud(self) -> int | None:
        return BAUD_RATES.get(self.serial_baud_code)

    @property
    def rs485_baud(self) -> int | None:
        return BAUD_RATES.get(self.rs485_baud_code)


def parse_channel_bitmap(byte1: int, byte2: int) -> list[bool]:
    """通道位图：第 1 字节 bit0-7 对应 CH1-CH8，第 2 字节 bit0 对应 CH9。"""
    channels = [bool((byte1 >> i) & 1) for i in range(8)]
    channels.append(bool(byte2 & 1))
    return channels


def parse_status_payload(data: bytes) -> DeviceStatus | None:
    """状态回帧数据段（15 字节）::

    [模式1][状态1][电压2 LE][电流2 LE][功率2 LE][电量4 LE][设备类型1][通道状态2]
    """
    if len(data) < 15:
        return None
    return DeviceStatus(
        mode=data[0],
        switching=data[1] == 0x01,
        voltage=int.from_bytes(data[2:4], "little") / 10,
        current=int.from_bytes(data[4:6], "little") / 10,
        power=int.from_bytes(data[6:8], "little"),
        energy=int.from_bytes(data[8:12], "little"),
        device_type=data[12],
        channels=parse_channel_bitmap(data[13], data[14]),
    )


def parse_version_payload(data: bytes) -> VersionInfo | None:
    """版本回帧数据段（5 字节）：[设备类型1][主1][次1][差异1][开关状态1]。"""
    if len(data) < 5:
        return None
    return VersionInfo(
        device_type=data[0],
        version=f"{data[1]}.{data[2]}.{data[3]}",
        power_on=data[4] == 0x01,
    )


def parse_basic_info_payload(data: bytes) -> BasicInfo | None:
    """基本信息回帧数据段（3 字节）：[串口波特率码][485 波特率码][延时关机秒]。"""
    if len(data) < 3:
        return None
    return BasicInfo(
        serial_baud_code=data[0],
        rs485_baud_code=data[1],
        power_off_delay=data[2],
    )


def parse_mode_channel_time_payload(data: bytes) -> tuple[int, list[int]] | None:
    """模式通道时间回帧（28 字节）：[模式1] + ([通道号1][延时2 BE]) * 9。

    失败时设备返回 [模式1][0x00]，此处返回 ``None``。
    """
    if len(data) < 28:
        return None
    delays = [0] * CHANNEL_COUNT
    for i in range(CHANNEL_COUNT):
        base = 1 + i * 3
        channel_no = data[base]
        if 1 <= channel_no <= CHANNEL_COUNT:
            delays[channel_no - 1] = int.from_bytes(data[base + 1 : base + 3], "big")
    return data[0], delays


def parse_cstring(data: bytes) -> str:
    """取以 0x00 结尾的字符串。"""
    end = data.find(b"\x00")
    return data[: end if end != -1 else len(data)].decode("utf-8", errors="replace")


_HEX_DIGITS = set("0123456789abcdefABCDEF")


def decode_device_name(raw: str) -> str:
    """设备名可能是明文，也可能是十六进制编码的 UTF-8。

    实测同系列的 JR8 设备就是后者（``4F6D6E69436F7265...`` 实为“OmniCore智能主机”），
    PDU-9 目前返回明文，但不同固件不保证一致，所以两种都认。

    解不出合法 UTF-8 就按原样返回——宁可显示得难看，也不要把明文名字弄丢。
    """
    text = raw.strip()
    if len(text) < 2 or len(text) % 2 or not all(c in _HEX_DIGITS for c in text):
        return raw
    try:
        decoded = bytes.fromhex(text).decode("utf-8").rstrip("\x00").strip()
    except (ValueError, UnicodeDecodeError):
        return raw
    return decoded or raw


# ---- 帧解析器（处理 TCP 粘包/分包） ----


@dataclass(slots=True)
class Frame:
    """一个已切分出来的完整帧。"""

    opcode: int
    func_code: int
    data: bytes
    crc_ok: bool


class FrameParser:
    """把 TCP 字节流切成一个个完整帧。"""

    def __init__(self) -> None:
        self._buffer = bytearray()

    def push(self, chunk: bytes) -> list[Frame]:
        """喂入新收到的数据，返回本次能解出的所有完整帧。"""
        self._buffer.extend(chunk)
        frames: list[Frame] = []
        buf = self._buffer

        while True:
            start = buf.find(HEADER_BYTE)
            if start == -1:
                buf.clear()
                break
            if start > 0:
                del buf[:start]

            if len(buf) < 1 + len(PROTOCOL_ID) + 1:
                break
            if bytes(buf[1 : 1 + len(PROTOCOL_ID)]) != PROTOCOL_ID:
                del buf[:1]  # 标识不匹配，跳过这个 0xAA 重新同步
                continue

            offset = 1 + len(PROTOCOL_ID)
            len_byte = buf[offset]
            if len_byte == 0xFF:
                if len(buf) < offset + 3:
                    break
                param_len = int.from_bytes(buf[offset + 1 : offset + 3], "big")
                offset += 3
            else:
                param_len = len_byte
                offset += 1

            tail_offset = offset + param_len
            if len(buf) < tail_offset + 1:
                break

            tail = buf[tail_offset]
            frame_end = tail_offset + 1
            if tail == TAIL_WITH_CRC:
                if len(buf) < frame_end + 2:
                    break
                frame_end += 2
            elif tail != TAIL_NO_CRC:
                del buf[:1]
                continue

            params = bytes(buf[offset:tail_offset])
            crc_ok = True
            if tail == TAIL_WITH_CRC:
                expected = int.from_bytes(buf[tail_offset + 1 : tail_offset + 3], "little")
                crc_ok = crc16(bytes(buf[: tail_offset + 1])) == expected

            if len(params) >= 2:
                frames.append(
                    Frame(
                        opcode=params[0],
                        func_code=params[1],
                        data=params[2:],
                        crc_ok=crc_ok,
                    )
                )

            del buf[:frame_end]

        return frames
