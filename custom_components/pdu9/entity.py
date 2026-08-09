"""PDU-9 实体基类。"""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, MANUFACTURER, MODEL, SUB_DEVICE_NAMES
from .coordinator import PDU9Coordinator


def sub_device_id(device_id: str, sub_device: str) -> str:
    """子设备在设备注册表里的标识。"""
    return f"{device_id}_{sub_device}"


class PDU9Entity(CoordinatorEntity[PDU9Coordinator]):
    """所有 PDU-9 实体共用的设备归属和可用性判断。"""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: PDU9Coordinator,
        key: str,
        *,
        sub_device: str | None = None,
    ) -> None:
        """初始化实体。

        `sub_device` 决定这个实体挂在哪个设备下：None 是主设备（固件信息、
        参数配置），其余见 const.SUB_DEVICE_*。unique_id 与子设备无关，
        所以调整归属不会改变已有实体的 entity_id。
        """
        super().__init__(coordinator)
        self._device_id = coordinator.entry.unique_id or coordinator.entry.entry_id
        self._sub_device = sub_device
        self._attr_unique_id = f"{self._device_id}_{key}"

    @property
    def device_info(self) -> DeviceInfo:
        """设备信息。名称与固件版本在每次连接时从设备读回。"""
        client = self.coordinator.client
        base_name = client.name or self.coordinator.entry.title

        if self._sub_device is None:
            return DeviceInfo(
                identifiers={(DOMAIN, self._device_id)},
                name=base_name,
                manufacturer=MANUFACTURER,
                model=MODEL,
                sw_version=client.version or None,
                configuration_url=f"http://{client.host}",
            )

        return DeviceInfo(
            identifiers={(DOMAIN, sub_device_id(self._device_id, self._sub_device))},
            name=f"{base_name} {SUB_DEVICE_NAMES[self._sub_device]}",
            manufacturer=MANUFACTURER,
            model=MODEL,
            via_device=(DOMAIN, self._device_id),
        )

    @property
    def available(self) -> bool:
        """轮询成功且拿到过状态才算可用。"""
        return super().available and self.coordinator.data is not None

    @property
    def _switching(self) -> bool:
        """设备是否正在按场景延时序列逐路动作。"""
        return bool(self.coordinator.data and self.coordinator.data.switching)
