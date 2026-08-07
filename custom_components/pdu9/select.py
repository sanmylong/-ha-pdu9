"""PDU-9 串口与 485 波特率（协议 1.12 / 1.13）。

这两个是设备物理串口的参数。改动会立刻影响接在串口/485 口上的外设通讯——
如果那边挂着控制面板或其他设备，改错会让它们失联，所以归到"配置"类别，
默认折叠在设备页的配置区里，不会误触。
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from homeassistant.components.select import SelectEntity, SelectEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .client import PDU9Error
from .const import DOMAIN
from .coordinator import PDU9Coordinator
from .entity import PDU9Entity
from .protocol import BAUD_RATES, BasicInfo

# 档位码 ↔ 显示值。协议写入时传的是档位码（1..0x0A）而不是波特率数值。
BAUD_OPTIONS: list[str] = [str(rate) for rate in BAUD_RATES.values()]
BAUD_CODE_BY_LABEL: dict[str, int] = {
    str(rate): code for code, rate in BAUD_RATES.items()
}


@dataclass(frozen=True, kw_only=True)
class PDU9SelectDescription(SelectEntityDescription):
    """带取值/写入函数的选择器描述。"""

    current_code_fn: Callable[[BasicInfo], int]
    write_kwarg: str


SELECTS: tuple[PDU9SelectDescription, ...] = (
    PDU9SelectDescription(
        key="serial_baud",
        translation_key="serial_baud",
        icon="mdi:serial-port",
        entity_category=EntityCategory.CONFIG,
        current_code_fn=lambda info: info.serial_baud_code,
        write_kwarg="serial_baud_code",
    ),
    PDU9SelectDescription(
        key="rs485_baud",
        translation_key="rs485_baud",
        icon="mdi:transit-connection-variant",
        entity_category=EntityCategory.CONFIG,
        current_code_fn=lambda info: info.rs485_baud_code,
        write_kwarg="rs485_baud_code",
    ),
)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """建立波特率选择器。"""
    coordinator: PDU9Coordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(PDU9BaudSelect(coordinator, desc) for desc in SELECTS)


class PDU9BaudSelect(PDU9Entity, SelectEntity):
    """一个波特率选择器。"""

    entity_description: PDU9SelectDescription
    _attr_options = BAUD_OPTIONS

    def __init__(
        self, coordinator: PDU9Coordinator, description: PDU9SelectDescription
    ) -> None:
        """初始化。"""
        super().__init__(coordinator, description.key)
        self.entity_description = description

    @property
    def available(self) -> bool:
        """基本信息读到了才可用。"""
        return super().available and self.coordinator.client.basic_info is not None

    @property
    def current_option(self) -> str | None:
        """当前波特率。设备返回未知档位码时留空，不瞎猜。"""
        info = self.coordinator.client.basic_info
        if info is None:
            return None
        rate = BAUD_RATES.get(self.entity_description.current_code_fn(info))
        return None if rate is None else str(rate)

    async def async_select_option(self, option: str) -> None:
        """写入新的波特率档位。"""
        code = BAUD_CODE_BY_LABEL.get(option)
        if code is None:
            raise HomeAssistantError(f"不支持的波特率: {option}")

        try:
            await self.coordinator.async_write_basic_info(
                **{self.entity_description.write_kwarg: code}
            )
        except PDU9Error as err:
            raise HomeAssistantError(f"设置波特率失败: {err}") from err
