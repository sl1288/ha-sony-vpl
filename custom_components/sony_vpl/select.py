"""Select platform for the Sony VPL projector integration."""

from dataclasses import dataclass
import logging
from typing import Final, override

from homeassistant.components.select import SelectEntity, SelectEntityDescription
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import items
from .coordinator import SonyVplConfigEntry, SonyVplRuntimeData
from .entity import SonyVplSettingEntity
from .items import OptionMap

_LOGGER = logging.getLogger(__name__)

# Every command is serialised by the client's lock, because the projector accepts
# only one at a time. Throttling again here would only add latency.
PARALLEL_UPDATES = 0


@dataclass(frozen=True, kw_only=True)
class SonyVplSelectDescription(SelectEntityDescription):
    """Describes a Sony VPL projector select entity."""

    item: int
    values: OptionMap


def _tuning(key: str, item: int, values: OptionMap) -> SonyVplSelectDescription:
    """Build a picture tuning select, disabled in the registry by default.

    Disabled by default is not only about registry clutter: a disabled entity
    registers no coordinator listener, so its item is never polled.
    """
    return SonyVplSelectDescription(
        key=key,
        item=item,
        values=values,
        entity_category=EntityCategory.CONFIG,
        entity_registry_enabled_default=False,
    )


SELECTS: Final[tuple[SonyVplSelectDescription, ...]] = (
    SonyVplSelectDescription(key="input", item=items.ITEM_INPUT, values=items.INPUT),
    SonyVplSelectDescription(
        key="calibration_preset",
        item=items.ITEM_CALIBRATION_PRESET,
        values=items.CALIBRATION_PRESET,
    ),
    SonyVplSelectDescription(key="aspect", item=items.ITEM_ASPECT, values=items.ASPECT),
    _tuning("lamp_control", items.ITEM_LAMP_CONTROL, items.LAMP_CONTROL),
    _tuning("contrast_enhancer", items.ITEM_CONTRAST_ENHANCER, items.CONTRAST_ENHANCER),
    _tuning("film_mode", items.ITEM_FILM_MODE, items.FILM_MODE),
    _tuning("gamma_correction", items.ITEM_GAMMA_CORRECTION, items.GAMMA_CORRECTION),
    _tuning("noise_reduction", items.ITEM_NOISE_REDUCTION, items.NOISE_REDUCTION),
    _tuning(
        "mpeg_noise_reduction",
        items.ITEM_MPEG_NOISE_REDUCTION,
        items.NOISE_REDUCTION,
    ),
    _tuning("smooth_gradation", items.ITEM_SMOOTH_GRADATION, items.SMOOTH_GRADATION),
    _tuning("clear_white", items.ITEM_CLEAR_WHITE, items.CLEAR_WHITE),
    _tuning("motionflow", items.ITEM_MOTIONFLOW, items.MOTIONFLOW),
    # These three shipped as read-only sensors until their values had been measured
    # on a real VW270ES, because a guessed value written into a projector's
    # calibration cannot be undone from Home Assistant. On another VPL model they
    # should be treated as unverified again. See the comments in items.py.
    _tuning("hdr", items.ITEM_HDR, items.HDR),
    _tuning("color_temperature", items.ITEM_COLOR_TEMPERATURE, items.COLOR_TEMPERATURE),
    _tuning("color_space", items.ITEM_COLOR_SPACE, items.COLOR_SPACE),
    _tuning(
        "reality_creation_database",
        items.ITEM_REALITY_CREATION_DATABASE,
        items.REALITY_CREATION_DATABASE,
    ),
    _tuning(
        "hdmi1_dynamic_range",
        items.ITEM_HDMI1_DYNAMIC_RANGE,
        items.DYNAMIC_RANGE,
    ),
    _tuning(
        "hdmi2_dynamic_range",
        items.ITEM_HDMI2_DYNAMIC_RANGE,
        items.DYNAMIC_RANGE,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: SonyVplConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the Sony VPL projector selects."""
    async_add_entities(
        SonyVplSelect(entry.runtime_data, description) for description in SELECTS
    )


class SonyVplSelect(SonyVplSettingEntity, SelectEntity):
    """A projector setting with a fixed list of options."""

    entity_description: SonyVplSelectDescription

    def __init__(
        self, runtime: SonyVplRuntimeData, description: SonyVplSelectDescription
    ) -> None:
        """Initialize the select."""
        super().__init__(runtime, description, description.item)
        # The map in items.py is declared once and used in both directions here,
        # so the option list and the reverse lookup cannot drift apart.
        self._attr_options = list(description.values)
        self._to_option = {
            value: option for option, value in description.values.items()
        }

    @property
    @override
    def current_option(self) -> str | None:
        """Return the selected option."""
        if (raw := self.raw_value) is None:
            return None
        if (option := self._to_option.get(raw)) is None:
            _LOGGER.warning(
                "Item 0x%04X reported undocumented value 0x%04X; please report this",
                self._item,
                raw,
            )
        return option

    @override
    async def async_select_option(self, option: str) -> None:
        """Change the selected option."""
        await self.async_write_item(self.entity_description.values[option])
