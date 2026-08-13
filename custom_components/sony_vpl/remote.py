"""Remote platform for the Sony VPL projector integration."""

import asyncio
from collections.abc import Iterable
import logging
from typing import Any, override

import voluptuous as vol

from homeassistant.components.remote import (
    ATTR_COMMAND,
    ATTR_DELAY_SECS,
    ATTR_NUM_REPEATS,
    DEFAULT_DELAY_SECS,
    DEFAULT_NUM_REPEATS,
    RemoteEntity,
)
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import config_validation as cv, entity_platform
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .api import SdcpError
from .const import DOMAIN
from .coordinator import SonyVplConfigEntry, SonyVplStatusCoordinator
from .entity import SonyVplEntity
from .items import IR_COMMAND_INTERVAL, IR_COMMANDS

_LOGGER = logging.getLogger(__name__)

PARALLEL_UPDATES = 0

SERVICE_SEND_COMMAND = "send_command"
ATTR_IR_COMMANDS = "ir_commands"


async def async_setup_entry(
    hass: HomeAssistant,
    entry: SonyVplConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the Sony VPL projector remote."""
    # Alongside the standard remote.send_command, which takes free text. This one
    # declares the command list in services.yaml, so the interface can offer a
    # searchable dropdown of every code instead of asking the user to remember
    # them. Both end up in async_send_command.
    entity_platform.async_get_current_platform().async_register_entity_service(
        SERVICE_SEND_COMMAND,
        {
            vol.Required(ATTR_COMMAND): vol.All(cv.ensure_list, [vol.In(IR_COMMANDS)]),
            vol.Optional(
                ATTR_NUM_REPEATS, default=DEFAULT_NUM_REPEATS
            ): cv.positive_int,
            vol.Optional(ATTR_DELAY_SECS, default=DEFAULT_DELAY_SECS): vol.Coerce(
                float
            ),
        },
        "async_send_command",
    )

    async_add_entities([SonyVplRemote(entry.runtime_data.status)])


class SonyVplRemote(SonyVplEntity, RemoteEntity):
    """The projector itself: power, plus its infrared command set."""

    _attr_name = None

    def __init__(self, coordinator: SonyVplStatusCoordinator) -> None:
        """Initialize the remote."""
        super().__init__(coordinator)
        entry = coordinator.config_entry
        self._attr_unique_id = entry.unique_id or entry.entry_id

    @property
    @override
    def is_on(self) -> bool:
        """Return True while the lamp is on or coming on.

        Cooling counts as off, matching what pysdcp has reported against real Sony
        projectors for years by way of the built-in sony_projector integration.
        """
        return self.coordinator.data.is_on

    @property
    @override
    def extra_state_attributes(self) -> dict[str, Any]:
        """Expose every command this remote accepts.

        So that the codes are discoverable from the developer tools and usable from
        a template, without having to read the source or the documentation.
        """
        return {ATTR_IR_COMMANDS: sorted(IR_COMMANDS)}

    @override
    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn the projector on."""
        try:
            await self.coordinator.async_set_power(True)
        except SdcpError as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN, translation_key="turn_on_failed"
            ) from err

    @override
    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn the projector off."""
        try:
            await self.coordinator.async_set_power(False)
        except SdcpError as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN, translation_key="turn_off_failed"
            ) from err

    @override
    async def async_send_command(self, command: Iterable[str], **kwargs: Any) -> None:
        """Replay one or more infrared remote codes."""
        commands = list(command)
        if unknown := [name for name in commands if name not in IR_COMMANDS]:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="unknown_command",
                translation_placeholders={"command": ", ".join(sorted(unknown))},
            )

        repeats: int = kwargs.get(ATTR_NUM_REPEATS, DEFAULT_NUM_REPEATS)
        delay: float = kwargs.get(ATTR_DELAY_SECS, DEFAULT_DELAY_SECS)
        # The manual requires at least 45 ms between two infrared commands, so a
        # shorter requested delay is raised to that floor rather than ignored.
        delay = max(delay, IR_COMMAND_INTERVAL)

        # One connection for the whole burst instead of one per keypress.
        async with self.coordinator.client.connection():
            for index, name in enumerate(commands * repeats):
                if index:
                    await asyncio.sleep(delay)
                _LOGGER.debug("Sending infrared command %s", name)
                try:
                    await self.coordinator.client.async_send_ir(IR_COMMANDS[name])
                except SdcpError as err:
                    raise HomeAssistantError(
                        translation_domain=DOMAIN,
                        translation_key="command_failed",
                        translation_placeholders={"command": name},
                    ) from err

        await self.coordinator.async_request_refresh()
