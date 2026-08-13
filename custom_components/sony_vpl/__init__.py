"""The Sony VPL projector integration."""

from homeassistant.const import EVENT_HOMEASSISTANT_STOP, Platform
from homeassistant.core import Event, HomeAssistant

from .coordinator import (
    SonyVplConfigEntry,
    SonyVplRuntimeData,
    SonyVplSettingsCoordinator,
    SonyVplStatusCoordinator,
    build_client,
)

PLATFORMS: list[Platform] = [
    Platform.BINARY_SENSOR,
    Platform.BUTTON,
    Platform.NUMBER,
    Platform.REMOTE,
    Platform.SELECT,
    Platform.SENSOR,
    Platform.SWITCH,
]


async def async_setup_entry(hass: HomeAssistant, entry: SonyVplConfigEntry) -> bool:
    """Set up a Sony VPL projector from a config entry."""
    client = build_client(entry)

    status = SonyVplStatusCoordinator(hass, entry, client)
    await status.async_config_entry_first_refresh()

    # No first refresh for the settings coordinator: with no tuning entity enabled
    # there is nothing to read, and it must never be able to fail the setup.
    settings = SonyVplSettingsCoordinator(hass, entry, client, status)

    entry.runtime_data = SonyVplRuntimeData(
        client=client, status=status, settings=settings
    )

    async def _async_close(event: Event) -> None:
        await client.async_close()

    entry.async_on_unload(
        hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STOP, _async_close)
    )

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # Fill the settings in once, now that the platforms have registered which items
    # they actually want. Without this the enabled-by-default settings entities
    # would sit unavailable until the debounced per-entity refresh fires a couple of
    # seconds later. This reads nothing when only the status backed entities are
    # enabled, and cannot fail the setup because a settings poll never raises.
    await settings.async_refresh()

    return True


async def async_unload_entry(hass: HomeAssistant, entry: SonyVplConfigEntry) -> bool:
    """Unload a config entry."""
    if unload_ok := await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        await entry.runtime_data.client.async_close()
    return unload_ok
