"""PDU-9 当前场景显示。

场景切换做成了 M1–M6 按键，按键本身不显示状态，所以用这个只读实体
告诉用户设备现在处在哪个场景。值来自 1.2 状态帧，不额外占用设备的请求配额。
"""

from __future__ import annotations

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .coordinator import PDU9Coordinator
from .entity import PDU9Entity
from .protocol import MODE_LABELS


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """建立当前场景传感器。"""
    coordinator: PDU9Coordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([PDU9ModeSensor(coordinator)])


class PDU9ModeSensor(PDU9Entity, SensorEntity):
    """设备当前处在哪个场景。"""

    _attr_device_class = SensorDeviceClass.ENUM
    _attr_icon = "mdi:home-lightning-bolt"
    # 0x00 开机和 0x06 展厅没有按键，但设备可能被面板切过去，也要能显示出来。
    _attr_options = list(MODE_LABELS.values())

    def __init__(self, coordinator: PDU9Coordinator) -> None:
        """初始化。"""
        super().__init__(coordinator, "mode")
        self._attr_name = "当前场景"

    @property
    def native_value(self) -> str | None:
        """当前场景。设备返回未知模式码时留空，而不是瞎猜一个。"""
        if self.coordinator.data is None:
            return None
        return MODE_LABELS.get(self.coordinator.data.mode)
