"""PDU-9 智能电源控制器集成。"""

from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, CONF_PORT, Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr

from .client import PDU9Client
from .const import (
    DEFAULT_PORT,
    DOMAIN,
    MANUFACTURER,
    MODEL,
    SUB_DEVICE_NAMES,
)
from .coordinator import PDU9Coordinator
from .entity import sub_device_id

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [
    Platform.BINARY_SENSOR,
    Platform.BUTTON,
    Platform.NUMBER,
    Platform.SELECT,
    Platform.SENSOR,
    Platform.SWITCH,
]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """建立与一台 PDU-9 主机的连接。

    连接交给协调器的首次刷新去做，不在这里先连一次——设备走 DHCP，IP 变了之后
    只有协调器里的自动重定位能按 UUID 把它找回来，提前连会让重定位没机会执行。
    """
    client = PDU9Client(entry.data[CONF_HOST], entry.data.get(CONF_PORT, DEFAULT_PORT))
    coordinator = PDU9Coordinator(hass, entry, client)
    try:
        await coordinator.async_config_entry_first_refresh()
    except Exception:
        await client.async_disconnect()
        raise

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator
    _async_register_devices(hass, entry, client)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    return True


def _async_register_devices(
    hass: HomeAssistant, entry: ConfigEntry, client: PDU9Client
) -> None:
    """先把主设备和两个子设备建出来，再加载平台。

    子设备的 via_device 指向主设备，主设备必须先存在才能挂上去；实体是由
    各平台异步建立的，谁先谁后不确定，所以在这里一次性建好。
    """
    registry = dr.async_get(hass)
    device_id = entry.unique_id or entry.entry_id
    base_name = client.name or entry.title

    main = registry.async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={(DOMAIN, device_id)},
        name=base_name,
        manufacturer=MANUFACTURER,
        model=MODEL,
        sw_version=client.version or None,
        configuration_url=f"http://{client.host}",
    )

    for sub_device, suffix in SUB_DEVICE_NAMES.items():
        identifiers = {(DOMAIN, sub_device_id(device_id, sub_device))}
        existed = registry.async_get_device(identifiers=identifiers) is not None
        device = registry.async_get_or_create(
            config_entry_id=entry.entry_id,
            identifiers=identifiers,
            name=f"{base_name} {suffix}",
            manufacturer=MANUFACTURER,
            model=MODEL,
            via_device=(DOMAIN, device_id),
        )
        # 只在刚建出来时跟随主设备的区域。之后用户把子设备挪到别处是他的选择，
        # 每次启动都强行拉回来就成了跟用户打架。
        if not existed and main.area_id is not None:
            registry.async_update_device(device.id, area_id=main.area_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """卸载配置项，断开 TCP 连接。"""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    coordinator: PDU9Coordinator | None = hass.data.get(DOMAIN, {}).pop(entry.entry_id, None)
    if coordinator is not None:
        await coordinator.client.async_disconnect()
    if not hass.data.get(DOMAIN):
        hass.data.pop(DOMAIN, None)
    return unload_ok


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """选项变更（轮询间隔）后重新加载。"""
    await hass.config_entries.async_reload(entry.entry_id)
