"""Diagnostics support for the Sony VPL projector integration.

This is the debugging channel for the item numbers and value maps that could not
be verified against a VPL-VW270ES: ``unsupported_items`` lists exactly what this
projector rejected, and ``settings`` shows the raw value behind every entity.
"""

from typing import Any

from homeassistant.core import HomeAssistant

from .coordinator import SonyVplConfigEntry


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: SonyVplConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    runtime = entry.runtime_data
    status = runtime.status

    return {
        "identity": {
            "model": status.identity.model,
            # The serial number and MAC address identify the hardware, so they
            # are left out rather than redacted: nothing here needs them.
            "sw_version": status.identity.sw_version,
            "fpga_version": status.identity.fpga_version,
        },
        "options": dict(entry.options),
        "status": {
            "last_update_success": status.last_update_success,
            "update_interval": str(status.update_interval),
            "power": status.data.power.name if status.data.power else None,
            "errors": status.data.errors,
            "items": {
                f"0x{item:04X}": value for item, value in status.data.items.items()
            },
        },
        "settings": {
            f"0x{item:04X}": value for item, value in runtime.settings.data.items()
        },
        "unsupported_items": sorted(
            f"0x{item:04X}" for item in runtime.client.unsupported_items
        ),
    }
