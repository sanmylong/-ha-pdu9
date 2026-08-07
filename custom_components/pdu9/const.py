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

# ---- 服务 ----

SERVICE_POWER_CYCLE: Final = "power_cycle"
SERVICE_SET_MODE_DELAYS: Final = "set_mode_delays"
SERVICE_GET_MODE_DELAYS: Final = "get_mode_delays"

ATTR_OFF_SECONDS: Final = "off_seconds"
ATTR_MODE: Final = "mode"
ATTR_DELAYS: Final = "delays"

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
