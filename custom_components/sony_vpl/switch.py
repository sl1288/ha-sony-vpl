"""Switch platform for the Sony VPL projector integration."""

from dataclasses import dataclass
from typing import Any, Final, override

from homeassistant.components.switch import SwitchEntity, SwitchEntityDescription
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import items
from .coordinator import SonyVplConfigEntry, SonyVplRuntimeData
from .entity import SonyVplSettingEntity

PARALLEL_UPDATES = 0


@dataclass(frozen=True, kw_only=True)
class SonyVplSwitchDescription(SwitchEntityDescription):
    """Describes a Sony VPL projector switch entity."""

    item: int


def _tuning(key: str, item: int) -> SonyVplSwitchDescription:
    """Build a picture tuning switch, disabled in the registry by default."""
    return SonyVplSwitchDescription(
        key=key,
        item=item,
        entity_category=EntityCategory.CONFIG,
        entity_registry_enabled_default=False,
    )


SWITCHES: Final[tuple[SonyVplSwitchDescription, ...]] = (
    # Picture muting is instant and genuinely useful day to day, so unlike the
    # tuning switches it is enabled and not filed under configuration.
    SonyVplSwitchDescription(key="picture_muting", item=items.ITEM_PICTURE_MUTING),
    _tuning("reality_creation", items.ITEM_REALITY_CREATION),
    _tuning("xv_color", items.ITEM_XV_COLOR),
    _tuning("color_correction", items.ITEM_COLOR_CORRECTION),
    _tuning("input_lag_reduction", items.ITEM_INPUT_LAG_REDUCTION),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: SonyVplConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the Sony VPL projector switches."""
    async_add_entities(
        SonyVplSwitch(entry.runtime_data, description) for description in SWITCHES
    )


class SonyVplSwitch(SonyVplSettingEntity, SwitchEntity):
    """A projector setting that is either off or on."""

    entity_description: SonyVplSwitchDescription

    def __init__(
        self, runtime: SonyVplRuntimeData, description: SonyVplSwitchDescription
    ) -> None:
        """Initialize the switch."""
        super().__init__(runtime, description, description.item)

    @property
    @override
    def is_on(self) -> bool | None:
        """Return True when the setting is on."""
        if (raw := self.raw_value) is None:
            return None
        return raw == items.BOOLEAN["on"]

    @override
    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn the setting on."""
        await self.async_write_item(items.BOOLEAN["on"])

    @override
    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn the setting off."""
        await self.async_write_item(items.BOOLEAN["off"])
