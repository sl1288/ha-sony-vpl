"""Sensor platform for the Sony VPL projector integration."""

from dataclasses import dataclass
from typing import Final, override

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import EntityCategory, UnitOfTime
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import items
from .coordinator import (
    SonyVplConfigEntry,
    SonyVplRuntimeData,
    SonyVplStatusCoordinator,
)
from .entity import SonyVplEntity, SonyVplSettingEntity
from .items import POWER_STATUS_OPTIONS

PARALLEL_UPDATES = 0


@dataclass(frozen=True, kw_only=True)
class SonyVplSensorDescription(SensorEntityDescription):
    """Describes a Sony VPL projector sensor entity."""

    item: int


SENSORS: Final[tuple[SonyVplSensorDescription, ...]] = (
    SonyVplSensorDescription(
        key="lamp_hours",
        item=items.ITEM_LAMP_TIMER,
        device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.HOURS,
        state_class=SensorStateClass.TOTAL_INCREASING,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: SonyVplConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the Sony VPL projector sensors."""
    runtime = entry.runtime_data
    async_add_entities(
        [
            SonyVplPowerSensor(runtime.status),
            *(SonyVplSensor(runtime, description) for description in SENSORS),
        ]
    )


class SonyVplSensor(SonyVplSettingEntity, SensorEntity):
    """A read-only numeric projector value backed by a single item."""

    entity_description: SonyVplSensorDescription

    def __init__(
        self, runtime: SonyVplRuntimeData, description: SonyVplSensorDescription
    ) -> None:
        """Initialize the sensor."""
        super().__init__(runtime, description, description.item)

    @property
    @override
    def native_value(self) -> int | None:
        """Return the current value."""
        return self.raw_value


class SonyVplPowerSensor(SonyVplEntity, SensorEntity):
    """The projector's detailed power state.

    Separate from the remote's on/off, which cannot distinguish warming up from
    cooling down because both of those are reported as off.
    """

    _attr_translation_key = "power_status"
    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = POWER_STATUS_OPTIONS
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator: SonyVplStatusCoordinator) -> None:
        """Initialize the power sensor."""
        super().__init__(coordinator)
        entry = coordinator.config_entry
        self._attr_unique_id = f"{entry.unique_id or entry.entry_id}_power_status"

    @property
    @override
    def native_value(self) -> str | None:
        """Return the power state as an option slug."""
        if (power := self.coordinator.data.power) is None:
            return None
        return power.slug
