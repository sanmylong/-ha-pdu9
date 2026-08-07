"""PDU-9 状态轮询协调器。"""

from __future__ import annotations

import logging
from datetime import timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .client import PDU9Client, PDU9Error, async_discover
from .const import (
    CONF_SCAN_INTERVAL_SECONDS,
    CONF_UUID,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
)
from .discovery import async_broadcast_addresses
from .protocol import DeviceStatus

_LOGGER = logging.getLogger(__name__)


class PDU9Coordinator(DataUpdateCoordinator[DeviceStatus]):
    """轮询 PDU-9 状态，并在连接断开后自动重连。"""

    def __init__(
        self, hass: HomeAssistant, entry: ConfigEntry, client: PDU9Client
    ) -> None:
        """初始化协调器。"""
        interval = entry.options.get(CONF_SCAN_INTERVAL_SECONDS, DEFAULT_SCAN_INTERVAL)
        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN} {client.host}",
            update_interval=timedelta(seconds=interval),
        )
        self.entry = entry
        self.client = client

    async def _async_update_data(self) -> DeviceStatus:
        """拉一次状态。断线时先重连，重连里会顺带读回设备信息。"""
        try:
            if not self.client.connected:
                await self.client.async_connect()
            return await self.client.async_get_status()
        except PDU9Error as err:
            # 状态未知，下一轮重新建连，避免卡在半死的 socket 上。
            await self.client.async_disconnect()
            if await self._async_relocate():
                # 更新配置项会触发重载，新地址在那时生效。
                raise UpdateFailed("设备 IP 已变更，正在用新地址重连") from err
            raise UpdateFailed(str(err)) from err

    async def _async_relocate(self) -> bool:
        """设备走 DHCP，重启后 IP 可能就变了（实测遇到过 .32 变 .46）。

        连不上时用 UDP 广播按 UUID 把它找回来。UUID 是设备出厂固化的，
        比 IP 可靠；找到新地址就写回配置项，HA 会自动重载并用新地址重连。

        手动添加的条目没有 UUID（TCP 的 1.4 读 UUID 只返回 "0"），认不出是哪一台，
        只能放弃——这种情况下用户得自己改 IP。
        """
        uuid = self.entry.data.get(CONF_UUID)
        if not uuid:
            return False

        try:
            devices = await async_discover(await async_broadcast_addresses(self.hass))
        except OSError as err:
            _LOGGER.debug("找回设备时 UDP 搜索失败: %s", err)
            return False

        match = next((d for d in devices if d.uuid == uuid), None)
        if match is None or match.host == self.client.host:
            return False

        _LOGGER.warning(
            "PDU-9 的地址从 %s 变成了 %s，已自动更新配置", self.client.host, match.host
        )
        self.hass.config_entries.async_update_entry(
            self.entry, data={**self.entry.data, CONF_HOST: match.host}
        )
        return True

    def apply_optimistic_channel(self, channel_index: int, on: bool) -> None:
        """控制指令没有 ACK，先按用户意图更新 UI，下一轮轮询会纠正。"""
        if self.data is None:
            return
        channels = list(self.data.channels)
        channels[channel_index] = on
        self.data.channels = channels
        self.async_update_listeners()

    async def async_request_refresh_soon(self) -> None:
        """控制指令发出后主动补一次刷新，比等下一个轮询周期快。"""
        await self.async_request_refresh()
