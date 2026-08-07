"""PDU-9 配置流程。"""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.const import CONF_HOST, CONF_PORT
from homeassistant.core import callback

try:  # HA 2025.1 起挪了位置，两边都兼容
    from homeassistant.helpers.service_info.dhcp import DhcpServiceInfo
except ImportError:  # HA 2024.x
    from homeassistant.components.dhcp import DhcpServiceInfo

from .client import DiscoveredDevice, PDU9Client, PDU9Error, async_discover
from .const import (
    CONF_DEVICE_NAME,
    CONF_SCAN_INTERVAL_SECONDS,
    CONF_UUID,
    DEFAULT_PORT,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    MAX_SCAN_INTERVAL,
    MIN_SCAN_INTERVAL,
)
from .discovery import async_broadcast_addresses

_LOGGER = logging.getLogger(__name__)

MANUAL_HOST = "manual"


class PDU9ConfigFlow(ConfigFlow, domain=DOMAIN):
    """引导用户搜索或手动填写 PDU-9 主机。"""

    VERSION = 1

    def __init__(self) -> None:
        """初始化。"""
        self._discovered: dict[str, Any] = {}
        self._pending: DiscoveredDevice | None = None

    async def async_step_dhcp(
        self, discovery_info: DhcpServiceInfo
    ) -> ConfigFlowResult:
        """DHCP 自动发现。

        manifest 里按 OUI 00:08:DC 粗筛，那是 WIZnet 的以太网芯片，很多嵌入式
        设备都在用，光看 MAC 认不出是不是 PDU-9。所以这里再用 UDP 搜索确认一次：
        只有回复里 "f" 是 JR-PDU9 的才算数，顺便把 UUID 也拿到手——UUID 只能从
        UDP 回复里取，TCP 的 1.4 读 UUID 在实测设备上只返回 "0"。

        确认不了就静默放弃，免得给局域网里别的 WIZnet 设备弹一张 PDU-9 的卡片。
        """
        host = discovery_info.ip
        try:
            devices = await async_discover(await async_broadcast_addresses(self.hass))
        except OSError as err:
            _LOGGER.debug("DHCP 发现 %s 后 UDP 确认失败: %s", host, err)
            return self.async_abort(reason="not_pdu9")

        device = next(
            (d for d in devices if d.host == host and d.family.startswith("JR-PDU9")),
            None,
        )
        if device is None:
            _LOGGER.debug("%s 的 MAC 像 PDU-9，但 UDP 确认不是，忽略", host)
            return self.async_abort(reason="not_pdu9")

        await self.async_set_unique_id(device.uuid or f"{host}:{device.port}")
        # 设备换了 IP 时，靠 UUID 认出是同一台并把地址更新过去。
        self._abort_if_unique_id_configured(updates={CONF_HOST: host})

        self._pending = device
        self.context["title_placeholders"] = {"name": device.name or "PDU-9"}
        return await self.async_step_discovery_confirm()

    async def async_step_discovery_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """让用户确认这台自动发现到的设备。"""
        device = self._pending
        assert device is not None

        if user_input is not None:
            return await self._async_create(
                host=device.host, port=device.port, uuid=device.uuid, name=device.name
            )

        self._set_confirm_only()
        return self.async_show_form(
            step_id="discovery_confirm",
            description_placeholders={
                "name": device.name or "PDU-9",
                "host": device.host,
            },
        )

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """先 UDP 广播搜一遍，搜到就让用户挑，搜不到直接转手动填写。"""
        if user_input is not None:
            if user_input[CONF_HOST] == MANUAL_HOST:
                return await self.async_step_manual()
            device = self._discovered[user_input[CONF_HOST]]
            return await self._async_create(
                host=device.host, port=device.port, uuid=device.uuid, name=device.name
            )

        try:
            broadcast_addresses = await async_broadcast_addresses(self.hass)
            _LOGGER.debug("向这些广播地址搜索 PDU-9: %s", broadcast_addresses)
            devices = await async_discover(broadcast_addresses)
        except OSError as err:
            # 广播发不出去不是错误，转手动填写即可。
            _LOGGER.debug("UDP 搜索失败，转为手动填写: %s", err)
            devices = []

        configured = {
            entry.data.get(CONF_HOST) for entry in self._async_current_entries()
        }
        # 局域网里的 JR8 等同系列设备也会回应 FMSD 广播，按家族标识只留 PDU-9，
        # 否则会把别的产品也列进来让用户挑。
        self._discovered = {
            device.host: device
            for device in devices
            if device.family.startswith("JR-PDU9") and device.host not in configured
        }
        if not self._discovered:
            return await self.async_step_manual()

        options = {
            host: f"{device.name or 'PDU-9'} ({host})"
            for host, device in self._discovered.items()
        }
        options[MANUAL_HOST] = "手动输入 IP 地址"

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({vol.Required(CONF_HOST): vol.In(options)}),
        )

    async def async_step_manual(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """手动填写 IP 与端口。"""
        errors: dict[str, str] = {}

        if user_input is not None:
            host = user_input[CONF_HOST].strip()
            port = user_input.get(CONF_PORT, DEFAULT_PORT)
            client = PDU9Client(host, port)
            try:
                await client.async_connect()
                await client.async_get_status()
            except PDU9Error as err:
                _LOGGER.debug("连接 %s:%s 失败: %s", host, port, err)
                errors["base"] = "cannot_connect"
            else:
                name = client.name
                return await self._async_create(
                    host=host, port=port, uuid=None, name=name
                )
            finally:
                await client.async_disconnect()

        return self.async_show_form(
            step_id="manual",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_HOST, default=(user_input or {}).get(CONF_HOST, "")): str,
                    vol.Optional(CONF_PORT, default=DEFAULT_PORT): vol.All(
                        vol.Coerce(int), vol.Range(min=1, max=65535)
                    ),
                }
            ),
            errors=errors,
        )

    async def _async_create(
        self, *, host: str, port: int, uuid: str | None, name: str
    ) -> ConfigFlowResult:
        """建配置项。有 UUID 就用 UUID 做唯一标识，换 IP 也能认出同一台设备。"""
        await self.async_set_unique_id(uuid or f"{host}:{port}")
        self._abort_if_unique_id_configured(updates={CONF_HOST: host, CONF_PORT: port})

        title = name or f"PDU-9 ({host})"
        return self.async_create_entry(
            title=title,
            data={
                CONF_HOST: host,
                CONF_PORT: port,
                CONF_UUID: uuid,
                CONF_DEVICE_NAME: name,
            },
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> PDU9OptionsFlow:
        """返回选项流程。"""
        return PDU9OptionsFlow()


class PDU9OptionsFlow(OptionsFlow):
    """只有一个选项：状态轮询间隔。"""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """设置轮询间隔。"""
        if user_input is not None:
            return self.async_create_entry(data=user_input)

        current = self.config_entry.options.get(
            CONF_SCAN_INTERVAL_SECONDS, DEFAULT_SCAN_INTERVAL
        )
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_SCAN_INTERVAL_SECONDS, default=current
                    ): vol.All(
                        vol.Coerce(int),
                        vol.Range(min=MIN_SCAN_INTERVAL, max=MAX_SCAN_INTERVAL),
                    )
                }
            ),
        )
