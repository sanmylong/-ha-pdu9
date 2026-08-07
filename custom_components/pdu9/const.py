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
