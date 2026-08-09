"""PDU-9 的 9 路通道开关。"""

from __future__ import annotations

import asyncio
from typing import Any

import voluptuous as vol

from homeassistant.components.switch import SwitchDeviceClass, SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import config_validation as cv, entity_platform
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .client import PDU9Error
from .const import (
    ATTR_OFF_SECONDS,
    CHANNEL_COUNT,
    DEFAULT_OFF_SECONDS,
    DOMAIN,
    MAX_OFF_SECONDS,
    MIN_OFF_SECONDS,
    SERVICE_POWER_CYCLE,
    SUB_DEVICE_CHANNEL,
)
from .coordinator import PDU9Coordinator
from .entity import PDU9Entity


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """建立 9 个通道开关，并注册断电重启服务。"""
    coordinator: PDU9Coordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        PDU9ChannelSwitch(coordinator, index) for index in range(CHANNEL_COUNT)
    )

    platform = entity_platform.async_get_current_platform()
    platform.async_register_entity_service(
        SERVICE_POWER_CYCLE,
        {
            vol.Optional(ATTR_OFF_SECONDS, default=DEFAULT_OFF_SECONDS): vol.All(
                cv.positive_int, vol.Range(min=MIN_OFF_SECONDS, max=MAX_OFF_SECONDS)
            )
        },
        "async_power_cycle",
    )


class PDU9ChannelSwitch(PDU9Entity, SwitchEntity):
    """单路继电器通道。"""

    _attr_device_class = SwitchDeviceClass.OUTLET
    _attr_translation_key = "channel"

    def __init__(self, coordinator: PDU9Coordinator, index: int) -> None:
        """初始化通道开关。"""
        super().__init__(coordinator, f"ch{index + 1}", sub_device=SUB_DEVICE_CHANNEL)
        self._index = index
        self._attr_translation_placeholders = {"number": str(index + 1)}

    @property
    def is_on(self) -> bool | None:
        """通道当前是否通电。"""
        if self.coordinator.data is None:
            return None
        return self.coordinator.data.channels[self._index]

    async def async_turn_on(self, **kwargs: Any) -> None:
        """接通该路。"""
        await self._async_set(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        """断开该路。"""
        await self._async_set(False)

    async def async_power_cycle(self, off_seconds: int) -> None:
        """断电若干秒后重新上电，用来重启接在这一路上的设备。

        一旦开始就一定会把电送回来：断电和上电是一对，中途放弃会让设备停在
        断电状态，比不重启更糟。所以上电那步即使被取消也要执行完。

        本来就关着的通道不做重启。那一路是用户主动关掉的，"重启"它等于擅自
        把电送上去——对接在上面的设备来说这是通电而不是重启。桌面控制软件的
        掉线重启逻辑也是这么处理的，两边保持一致。
        """
        if self.is_on is None:
            raise HomeAssistantError(
                f"通道 {self._index + 1} 状态未知，无法重启"
            )
        if not self.is_on:
            raise HomeAssistantError(
                f"通道 {self._index + 1} 当前是关闭的，不执行重启"
                "（重启会把它打开，而它是被主动关掉的）"
            )

        await self._async_set(False)
        try:
            await asyncio.sleep(off_seconds)
        finally:
            # shield 挡住取消，确保这一路不会被落在断电状态。
            # 上电这步不再检查"切换中"——此时断电已经发生，送电优先。
            await asyncio.shield(self._async_set(True, ignore_switching=True))

    async def _async_set(self, on: bool, *, ignore_switching: bool = False) -> None:
        # 场景切换期间设备会按内置延时逐路动作 14~30 秒，
        # 这时插一条单路指令会和固件的延时序列打架。
        if self._switching and not ignore_switching:
            raise HomeAssistantError("设备正在切换场景，请等切换完成后再操作通道")

        try:
            await self.coordinator.client.async_set_channel(self._index, on)
        except PDU9Error as err:
            raise HomeAssistantError(f"通道 {self._index + 1} 控制失败: {err}") from err

        # 单路控制没有响应帧，先乐观更新，再补一次轮询纠正。
        self.coordinator.apply_optimistic_channel(self._index, on)
        await self.coordinator.async_request_refresh_soon()
