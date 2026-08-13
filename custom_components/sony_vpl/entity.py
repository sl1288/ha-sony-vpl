"""Base entities for the Sony VPL projector integration."""

from typing import override

from homeassistant.helpers.device_registry import CONNECTION_NETWORK_MAC, DeviceInfo
from homeassistant.helpers.entity import EntityDescription
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .api import SdcpError
from .const import DEFAULT_MODEL, DOMAIN, MANUFACTURER
from .coordinator import (
    STATUS_ITEMS,
    SonyVplRuntimeData,
    SonyVplSettingsCoordinator,
    SonyVplStatusCoordinator,
)
from .helpers import write_error


class SonyVplEntity(CoordinatorEntity[SonyVplStatusCoordinator]):
    """Base class for Sony VPL projector entities."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: SonyVplStatusCoordinator) -> None:
        """Initialize the entity."""
        super().__init__(coordinator)
        entry = coordinator.config_entry
        identity = coordinator.identity

        connections = set()
        if identity.mac_address:
            connections.add((CONNECTION_NETWORK_MAC, identity.mac_address))

        self._attr_device_info = DeviceInfo(
            # The identity items are unconfirmed on some models, so fall back to
            # the config entry id rather than leaving the device unidentified.
            identifiers={(DOMAIN, entry.unique_id or entry.entry_id)},
            connections=connections,
            name=identity.model or DEFAULT_MODEL,
            manufacturer=MANUFACTURER,
            model=identity.model,
            serial_number=identity.serial_number,
            sw_version=identity.sw_version,
            hw_version=identity.fpga_version,
            configuration_url=f"http://{coordinator.client.host}",
        )


class SonyVplSettingEntity(SonyVplEntity):
    """Base class for entities backed by a single SDCP item.

    Items listed in ``STATUS_ITEMS`` are read by the fast status coordinator;
    everything else is read lazily by the settings coordinator, which only asks
    for items whose entity is enabled.
    """

    def __init__(
        self,
        runtime: SonyVplRuntimeData,
        description: EntityDescription,
        item: int,
    ) -> None:
        """Initialize the setting entity."""
        super().__init__(runtime.status)
        self.entity_description = description
        self.settings: SonyVplSettingsCoordinator = runtime.settings
        self._item = item
        self._attr_translation_key = description.key
        entry = runtime.status.config_entry
        self._attr_unique_id = f"{entry.unique_id or entry.entry_id}_{description.key}"

    @override
    async def async_added_to_hass(self) -> None:
        """Subscribe to the settings coordinator with our item as the context.

        The context is what makes lazy polling work: the settings coordinator
        reads ``async_contexts()``, so an item is only ever requested while at
        least one enabled entity wants it. Items the status coordinator already
        reads are skipped, so they are neither polled twice nor cause a settings
        cycle to be scheduled at all.
        """
        await super().async_added_to_hass()
        if self._item in STATUS_ITEMS:
            return
        self.async_on_remove(
            self.settings.async_add_listener(
                self._handle_coordinator_update, self._item
            )
        )
        # Enabling an entity should not mean staring at "unknown" until the next
        # slow cycle comes round.
        await self.settings.async_request_refresh()

    @property
    def raw_value(self) -> int | None:
        """Return the last raw value read for this item."""
        if (value := self.coordinator.data.items.get(self._item)) is not None:
            return value
        return self.settings.data.get(self._item)

    @property
    @override
    def available(self) -> bool:
        """Return True only while the projector actually exposes this setting.

        An item the projector answered "not applicable" for is absent from the
        coordinator data. Unavailable is the honest answer: the setting does not
        apply to the current input or signal, rather than us having failed to read
        it. This also handles dependencies for free, with no dependency graph to
        maintain: Motionflow simply goes unavailable on a 4K HDR source because
        the projector says it does not apply.
        """
        return super().available and self.raw_value is not None

    async def async_write_item(self, value: int) -> None:
        """Write this entity's item, translating any failure for the user."""
        # Entity.name is a translated string for these entities, but its declared
        # type also allows the undefined sentinel, so fall back to the entity id.
        label = self.name if isinstance(self.name, str) else self.entity_id
        try:
            await self.settings.async_write(self._item, value)
        except SdcpError as err:
            raise write_error(err, label) from err
