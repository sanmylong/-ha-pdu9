"""PDU-9 场景模式按键（M1–M6）。

每个场景一个按键。按下只发一条 1.1 指令就够了——每个场景下 9 路的目标状态和
延时都存在设备固件里，固件会自行按序动作，软件不要再逐路发通道指令。
"""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .client import PDU9Error
from .const import DEFAULT_SEQUENCE_INTERVAL, DOMAIN
from .coordinator import PDU9Coordinator
from .entity import PDU9Entity
from .protocol import BUTTON_MODES

BUTTON_ICONS: dict[str, str] = {
    "M1": "mdi:sofa",
    "M2": "mdi:movie-open",
    "M3": "mdi:microphone-variant",
    "M4": "mdi:account-group",
    "M5": "mdi:school",
    "M6": "mdi:power-off",
}


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """建立 M1–M6 场景按键，以及全开/全关两个顺序按键。"""
    coordinator: PDU9Coordinator = hass.data[DOMAIN][entry.entry_id]
    entities: list[PDU9Entity] = [
        PDU9ModeButton(coordinator, label, mode) for label, mode in BUTTON_MODES.items()
    ]
    entities.append(PDU9SequenceButton(coordinator, turn_on=True))
    entities.append(PDU9SequenceButton(coordinator, turn_on=False))
    async_add_entities(entities)


class PDU9SequenceButton(PDU9Entity, ButtonEntity):
    """按固定顺序逐路开或关。

    不要用 HA 区域卡片上的总开关来做这件事——那是并行下发 9 条指令，而设备
    一次只处理一条，实际动作顺序会是随机的。这两个按键逐条发送并留 1 秒间隔，
    顺序才严格是 CH1→CH9（开）和 CH9→CH1（关）。
    """

    def __init__(self, coordinator: PDU9Coordinator, *, turn_on: bool) -> None:
        """初始化顺序按键。"""
        super().__init__(coordinator, "all_on" if turn_on else "all_off")
        self._turn_on = turn_on
        self._attr_translation_key = "all_on" if turn_on else "all_off"
        self._attr_icon = "mdi:progress-check" if turn_on else "mdi:progress-close"

    async def async_press(self) -> None:
        """依次动作。整个过程约 8 秒（9 路、间隔 1 秒）。"""
        if self._switching:
            raise HomeAssistantError("设备正在切换场景，请等当前切换完成")

        try:
            await self.coordinator.async_run_sequence(
                self._turn_on, DEFAULT_SEQUENCE_INTERVAL
            )
        except PDU9Error as err:
            action = "全开" if self._turn_on else "全关"
            raise HomeAssistantError(f"{action}执行失败: {err}") from err


class PDU9ModeButton(PDU9Entity, ButtonEntity):
    """一键切到某个场景。"""

    def __init__(self, coordinator: PDU9Coordinator, label: str, mode: int) -> None:
        """初始化场景按键。"""
        super().__init__(coordinator, f"mode_{mode:02x}")
        self._label = label
        self._mode = mode
        self._attr_name = label
        self._attr_icon = BUTTON_ICONS.get(label, "mdi:home-lightning-bolt")

    async def async_press(self) -> None:
        """切换到该场景。"""
        # 切换期间设备要按内置延时逐路动作 14~30 秒，这时再插一条会和它打架。
        if self._switching:
            raise HomeAssistantError("设备正在切换场景，请等当前切换完成")

        try:
            await self.coordinator.client.async_switch_mode(self._mode)
        except PDU9Error as err:
            raise HomeAssistantError(f"切换到 {self._label} 失败: {err}") from err

        # 切换指令没有响应帧，靠轮询看着它一路一路动作。
        await self.coordinator.async_request_refresh_soon()
