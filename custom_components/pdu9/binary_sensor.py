"""PDU-9 场景切换状态。"""

from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .coordinator import PDU9Coordinator
from .entity import PDU9Entity


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """建立切换状态传感器。"""
    coordinator: PDU9Coordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([PDU9SwitchingSensor(coordinator)])


class PDU9SwitchingSensor(PDU9Entity, BinarySensorEntity):
    """设备是否正在按场景延时序列逐路动作。

    对应状态帧第 2 字节：01 切换中、00 完成。切换期间（实测 14~30 秒）
    不要下发通道指令，自动化里可以用这个实体来等它做完。
    """

    _attr_device_class = BinarySensorDeviceClass.RUNNING
    _attr_translation_key = "switching"

    def __init__(self, coordinator: PDU9Coordinator) -> None:
        """初始化。"""
        super().__init__(coordinator, "switching")

    @property
    def is_on(self) -> bool | None:
        """是否正在切换。"""
        if self.coordinator.data is None:
            return None
        return self.coordinator.data.switching
