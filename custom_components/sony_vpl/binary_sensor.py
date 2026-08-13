"""Binary sensor platform for the Sony VPL projector integration."""

from typing import Any, override

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import SonyVplConfigEntry, SonyVplStatusCoordinator
from .entity import SonyVplEntity

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: SonyVplConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the Sony VPL projector binary sensors."""
    async_add_entities([SonyVplProblemSensor(entry.runtime_data.status)])


class SonyVplProblemSensor(SonyVplEntity, BinarySensorEntity):
    """Whether the projector is reporting any fault or warning.

    The two status error items are bitfields rather than enumerations: their
    values are powers of two and the projector ORs them together, so 0x48 means
    both a temperature error and a temperature warning. A single enum entity would
    therefore report nothing recognisable exactly when two faults coincide, which
    is when it matters most. The decoded names are exposed as an attribute.
    """

    _attr_translation_key = "problem"
    _attr_device_class = BinarySensorDeviceClass.PROBLEM
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator: SonyVplStatusCoordinator) -> None:
        """Initialize the problem sensor."""
        super().__init__(coordinator)
        entry = coordinator.config_entry
        self._attr_unique_id = f"{entry.unique_id or entry.entry_id}_problem"

    @property
    @override
    def is_on(self) -> bool:
        """Return True while any fault or warning is active."""
        return bool(self.coordinator.data.errors)

    @property
    @override
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return the names of the active faults and warnings."""
        return {"errors": self.coordinator.data.errors}
