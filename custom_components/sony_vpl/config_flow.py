"""Config flow for the Sony VPL projector integration."""

from collections.abc import Mapping
import logging
from typing import Any, override

import voluptuous as vol

from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlowWithReload,
)
from homeassistant.const import CONF_HOST, CONF_PORT
from homeassistant.core import callback
from homeassistant.helpers.selector import (
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
)

from .api import (
    DEFAULT_COMMUNITY,
    DEFAULT_PORT,
    SdcpClient,
    SdcpCommunityError,
    SdcpError,
)
from .const import (
    CONF_COMMAND_TIMEOUT,
    CONF_COMMUNITY,
    CONF_SCAN_INTERVAL_ON,
    CONF_SCAN_INTERVAL_SETTINGS,
    CONF_SCAN_INTERVAL_STANDBY,
    DEFAULT_COMMAND_TIMEOUT,
    DEFAULT_MODEL,
    DEFAULT_SCAN_INTERVAL_ON,
    DEFAULT_SCAN_INTERVAL_SETTINGS,
    DEFAULT_SCAN_INTERVAL_STANDBY,
    DOMAIN,
)
from .helpers import SonyVplIdentity, async_get_identity
from .items import ITEM_STATUS_POWER

_LOGGER = logging.getLogger(__name__)

STEP_USER_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_HOST): str,
        vol.Required(CONF_PORT, default=DEFAULT_PORT): vol.Coerce(int),
        vol.Required(CONF_COMMUNITY, default=DEFAULT_COMMUNITY): str,
    }
)
STEP_REAUTH_DATA_SCHEMA = vol.Schema(
    {vol.Required(CONF_COMMUNITY, default=DEFAULT_COMMUNITY): str}
)


def _seconds(minimum: int, maximum: int) -> NumberSelector:
    """Build a seconds selector for the options flow."""
    return NumberSelector(
        NumberSelectorConfig(
            min=minimum,
            max=maximum,
            step=1,
            mode=NumberSelectorMode.BOX,
            unit_of_measurement="s",
        )
    )


async def _async_validate(data: Mapping[str, Any]) -> SonyVplIdentity:
    """Check the connection details and read back the projector's identity."""
    client = SdcpClient(
        host=data[CONF_HOST],
        port=data[CONF_PORT],
        community=data[CONF_COMMUNITY],
    )
    try:
        async with client.connection():
            # retry=True because with "Network management" off the projector drops
            # the first packet that wakes its Ethernet interface.
            await client.async_get_value(ITEM_STATUS_POWER, retry=True)
            return await async_get_identity(client)
    finally:
        await client.async_close()


class SonyVplConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for a Sony VPL projector."""

    VERSION = 1
    MINOR_VERSION = 1

    @staticmethod
    @callback
    @override
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlowWithReload:
        """Return the options flow handler."""
        return SonyVplOptionsFlow()

    async def _async_try(
        self, user_input: Mapping[str, Any], errors: dict[str, str]
    ) -> SonyVplIdentity | None:
        """Validate user input, filling in ``errors`` on failure."""
        try:
            return await _async_validate(user_input)
        except SdcpCommunityError, ValueError:
            # ValueError covers a community that is not four ASCII characters,
            # which the client rejects before it opens a connection.
            errors["base"] = "invalid_community"
        except SdcpError:
            errors["base"] = "cannot_connect"
        except Exception:
            _LOGGER.exception("Unexpected exception")
            errors["base"] = "unknown"
        return None

    @override
    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle the initial step."""
        errors: dict[str, str] = {}

        if user_input is not None:
            self._async_abort_entries_match({CONF_HOST: user_input[CONF_HOST]})
            if (identity := await self._async_try(user_input, errors)) is not None:
                if unique_id := identity.unique_id:
                    await self.async_set_unique_id(unique_id)
                    self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title=identity.model or DEFAULT_MODEL, data=user_input
                )

        return self.async_show_form(
            step_id="user",
            data_schema=self.add_suggested_values_to_schema(
                STEP_USER_DATA_SCHEMA, user_input
            ),
            errors=errors,
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle reconfiguration, typically after the projector changed address."""
        entry = self._get_reconfigure_entry()
        errors: dict[str, str] = {}

        if user_input is not None:
            if user_input[CONF_HOST] != entry.data[CONF_HOST]:
                self._async_abort_entries_match({CONF_HOST: user_input[CONF_HOST]})
            if (identity := await self._async_try(user_input, errors)) is not None:
                if unique_id := identity.unique_id:
                    await self.async_set_unique_id(unique_id)
                    self._abort_if_unique_id_mismatch(reason="different_device")
                return self.async_update_reload_and_abort(
                    entry,
                    data_updates=user_input,
                    title=identity.model or DEFAULT_MODEL,
                )

        return self.async_show_form(
            step_id="reconfigure",
            data_schema=self.add_suggested_values_to_schema(
                STEP_USER_DATA_SCHEMA, user_input or entry.data
            ),
            errors=errors,
        )

    async def async_step_reauth(
        self, entry_data: Mapping[str, Any]
    ) -> ConfigFlowResult:
        """Handle a rejected community string."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask for the current community string."""
        entry = self._get_reauth_entry()
        errors: dict[str, str] = {}

        if user_input is not None:
            if await self._async_try({**entry.data, **user_input}, errors) is not None:
                return self.async_update_reload_and_abort(
                    entry, data_updates=user_input
                )

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=self.add_suggested_values_to_schema(
                STEP_REAUTH_DATA_SCHEMA, user_input
            ),
            description_placeholders={CONF_HOST: entry.data[CONF_HOST]},
            errors=errors,
        )


class SonyVplOptionsFlow(OptionsFlowWithReload):
    """Handle the runtime options.

    OptionsFlowWithReload reloads the config entry when these change, so the
    coordinators are rebuilt with the new intervals without a restart.
    """

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Manage the options."""
        if user_input is not None:
            return self.async_create_entry(
                data={key: int(value) for key, value in user_input.items()}
            )

        options = self.config_entry.options
        schema = vol.Schema(
            {
                vol.Required(
                    CONF_SCAN_INTERVAL_ON,
                    default=options.get(
                        CONF_SCAN_INTERVAL_ON, DEFAULT_SCAN_INTERVAL_ON
                    ),
                ): _seconds(5, 300),
                vol.Required(
                    CONF_SCAN_INTERVAL_STANDBY,
                    default=options.get(
                        CONF_SCAN_INTERVAL_STANDBY, DEFAULT_SCAN_INTERVAL_STANDBY
                    ),
                ): _seconds(10, 900),
                vol.Required(
                    CONF_SCAN_INTERVAL_SETTINGS,
                    default=options.get(
                        CONF_SCAN_INTERVAL_SETTINGS, DEFAULT_SCAN_INTERVAL_SETTINGS
                    ),
                ): _seconds(30, 3600),
                vol.Required(
                    CONF_COMMAND_TIMEOUT,
                    default=options.get(CONF_COMMAND_TIMEOUT, DEFAULT_COMMAND_TIMEOUT),
                ): _seconds(2, 30),
            }
        )
        return self.async_show_form(step_id="init", data_schema=schema)
