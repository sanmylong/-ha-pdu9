"""PDU-9 的 9 路通道开关。"""

from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchDeviceClass, SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .client import PDU9Error
from .const import CHANNEL_COUNT, DOMAIN
from .coordinator import PDU9Coordinator
from .entity import PDU9Entity


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """建立 9 个通道开关。"""
    coordinator: PDU9Coordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        PDU9ChannelSwitch(coordinator, index) for index in range(CHANNEL_COUNT)
    )


class PDU9ChannelSwitch(PDU9Entity, SwitchEntity):
    """单路继电器通道。"""

    _attr_device_class = SwitchDeviceClass.OUTLET

    def __init__(self, coordinator: PDU9Coordinator, index: int) -> None:
        """初始化通道开关。"""
        super().__init__(coordinator, f"ch{index + 1}")
        self._index = index
        self._attr_name = f"通道 {index + 1}"

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

    async def _async_set(self, on: bool) -> None:
        # 场景切换期间设备会按内置延时逐路动作 14~30 秒，
        # 这时插一条单路指令会和固件的延时序列打架。
        if self._switching:
            raise HomeAssistantError("设备正在切换场景，请等切换完成后再操作通道")

        try:
            await self.coordinator.client.async_set_channel(self._index, on)
        except PDU9Error as err:
            raise HomeAssistantError(f"通道 {self._index + 1} 控制失败: {err}") from err

        # 单路控制没有响应帧，先乐观更新，再补一次轮询纠正。
        self.coordinator.apply_optimistic_channel(self._index, on)
        await self.coordinator.async_request_refresh_soon()
