"""PDU-9 集成常量。"""

from __future__ import annotations

from typing import Final

DOMAIN: Final = "pdu9"

DEFAULT_PORT: Final = 1002
DISCOVERY_PORT: Final = 2288
DISCOVERY_PROBE: Final = b"FMSD,"
DISCOVERY_REPLY_PREFIX: Final = "RMSD,"

CHANNEL_COUNT: Final = 9

CONF_UUID: Final = "uuid"
CONF_DEVICE_NAME: Final = "device_name"
CONF_SCAN_INTERVAL_SECONDS: Final = "scan_interval_seconds"

# 设备约每秒处理 40 个请求，3 秒一次轮询远在余量内。
DEFAULT_SCAN_INTERVAL: Final = 3
MIN_SCAN_INTERVAL: Final = 2
MAX_SCAN_INTERVAL: Final = 60

MANUFACTURER: Final = "UnitLink"
MODEL: Final = "PDU-9"

# ---- 子设备 ----
#
# 一台 PDU-9 在 HA 里注册成三个设备：主设备放固件信息和参数配置，
# 场景和通道各自成一个子设备（via_device 指向主设备）。这样在设备页
# 「添加至仪表盘」时，拿到的卡片天然就是分开的——只用场景的场合不必
# 面对 9 路通道开关。实体的 unique_id 不变，换归属不会改 entity_id。
SUB_DEVICE_SCENE: Final = "scene"
SUB_DEVICE_CHANNEL: Final = "channel"

SUB_DEVICE_NAMES: Final[dict[str, str]] = {
    SUB_DEVICE_SCENE: "场景",
    SUB_DEVICE_CHANNEL: "通道",
}

# ---- 服务 ----

SERVICE_POWER_CYCLE: Final = "power_cycle"
SERVICE_SET_MODE_DELAYS: Final = "set_mode_delays"
SERVICE_GET_MODE_DELAYS: Final = "get_mode_delays"
SERVICE_RUN_SEQUENCE: Final = "run_sequence"

ATTR_OFF_SECONDS: Final = "off_seconds"
ATTR_MODE: Final = "mode"
ATTR_DELAYS: Final = "delays"
ATTR_DIRECTION: Final = "direction"
ATTR_INTERVAL: Final = "interval"

DIRECTION_ON: Final = "on"
DIRECTION_OFF: Final = "off"

# 逐路开关的间隔。设备一次只处理一条指令，逐条发送并留间隔，顺序才是确定的。
DEFAULT_SEQUENCE_INTERVAL: Final = 1.0
MIN_SEQUENCE_INTERVAL: Final = 0.1
MAX_SEQUENCE_INTERVAL: Final = 60.0

DEFAULT_OFF_SECONDS: Final = 5
MIN_OFF_SECONDS: Final = 1
MAX_OFF_SECONDS: Final = 600

# 服务里用 -1 表示"该路在此场景下不参与"，对应协议的 0xFFFF。
# 用 -1 而不是直接写 65535，是因为后者容易被误当成一个超长延时。
DELAY_OFF: Final = -1
MAX_DELAY_SECONDS: Final = 65534

# 延时关机时间（1.12/1.13），单位秒。
MIN_POWER_OFF_DELAY: Final = 0
MAX_POWER_OFF_DELAY: Final = 120
