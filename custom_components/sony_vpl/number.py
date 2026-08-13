"""Number platform for the Sony VPL projector integration."""

from dataclasses import dataclass
from typing import Final, override

from homeassistant.components.number import (
    NumberEntity,
    NumberEntityDescription,
    NumberMode,
)
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import items
from .coordinator import SonyVplConfigEntry, SonyVplRuntimeData
from .entity import SonyVplSettingEntity

PARALLEL_UPDATES = 0


@dataclass(frozen=True, kw_only=True)
class SonyVplNumberDescription(NumberEntityDescription):
    """Describes a Sony VPL projector number entity."""

    item: int


def _picture(key: str, item: int) -> SonyVplNumberDescription:
    """Build a picture adjustment slider.

    The sibling manual documents the Reality Creation sub-parameters as 1 to 100
    while the VW270ES menu shows 0 to 100. The wider range is used deliberately:
    a value the projector actually reports must never fall outside the entity's
    own range, or the state becomes unsettable and invalid.
    """
    return SonyVplNumberDescription(
        key=key,
        item=item,
        native_min_value=0,
        native_max_value=100,
        native_step=1,
        mode=NumberMode.SLIDER,
        entity_category=EntityCategory.CONFIG,
        entity_registry_enabled_default=False,
    )


NUMBERS: Final[tuple[SonyVplNumberDescription, ...]] = (
    _picture("contrast", items.ITEM_CONTRAST),
    _picture("brightness", items.ITEM_BRIGHTNESS),
    _picture("color", items.ITEM_COLOR),
    _picture("hue", items.ITEM_HUE),
    _picture("sharpness", items.ITEM_SHARPNESS),
    _picture("reality_creation_resolution", items.ITEM_REALITY_CREATION_RESOLUTION),
    _picture(
        "reality_creation_noise_filtering",
        items.ITEM_REALITY_CREATION_NOISE_FILTERING,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: SonyVplConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the Sony VPL projector numbers."""
    async_add_entities(
        SonyVplNumber(entry.runtime_data, description) for description in NUMBERS
    )


class SonyVplNumber(SonyVplSettingEntity, NumberEntity):
    """A projector setting with a numeric range."""

    entity_description: SonyVplNumberDescription

    def __init__(
        self, runtime: SonyVplRuntimeData, description: SonyVplNumberDescription
    ) -> None:
        """Initialize the number."""
        super().__init__(runtime, description, description.item)

    @property
    @override
    def native_value(self) -> float | None:
        """Return the current value."""
        return self.raw_value

    @override
    async def async_set_native_value(self, value: float) -> None:
        """Set a new value."""
        await self.async_write_item(int(value))
