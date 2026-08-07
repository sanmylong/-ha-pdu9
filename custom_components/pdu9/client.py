"""PDU-9 主机的 asyncio 客户端。

设备侧有几条硬约束，实现时必须照顾到（来自桌面软件的真机实测）：

1. **一次只处理一条指令，不支持流水线。** 连发多条读指令、间隔 0ms 时只有
   第一条能收到响应（回收率 20%）。所以所有请求都串行化在一把锁里，
   并且两次发送之间强制留出 :data:`COMMAND_GAP` 的间隔。
2. **控制指令（切换模式 1.1 / 单路控制 1.3）不返回响应帧**，发出去就完事，
   不能等 ACK，只能靠下一轮状态轮询纠正。
3. **响应只按功能码匹配是不够的**：一次请求超时后，它迟到的响应会被下一个
   同功能码的请求领走。所以 :meth:`PDU9Client._request` 支持传 ``match``
   做二次校验（读模式配置就用回帧里的模式号对齐）。
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import socket
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Any

from . import protocol
from .const import (
    DEFAULT_PORT,
    DISCOVERY_PORT,
    DISCOVERY_PROBE,
    DISCOVERY_REPLY_PREFIX,
)
from .protocol import BasicInfo, DeviceStatus, Frame, Func, Opcode, VersionInfo

_LOGGER = logging.getLogger(__name__)

CONNECT_TIMEOUT = 5.0
REQUEST_TIMEOUT = 3.0
WRITE_TIMEOUT = 5.0
# 实测 30ms 间隔的响应回收率才到 100%，留一点余量。
COMMAND_GAP = 0.05


class PDU9Error(Exception):
    """PDU-9 通讯异常基类。"""


class PDU9ConnectionError(PDU9Error):
    """连不上设备，或连接中途断了。"""


class PDU9TimeoutError(PDU9Error):
    """设备没有在超时时间内响应。"""


class PDU9CommandError(PDU9Error):
    """设备拒绝了该指令。"""


@dataclass(slots=True)
class DiscoveredDevice:
    """UDP 广播搜索到的设备。"""

    uuid: str
    host: str
    port: int
    name: str
    family: str
    mode: int | None


@dataclass(slots=True)
class _Pending:
    """一条等待响应的请求。"""

    func_code: int
    match: Callable[[Any], bool] | None
    future: asyncio.Future


@dataclass(slots=True)
class _WriteAck:
    """写应答。``mode`` 仅在设置模式通道时间时有值，用来对齐请求。"""

    ok: bool
    mode: int | None = None


async def async_discover(
    broadcast_addresses: Iterable[str] | None = None, timeout: float = 3.0
) -> list[DiscoveredDevice]:
    """UDP 广播搜索局域网内的 PDU-9 主机。

    设备回复形如::

        RMSD,JRDD6EEA1A08000000F70700DC,{"f":"JR-PDU9","n":"PDU9_00F707","t":11,"cid":1,"m":255}

    UUID 要从这里取——TCP 的 1.4 读 UUID 在实测设备上只返回 "0"。

    必须往**子网定向广播**地址发（如 192.168.20.255）。实测 HA 跑在 macvlan
    容器里（自己有一个局域网 IP）时，发往 255.255.255.255 的包不会到达设备，
    只有子网广播收得到回复；所以调用方应把 HA 的 network 助手给出的广播地址传进来。
    """
    loop = asyncio.get_running_loop()
    found: dict[str, DiscoveredDevice] = {}

    class _DiscoveryProtocol(asyncio.DatagramProtocol):
        def datagram_received(self, data: bytes, addr: tuple[str, int]) -> None:
            text = data.decode("utf-8", errors="replace")
            if not text.startswith(DISCOVERY_REPLY_PREFIX):
                return
            first = text.find(",")
            second = text.find(",", first + 1)
            if second == -1:
                return
            uuid = text[first + 1 : second]
            try:
                info = json.loads(text[second + 1 :])
            except ValueError:
                info = {}
            if uuid not in found:
                found[uuid] = DiscoveredDevice(
                    uuid=uuid,
                    host=addr[0],
                    port=DEFAULT_PORT,
                    name=protocol.decode_device_name(info.get("n", "")),
                    family=info.get("f", ""),
                    mode=info.get("m"),
                )

    transport, _ = await loop.create_datagram_endpoint(
        _DiscoveryProtocol,
        local_addr=("0.0.0.0", 0),
        family=socket.AF_INET,
        allow_broadcast=True,
    )
    targets = list(broadcast_addresses or [])
    if "255.255.255.255" not in targets:
        targets.append("255.255.255.255")

    try:
        # 广播偶尔会丢，每个地址发三轮。设备重复回复的会按 UUID 去重。
        for _ in range(3):
            for target in targets:
                # 某个地址发不出去（接口没配好等）不该影响其他地址。
                with contextlib.suppress(OSError):
                    transport.sendto(DISCOVERY_PROBE, (target, DISCOVERY_PORT))
            await asyncio.sleep(min(0.3, timeout / 3))
        await asyncio.sleep(timeout)
    finally:
        transport.close()

    return list(found.values())


class PDU9Client:
    """与一台 PDU-9 主机的长连接。"""

    def __init__(self, host: str, port: int = DEFAULT_PORT) -> None:
        self.host = host
        self.port = port

        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None
        self._reader_task: asyncio.Task | None = None
        self._parser = protocol.FrameParser()
        self._pending: list[_Pending] = []
        # 所有收发串行化：设备不支持流水线。
        self._lock = asyncio.Lock()
        self._last_tx = 0.0
        self._connected = False

        self.name: str = ""
        self.version: str = ""
        self.device_type: int | None = None
        self.basic_info: BasicInfo | None = None

    @property
    def connected(self) -> bool:
        """连接是否可用。"""
        return self._connected

    # ---- 连接管理 ----

    async def async_connect(self) -> None:
        """建立 TCP 连接并读取设备基本信息。"""
        await self.async_disconnect()
        try:
            async with asyncio.timeout(CONNECT_TIMEOUT):
                self._reader, self._writer = await asyncio.open_connection(
                    self.host, self.port
                )
        except (OSError, TimeoutError) as err:
            raise PDU9ConnectionError(f"无法连接 {self.host}:{self.port}: {err}") from err

        self._parser = protocol.FrameParser()
        self._connected = True
        self._reader_task = asyncio.create_task(self._reader_loop())

        # 逐条串行读取——刚连上时连发会丢响应。失败不致命，留空即可。
        try:
            self.name = await self.async_read_name()
        except PDU9Error as err:
            _LOGGER.debug("读取主机名称失败: %s", err)
        try:
            version = await self.async_read_version()
            self.version = version.version
            self.device_type = version.device_type
        except PDU9Error as err:
            _LOGGER.debug("读取版本失败: %s", err)
        try:
            self.basic_info = await self.async_read_basic_info()
        except PDU9Error as err:
            _LOGGER.debug("读取基本信息失败: %s", err)

    async def async_disconnect(self) -> None:
        """断开连接并清理所有挂起的请求。"""
        self._connected = False

        if self._reader_task is not None:
            task = self._reader_task
            self._reader_task = None
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError, OSError):
                await task

        if self._writer is not None:
            writer = self._writer
            self._writer = None
            self._reader = None
            try:
                writer.close()
                await writer.wait_closed()
            except OSError:
                pass

        self._fail_pending(PDU9ConnectionError("连接已断开"))

    def _fail_pending(self, err: Exception) -> None:
        pending, self._pending = self._pending, []
        for entry in pending:
            if not entry.future.done():
                entry.future.set_exception(err)

    async def _reader_loop(self) -> None:
        """持续读取设备回帧。"""
        assert self._reader is not None
        try:
            while True:
                chunk = await self._reader.read(1024)
                if not chunk:
                    break
                for frame in self._parser.push(chunk):
                    self._handle_frame(frame)
        except asyncio.CancelledError:
            raise
        except OSError as err:
            _LOGGER.debug("%s 读取出错: %s", self.host, err)
        finally:
            self._connected = False
            self._fail_pending(PDU9ConnectionError("连接已断开"))

    def _handle_frame(self, frame: Frame) -> None:
        if not frame.crc_ok:
            _LOGGER.warning(
                "%s CRC 校验失败（功能码 0x%02X），丢弃该帧", self.host, frame.func_code
            )
            return

        if frame.opcode == Opcode.READ_ACK:
            self._resolve(frame.func_code, self._parse_read_ack(frame))
        elif frame.opcode == Opcode.WRITE_ACK:
            # 写应答的结果在最后一字节：01 成功、00 失败。
            ok = len(frame.data) > 0 and frame.data[-1] == 0x01
            mode = frame.data[0] if frame.func_code == Func.MODE_CHANNEL_TIME else None
            self._resolve(frame.func_code, _WriteAck(ok=ok, mode=mode))

    def _parse_read_ack(self, frame: Frame) -> Any:
        data = frame.data
        if frame.func_code == Func.GET_STATUS:
            return protocol.parse_status_payload(data)
        if frame.func_code == Func.VERSION:
            return protocol.parse_version_payload(data)
        if frame.func_code == Func.BASIC_INFO:
            return protocol.parse_basic_info_payload(data)
        if frame.func_code == Func.MODE_CHANNEL_TIME:
            return protocol.parse_mode_channel_time_payload(data)
        if frame.func_code in (Func.NAME, Func.READ_UUID):
            return protocol.parse_cstring(data)
        return None

    def _resolve(self, func_code: int, payload: Any) -> None:
        for entry in self._pending:
            if entry.func_code != func_code:
                continue
            if entry.match is not None and not entry.match(payload):
                continue
            self._pending.remove(entry)
            if not entry.future.done():
                entry.future.set_result(payload)
            return
        # 无人认领，多半是超时请求迟到的响应，丢弃即可。

    # ---- 收发 ----

    async def _wait_gap(self) -> None:
        loop = asyncio.get_running_loop()
        elapsed = loop.time() - self._last_tx
        if elapsed < COMMAND_GAP:
            await asyncio.sleep(COMMAND_GAP - elapsed)

    def _write(self, frame: bytes) -> None:
        if self._writer is None or not self._connected:
            raise PDU9ConnectionError("设备未连接")
        try:
            self._writer.write(frame)
        except OSError as err:
            raise PDU9ConnectionError(f"发送失败: {err}") from err
        self._last_tx = asyncio.get_running_loop().time()

    async def _request(
        self,
        frame: bytes,
        func_code: int,
        *,
        match: Callable[[Any], bool] | None = None,
        timeout: float = REQUEST_TIMEOUT,
        retries: int = 1,
    ) -> Any:
        """发一条指令并等待回帧。读指令没有副作用，默认重试一次。"""
        loop = asyncio.get_running_loop()
        async with self._lock:
            for attempt in range(retries + 1):
                if not self._connected:
                    raise PDU9ConnectionError("设备未连接")

                await self._wait_gap()
                future: asyncio.Future = loop.create_future()
                entry = _Pending(func_code=func_code, match=match, future=future)
                self._pending.append(entry)
                try:
                    self._write(frame)
                    async with asyncio.timeout(timeout):
                        return await future
                except TimeoutError:
                    if entry in self._pending:
                        self._pending.remove(entry)
                    _LOGGER.debug(
                        "%s 功能码 0x%02X 响应超时（第 %d 次）",
                        self.host,
                        func_code,
                        attempt + 1,
                    )
                except BaseException:
                    if entry in self._pending:
                        self._pending.remove(entry)
                    raise

        raise PDU9TimeoutError(f"设备响应超时（功能码 0x{func_code:02X}）")

    async def _fire_and_forget(self, frame: bytes) -> None:
        """发送无响应的控制指令（1.1 切换模式 / 1.3 单路控制）。"""
        async with self._lock:
            await self._wait_gap()
            self._write(frame)

    # ---- 读取 ----

    async def async_get_status(self) -> DeviceStatus:
        """1.2 获取状态。

        实测往返只要 22ms，2 秒超时足够宽松；轮询间隔默认 3 秒，
        缩短超时能让掉线更快地反映成实体不可用。
        """
        status = await self._request(
            protocol.encode_get_status(), Func.GET_STATUS, timeout=2.0
        )
        if status is None:
            raise PDU9CommandError("状态回帧无法解析")
        return status

    async def async_read_name(self) -> str:
        """1.6 读主机名称。名称也可能是十六进制编码的 UTF-8，统一解一次。"""
        raw = await self._request(protocol.encode_read_name(), Func.NAME)
        return protocol.decode_device_name(raw) if isinstance(raw, str) else raw

    async def async_read_version(self) -> VersionInfo:
        """1.7 读版本。"""
        info = await self._request(protocol.encode_get_version(), Func.VERSION)
        if info is None:
            raise PDU9CommandError("版本回帧无法解析")
        return info

    async def async_read_uuid(self) -> str:
        """1.4 读 UUID。实测设备只返回 "0"，真实 UUID 请用 UDP 搜索。"""
        return await self._request(protocol.encode_read_uuid(), Func.READ_UUID)

    async def async_read_basic_info(self) -> BasicInfo:
        """1.13 读基本信息。"""
        info = await self._request(protocol.encode_read_basic_info(), Func.BASIC_INFO)
        if info is None:
            raise PDU9CommandError("基本信息回帧无法解析")
        return info

    async def async_read_mode_delays(self, mode: int) -> list[int]:
        """1.11 读取某模式下 9 路通道的延时时间。"""
        result = await self._request(
            protocol.encode_read_mode_channel_time(mode),
            Func.MODE_CHANNEL_TIME,
            # 只按功能码匹配的话，超时请求迟到的响应会串到下一个模式上。
            match=lambda payload: payload is not None and payload[0] == mode,
        )
        return result[1]

    # ---- 写入 ----

    async def async_set_channel(self, channel_index: int, on: bool) -> None:
        """1.3 单路控制。设备不返回响应帧。"""
        await self._fire_and_forget(protocol.encode_set_channel(channel_index, on))

    async def async_switch_mode(self, mode: int) -> None:
        """1.1 切换场景模式。设备不返回响应帧。

        只发这一条就够了——各通道在该场景下的状态和延时存在设备固件里，
        固件会自行按序动作，再逐路发通道指令会和它的延时序列打架。
        """
        await self._fire_and_forget(protocol.encode_switch_mode(mode))

    async def async_write_mode_delays(self, mode: int, delays: list[int]) -> None:
        """1.10 写某模式下 9 路通道的延时时间。"""
        ack = await self._request(
            protocol.encode_set_mode_channel_time(mode, delays),
            Func.MODE_CHANNEL_TIME,
            match=lambda payload: isinstance(payload, _WriteAck) and payload.mode == mode,
            timeout=WRITE_TIMEOUT,
            retries=0,
        )
        if not ack.ok:
            raise PDU9CommandError("设备拒绝了该延时配置")

    async def async_write_basic_info(
        self, serial_baud_code: int, rs485_baud_code: int, power_off_delay: int
    ) -> BasicInfo:
        """1.12 设置基本信息，写完回读一次，以设备实际存下的值为准。"""
        ack = await self._request(
            protocol.encode_set_basic_info(
                serial_baud_code, rs485_baud_code, power_off_delay
            ),
            Func.BASIC_INFO,
            match=lambda payload: isinstance(payload, _WriteAck),
            timeout=WRITE_TIMEOUT,
            retries=0,
        )
        if not ack.ok:
            raise PDU9CommandError("设备拒绝了该配置")

        await asyncio.sleep(0.4)
        self.basic_info = await self.async_read_basic_info()
        return self.basic_info

    async def async_set_name(self, name: str) -> str:
        """1.5 修改主机名称，写完回读（设备对长度有限制，可能截断）。"""
        ack = await self._request(
            protocol.encode_set_name(name),
            Func.NAME,
            match=lambda payload: isinstance(payload, _WriteAck),
            timeout=WRITE_TIMEOUT,
            retries=0,
        )
        if not ack.ok:
            raise PDU9CommandError("设备拒绝了该名称")

        await asyncio.sleep(0.3)
        self.name = await self.async_read_name()
        return self.name
