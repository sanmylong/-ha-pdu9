"""局域网搜索辅助。config_flow 和 coordinator 都要用。"""

from __future__ import annotations

from ipaddress import IPv4Interface

from homeassistant.components import network
from homeassistant.core import HomeAssistant


async def async_broadcast_addresses(hass: HomeAssistant) -> list[str]:
    """列出所有网卡的子网定向广播地址。

    不能用 network.async_get_ipv4_broadcast_addresses()：HA 默认只启用默认网卡，
    那个函数在这种情况下只返回 255.255.255.255。而 HA 跑在 macvlan 容器里时，
    发往 255.255.255.255 的包到不了设备，必须发子网广播（如 192.168.20.255）——
    实测 PDU-9 只对后者回应。所以这里直接从网卡的地址和掩码自己算。
    """
    addresses: set[str] = {"255.255.255.255"}
    for adapter in await network.async_get_adapters(hass):
        for ip_info in adapter["ipv4"]:
            try:
                interface = IPv4Interface(
                    f"{ip_info['address']}/{ip_info['network_prefix']}"
                )
            except ValueError:
                continue
            if interface.ip.is_loopback:
                continue
            addresses.add(str(interface.network.broadcast_address))
    return sorted(addresses)
