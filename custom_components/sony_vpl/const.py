"""Constants for the Sony VPL projector integration."""

from datetime import timedelta
from typing import Final

DOMAIN: Final = "sony_vpl"
MANUFACTURER: Final = "Sony"
DEFAULT_MODEL: Final = "VPL projector"

CONF_COMMUNITY: Final = "community"
CONF_SERIAL_NUMBER: Final = "serial_number"
CONF_MODEL: Final = "model"

CONF_SCAN_INTERVAL_ON: Final = "scan_interval_on"
CONF_SCAN_INTERVAL_STANDBY: Final = "scan_interval_standby"
CONF_SCAN_INTERVAL_SETTINGS: Final = "scan_interval_settings"
CONF_COMMAND_TIMEOUT: Final = "command_timeout"

DEFAULT_SCAN_INTERVAL_ON: Final = 15
DEFAULT_SCAN_INTERVAL_STANDBY: Final = 30
DEFAULT_SCAN_INTERVAL_SETTINGS: Final = 120
DEFAULT_COMMAND_TIMEOUT: Final = 5.0

# Warm-up takes roughly 25 seconds and cool-down about the same, so the
# transitional interval is short and deliberately not user configurable.
INTERVAL_TRANSITION: Final = timedelta(seconds=5)

# The projector answers one command at a time and may take up to 3.2 seconds, so
# a cycle that read every enabled setting could occupy it for half a minute. Cap
# the batch and rotate: every item is still refreshed within a few minutes.
MAX_ITEMS_PER_CYCLE: Final = 12
