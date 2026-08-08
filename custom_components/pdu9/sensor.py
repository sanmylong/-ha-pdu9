"""PDU-9 当前场景显示，以及场景延时的读写服务。

场景切换做成了 M1–M6 按键，按键本身不显示状态，所以用这个只读实体
告诉用户设备现在处在哪个场景。值来自 1.2 状态帧，不额外占用设备的请求配额。

协议 1.10 / 1.11 的场景延时读写也挂在这个实体上——它们是"针对某个场景"的
操作，挂在表示当前场景的实体上比挂在某个通道上更说得通。
"""

from __future__ import annotations

import voluptuous as vol

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, ServiceResponse, SupportsResponse
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_platform
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .client import PDU9Error
from .const import (
    ATTR_DELAYS,
    ATTR_DIRECTION,
    ATTR_INTERVAL,
    ATTR_MODE,
    CHANNEL_COUNT,
    DEFAULT_SEQUENCE_INTERVAL,
    DELAY_OFF,
    DIRECTION_OFF,
    DIRECTION_ON,
    DOMAIN,
    MAX_DELAY_SECONDS,
    MAX_SEQUENCE_INTERVAL,
    MIN_SEQUENCE_INTERVAL,
    SERVICE_GET_MODE_DELAYS,
    SERVICE_RUN_SEQUENCE,
    SERVICE_SET_MODE_DELAYS,
)
from .coordinator import PDU9Coordinator
from .entity import PDU9Entity
from .protocol import DELAY_DISABLED, MODE_BY_LABEL, MODE_LABELS

# 单个延时值：-1 表示该路在此场景下不参与，其余为秒数。
_DELAY_VALUE = vol.All(vol.Coerce(int), vol.Range(min=DELAY_OFF, max=MAX_DELAY_SECONDS))

_MODE_SCHEMA = {vol.Required(ATTR_MODE): vol.In(list(MODE_BY_LABEL))}


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """建立当前场景传感器，并注册场景延时读写服务。"""
    coordinator: PDU9Coordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([PDU9ModeSensor(coordinator)])

    platform = entity_platform.async_get_current_platform()
    platform.async_register_entity_service(
        SERVICE_SET_MODE_DELAYS,
        {
            **_MODE_SCHEMA,
            vol.Required(ATTR_DELAYS): vol.All(
                [_DELAY_VALUE], vol.Length(min=CHANNEL_COUNT, max=CHANNEL_COUNT)
            ),
        },
        "async_set_mode_delays",
    )
    platform.async_register_entity_service(
        SERVICE_GET_MODE_DELAYS,
        _MODE_SCHEMA,
        "async_get_mode_delays",
        supports_response=SupportsResponse.ONLY,
    )
    platform.async_register_entity_service(
        SERVICE_RUN_SEQUENCE,
        {
            vol.Required(ATTR_DIRECTION): vol.In([DIRECTION_ON, DIRECTION_OFF]),
            vol.Optional(ATTR_INTERVAL, default=DEFAULT_SEQUENCE_INTERVAL): vol.All(
                vol.Coerce(float),
                vol.Range(min=MIN_SEQUENCE_INTERVAL, max=MAX_SEQUENCE_INTERVAL),
            ),
        },
        "async_run_sequence",
    )


class PDU9ModeSensor(PDU9Entity, SensorEntity):
    """设备当前处在哪个场景。"""

    _attr_device_class = SensorDeviceClass.ENUM
    _attr_icon = "mdi:home-lightning-bolt"
    _attr_translation_key = "mode"
    # 0x00 开机和 0x06 展厅没有按键，但设备可能被面板切过去，也要能显示出来。
    _attr_options = list(MODE_LABELS.values())

    def __init__(self, coordinator: PDU9Coordinator) -> None:
        """初始化。"""
        super().__init__(coordinator, "mode")

    @property
    def native_value(self) -> str | None:
        """当前场景。设备返回未知模式码时留空，而不是瞎猜一个。"""
        if self.coordinator.data is None:
            return None
        return MODE_LABELS.get(self.coordinator.data.mode)

    async def async_run_sequence(self, direction: str, interval: float) -> None:
        """按顺序逐路开或关：开=CH1→CH9，关=CH9→CH1。"""
        if self._switching:
            raise HomeAssistantError("设备正在切换场景，请等当前切换完成")

        try:
            await self.coordinator.async_run_sequence(
                direction == DIRECTION_ON, interval
            )
        except PDU9Error as err:
            raise HomeAssistantError(f"顺序执行失败: {err}") from err

    async def async_set_mode_delays(self, mode: str, delays: list[int]) -> None:
        """1.10 写某个场景下 9 路的延时时间。"""
        payload = [DELAY_DISABLED if value == DELAY_OFF else value for value in delays]
        try:
            await self.coordinator.client.async_write_mode_delays(
                MODE_BY_LABEL[mode], payload
            )
        except PDU9Error as err:
            raise HomeAssistantError(f"写入 {mode} 的场景延时失败: {err}") from err

    async def async_get_mode_delays(self, mode: str) -> ServiceResponse:
        """1.11 读某个场景下 9 路的延时时间。"""
        try:
            raw = await self.coordinator.client.async_read_mode_delays(
                MODE_BY_LABEL[mode]
            )
        except PDU9Error as err:
            raise HomeAssistantError(f"读取 {mode} 的场景延时失败: {err}") from err

        return {
            ATTR_MODE: mode,
            ATTR_DELAYS: [
                DELAY_OFF if value == DELAY_DISABLED else value for value in raw
            ],
        }
