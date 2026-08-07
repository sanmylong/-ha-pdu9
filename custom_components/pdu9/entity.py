"""PDU-9 实体基类。"""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, MANUFACTURER, MODEL
from .coordinator import PDU9Coordinator


class PDU9Entity(CoordinatorEntity[PDU9Coordinator]):
    """所有 PDU-9 实体共用的设备归属和可用性判断。"""

    _attr_has_entity_name = True

    def __init__(self, coordinator: PDU9Coordinator, key: str) -> None:
        """初始化实体。"""
        super().__init__(coordinator)
        self._device_id = coordinator.entry.unique_id or coordinator.entry.entry_id
        self._attr_unique_id = f"{self._device_id}_{key}"

    @property
    def device_info(self) -> DeviceInfo:
        """设备信息。名称与固件版本在每次连接时从设备读回。"""
        client = self.coordinator.client
        return DeviceInfo(
            identifiers={(DOMAIN, self._device_id)},
            name=client.name or self.coordinator.entry.title,
            manufacturer=MANUFACTURER,
            model=MODEL,
            sw_version=client.version or None,
            configuration_url=f"http://{client.host}",
        )

    @property
    def available(self) -> bool:
        """轮询成功且拿到过状态才算可用。"""
        return super().available and self.coordinator.data is not None

    @property
    def _switching(self) -> bool:
        """设备是否正在按场景延时序列逐路动作。"""
        return bool(self.coordinator.data and self.coordinator.data.switching)
