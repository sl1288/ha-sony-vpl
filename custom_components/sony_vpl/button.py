"""Button platform for the Sony VPL projector integration.

A curated handful of the infrared commands as first class entities, so the ones
people press repeatedly can go on a dashboard instead of being typed as a command
name. The remaining codes stay available through the send_command action, which
offers all of them in a searchable list.

All of these are disabled in the registry by default: which ones are worth having
depends entirely on whether you adjust the lens by hand or drive the menu.
"""

from dataclasses import dataclass
from typing import Final, override

from homeassistant.components.button import ButtonEntity, ButtonEntityDescription
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .api import SdcpError
from .const import DOMAIN
from .coordinator import SonyVplConfigEntry, SonyVplStatusCoordinator
from .entity import SonyVplEntity
from .items import IR_COMMANDS

PARALLEL_UPDATES = 0


@dataclass(frozen=True, kw_only=True)
class SonyVplButtonDescription(ButtonEntityDescription):
    """Describes a Sony VPL projector button entity."""

    command: str


def _button(key: str, *, config: bool = False) -> SonyVplButtonDescription:
    """Build a button for the infrared command of the same name."""
    return SonyVplButtonDescription(
        key=key,
        command=key,
        entity_category=EntityCategory.CONFIG if config else None,
        entity_registry_enabled_default=False,
    )


BUTTONS: Final[tuple[SonyVplButtonDescription, ...]] = (
    # Driving the on-screen menu.
    _button("menu"),
    _button("up"),
    _button("down"),
    _button("left"),
    _button("right"),
    _button("enter"),
    # Lens adjustment. The VW270ES lens is motorised, and these are the commands
    # that are genuinely awkward to use as typed strings, because setting up a
    # picture means nudging them dozens of times.
    _button("lens_focus_near", config=True),
    _button("lens_focus_far", config=True),
    _button("lens_zoom_large", config=True),
    _button("lens_zoom_small", config=True),
    _button("lens_shift_up", config=True),
    _button("lens_shift_down", config=True),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: SonyVplConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the Sony VPL projector buttons."""
    async_add_entities(
        SonyVplButton(entry.runtime_data.status, description) for description in BUTTONS
    )


class SonyVplButton(SonyVplEntity, ButtonEntity):
    """One infrared command as a button."""

    entity_description: SonyVplButtonDescription

    def __init__(
        self,
        coordinator: SonyVplStatusCoordinator,
        description: SonyVplButtonDescription,
    ) -> None:
        """Initialize the button."""
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_translation_key = description.key
        entry = coordinator.config_entry
        self._attr_unique_id = f"{entry.unique_id or entry.entry_id}_{description.key}"

    @override
    async def async_press(self) -> None:
        """Send the command."""
        name = self.entity_description.command
        try:
            await self.coordinator.client.async_send_ir(IR_COMMANDS[name])
        except SdcpError as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="command_failed",
                translation_placeholders={"command": name},
            ) from err
