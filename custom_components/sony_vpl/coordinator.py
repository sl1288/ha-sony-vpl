"""Coordinators for the Sony VPL projector integration."""

from collections import deque
from collections.abc import Collection, Mapping
from dataclasses import dataclass, field
from datetime import timedelta
import itertools
import logging
from typing import Final, override

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, CONF_PORT
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.debounce import Debouncer
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import SdcpClient, SdcpCommunityError, SdcpError, SdcpProtocolError
from .const import (
    CONF_COMMAND_TIMEOUT,
    CONF_COMMUNITY,
    CONF_SCAN_INTERVAL_ON,
    CONF_SCAN_INTERVAL_SETTINGS,
    CONF_SCAN_INTERVAL_STANDBY,
    DEFAULT_COMMAND_TIMEOUT,
    DEFAULT_SCAN_INTERVAL_ON,
    DEFAULT_SCAN_INTERVAL_SETTINGS,
    DEFAULT_SCAN_INTERVAL_STANDBY,
    DOMAIN,
    INTERVAL_TRANSITION,
    MAX_ITEMS_PER_CYCLE,
)
from .helpers import SonyVplIdentity, async_get_identity
from .items import (
    ERROR2_FLAGS,
    ERROR_FLAGS,
    ITEM_INPUT,
    ITEM_LAMP_TIMER,
    ITEM_SET_POWER,
    ITEM_STATUS_ERROR,
    ITEM_STATUS_ERROR2,
    ITEM_STATUS_POWER,
    POWER_SET_OFF,
    POWER_SET_ON,
    POWER_STATUS_ON,
    POWER_STATUS_TRANSITIONAL,
    PowerStatus,
    decode_flags,
    power_status,
)

_LOGGER = logging.getLogger(__name__)

# Items the fast status coordinator reads for entities, so that the input select
# and the lamp hours sensor do not have to wait for the slow settings cycle. The
# settings coordinator subtracts these, so nothing is polled twice.
STATUS_ITEMS: Final = frozenset({ITEM_INPUT, ITEM_LAMP_TIMER})

# Lamp hours only ever increase and cannot be read while the lamp is off, so the
# last known value is carried across power cycles. Without this the long term
# statistics of a total_increasing sensor would show a gap every night. The input
# is deliberately not retained: a stale HDMI reading on a projector that is off
# would suggest a selection that is not actually in effect.
STATUS_RETAINED_ITEMS: Final = frozenset({ITEM_LAMP_TIMER})

# After a write the projector needs a moment before it reports the new value, so
# a read back must not be immediate. The cooldown also collapses the flood of
# refresh requests produced by dragging a number slider.
_DEBOUNCE_COOLDOWN: Final = 2.0


type SonyVplConfigEntry = ConfigEntry[SonyVplRuntimeData]


@dataclass(kw_only=True, slots=True)
class SonyVplRuntimeData:
    """Objects shared by every platform of one config entry."""

    client: SdcpClient
    status: SonyVplStatusCoordinator
    settings: SonyVplSettingsCoordinator


@dataclass(frozen=True, kw_only=True, slots=True)
class SonyVplStatus:
    """Result of one status poll."""

    power: PowerStatus | None = None
    errors: list[str] = field(default_factory=list)
    items: Mapping[int, int] = field(default_factory=dict)

    @property
    def is_on(self) -> bool:
        """Return True while the lamp is on or coming on."""
        return self.power in POWER_STATUS_ON


def next_batch(queue: deque[int], wanted: Collection[int], limit: int) -> list[int]:
    """Return up to ``limit`` items to read, least recently read first.

    Mutates ``queue`` so that the returned items move to the back, giving a plain
    round robin. Kept a module level function of its arguments alone so the poll
    scheduling can be unit tested without a Home Assistant instance.
    """
    queue.extend(item for item in wanted if item not in queue)
    for stale in [item for item in queue if item not in wanted]:
        queue.remove(stale)
    size = min(limit, len(queue))
    batch = list(itertools.islice(queue, size))
    queue.rotate(-size)
    return batch


def build_client(entry: SonyVplConfigEntry) -> SdcpClient:
    """Create a client from a config entry's data and options."""
    return SdcpClient(
        host=entry.data[CONF_HOST],
        port=entry.data[CONF_PORT],
        community=entry.data[CONF_COMMUNITY],
        timeout=entry.options.get(CONF_COMMAND_TIMEOUT, DEFAULT_COMMAND_TIMEOUT),
    )


class SonyVplStatusCoordinator(DataUpdateCoordinator[SonyVplStatus]):
    """Poll the handful of items every installation needs."""

    config_entry: SonyVplConfigEntry

    def __init__(
        self, hass: HomeAssistant, entry: SonyVplConfigEntry, client: SdcpClient
    ) -> None:
        """Initialize the status coordinator."""
        options = entry.options
        self._interval_on = timedelta(
            seconds=options.get(CONF_SCAN_INTERVAL_ON, DEFAULT_SCAN_INTERVAL_ON)
        )
        self._interval_standby = timedelta(
            seconds=options.get(
                CONF_SCAN_INTERVAL_STANDBY, DEFAULT_SCAN_INTERVAL_STANDBY
            )
        )
        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN} status",
            config_entry=entry,
            update_interval=self._interval_standby,
            request_refresh_debouncer=Debouncer(
                hass, _LOGGER, cooldown=_DEBOUNCE_COOLDOWN, immediate=False
            ),
        )
        self.client = client
        self.identity = SonyVplIdentity()
        self._retained: dict[int, int] = {}

    @override
    async def _async_setup(self) -> None:
        """Read the identity items once; they cannot change at runtime."""
        try:
            self.identity = await async_get_identity(self.client)
        except SdcpError as err:
            raise UpdateFailed(
                translation_domain=DOMAIN, translation_key="connection_failed"
            ) from err

    @override
    async def _async_update_data(self) -> SonyVplStatus:
        """Read power, faults and, while the lamp is on, lamp hours and input."""
        try:
            async with self.client.connection():
                # retry=True only here and for the power write: with "Network
                # management" off, this is the packet that has to wake the
                # projector's Ethernet interface.
                power = power_status(
                    await self.client.async_get_value(ITEM_STATUS_POWER, retry=True)
                )
                errors = decode_flags(
                    await self.client.async_try_get(ITEM_STATUS_ERROR) or 0, ERROR_FLAGS
                )
                errors += decode_flags(
                    await self.client.async_try_get(ITEM_STATUS_ERROR2) or 0,
                    ERROR2_FLAGS,
                )
                items: dict[int, int] = {}
                if power in POWER_STATUS_ON:
                    for item in STATUS_ITEMS:
                        if (value := await self.client.async_try_get(item)) is not None:
                            items[item] = value
        except SdcpCommunityError as err:
            raise ConfigEntryAuthFailed(
                translation_domain=DOMAIN, translation_key="invalid_community"
            ) from err
        except SdcpProtocolError as err:
            raise UpdateFailed(
                translation_domain=DOMAIN, translation_key="unexpected_response"
            ) from err
        except SdcpError as err:
            raise UpdateFailed(
                translation_domain=DOMAIN, translation_key="connection_failed"
            ) from err

        self._retained.update(
            (item, value)
            for item, value in items.items()
            if item in STATUS_RETAINED_ITEMS
        )
        self.update_interval = (
            INTERVAL_TRANSITION
            if power in POWER_STATUS_TRANSITIONAL
            else self._interval_on
            if power is PowerStatus.POWER_ON
            else self._interval_standby
        )
        return SonyVplStatus(
            power=power, errors=sorted(errors), items={**self._retained, **items}
        )

    async def async_set_power(self, on: bool) -> None:
        """Turn the projector on or off.

        The power item is set only; the state always comes back through the
        separate status item.
        """
        await self.client.async_set_value(
            ITEM_SET_POWER, POWER_SET_ON if on else POWER_SET_OFF, retry=True
        )
        await self.async_request_refresh()


class SonyVplSettingsCoordinator(DataUpdateCoordinator[dict[int, int]]):
    """Read only the setting items whose entity is actually enabled.

    Every setting entity subscribes with its SDCP item number as the coordinator
    context, so ``async_contexts()`` is exactly the set of items somebody is
    looking at. Tuning entities are disabled in the registry by default, and a
    disabled entity is never added to Home Assistant, so it registers no listener
    and its item is never requested. A stock installation performs no input or
    output here at all, and the interval is not even scheduled until the first
    entity is enabled.
    """

    config_entry: SonyVplConfigEntry

    def __init__(
        self,
        hass: HomeAssistant,
        entry: SonyVplConfigEntry,
        client: SdcpClient,
        status: SonyVplStatusCoordinator,
    ) -> None:
        """Initialize the settings coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN} settings",
            config_entry=entry,
            update_interval=timedelta(
                seconds=entry.options.get(
                    CONF_SCAN_INTERVAL_SETTINGS, DEFAULT_SCAN_INTERVAL_SETTINGS
                )
            ),
            request_refresh_debouncer=Debouncer(
                hass, _LOGGER, cooldown=_DEBOUNCE_COOLDOWN, immediate=False
            ),
            # Settings only change when somebody touches the physical remote, so
            # do not write every entity's state out on every cycle.
            always_update=False,
        )
        self.client = client
        self._status = status
        self._queue: deque[int] = deque()
        # There is no first refresh for this coordinator: with nothing enabled
        # there would be nothing to read, and it must never be able to fail the
        # config entry setup.
        self.data = {}

    @override
    async def _async_update_data(self) -> dict[int, int]:
        """Read one bounded batch of the enabled setting items."""
        data = dict(self.data)
        # Items the status coordinator already covers are subtracted so that an
        # entity backed by one of them is not polled twice.
        wanted = set(self.async_contexts()) - STATUS_ITEMS

        # Every setting answers "not applicable" while the lamp is off, so there
        # is nothing to learn from asking.
        if not wanted or not self._status.data.is_on:
            return data

        try:
            async with self.client.connection():
                for item in next_batch(self._queue, wanted, MAX_ITEMS_PER_CYCLE):
                    if (value := await self.client.async_try_get(item)) is None:
                        # Not applicable to the current input or signal, so drop
                        # it: the entity should report unavailable rather than a
                        # stale value.
                        data.pop(item, None)
                    else:
                        data[item] = value
        except SdcpError as err:
            # The status coordinator owns availability. A failed settings read
            # must not take the whole device offline.
            _LOGGER.debug("Settings poll aborted: %s", err)

        return data

    async def async_write(self, item: int, value: int) -> None:
        """Write one setting and schedule a read back.

        Raising is left to the caller, which knows the entity name to put in the
        message. The new value is shown at once so the control does not visibly
        bounce back to the old one while the debounced read back is pending.
        """
        await self.client.async_set_value(item, value)
        self.data[item] = value
        self.async_update_listeners()
        await self.async_request_refresh()
