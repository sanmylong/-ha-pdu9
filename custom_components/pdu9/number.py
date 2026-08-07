"""PDU-9 延时关机时间（协议 1.12 / 1.13）。"""

from __future__ import annotations

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory, UnitOfTime
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .client import PDU9Error
from .const import DOMAIN, MAX_POWER_OFF_DELAY, MIN_POWER_OFF_DELAY
from .coordinator import PDU9Coordinator
from .entity import PDU9Entity


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """建立延时关机时间实体。"""
    coordinator: PDU9Coordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([PDU9PowerOffDelayNumber(coordinator)])


class PDU9PowerOffDelayNumber(PDU9Entity, NumberEntity):
    """延时关机时间，存在设备里。"""

    _attr_entity_category = EntityCategory.CONFIG
    _attr_translation_key = "power_off_delay"
    _attr_native_unit_of_measurement = UnitOfTime.SECONDS
    _attr_native_min_value = MIN_POWER_OFF_DELAY
    _attr_native_max_value = MAX_POWER_OFF_DELAY
    _attr_native_step = 1
    _attr_mode = NumberMode.BOX
    _attr_icon = "mdi:timer-off-outline"

    def __init__(self, coordinator: PDU9Coordinator) -> None:
        """初始化。"""
        super().__init__(coordinator, "power_off_delay")

    @property
    def available(self) -> bool:
        """基本信息读到了才可用。"""
        return super().available and self.coordinator.client.basic_info is not None

    @property
    def native_value(self) -> float | None:
        """当前设置值。"""
        info = self.coordinator.client.basic_info
        return None if info is None else info.power_off_delay

    async def async_set_native_value(self, value: float) -> None:
        """写入新的延时关机时间。"""
        try:
            await self.coordinator.async_write_basic_info(power_off_delay=int(value))
        except PDU9Error as err:
            raise HomeAssistantError(f"设置延时关机时间失败: {err}") from err
