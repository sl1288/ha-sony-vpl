"""SDCP ("PJ Talk") client for Sony VPL video projectors.

This module deliberately has no Home Assistant imports and no knowledge of the
item table, so it can be unit tested on its own and reused for another model.

Packet layout, from the VPL-VW320/VW520 protocol manual and confirmed byte for
byte against pysdcp::

    request   VERSION(1)=0x02  CATEGORY(1)=0x0A  COMMUNITY(4)
              REQUEST(1)       ITEM_NO(2 BE)     DATA_LEN(1)  DATA(n)
    response  VERSION(1)       CATEGORY(1)       COMMUNITY(4)
              RESPONSE(1)      ITEM_NO(2 BE)     DATA_LEN(1)  DATA(n)

A GET request carries no data, so it is 10 bytes; a SET carries two big endian
bytes, so it is 12. A response to an OK GET carries the value, a response to an
OK SET carries nothing, and an NG response carries a two byte error code.
"""

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress
from dataclasses import dataclass
from enum import IntEnum
import logging
from typing import Final

_LOGGER = logging.getLogger(__name__)

DEFAULT_PORT: Final = 53484
DEFAULT_COMMUNITY: Final = "SONY"
DEFAULT_TIMEOUT: Final = 5.0

# PJ Talk closes a TCP connection that has been idle for 30 seconds. Reopening
# slightly before that is the difference between a clean handshake and reading an
# EOF from a socket the projector has already dropped, so a caller that holds a
# connection open across something slow never has to think about it.
IDLE_REOPEN_AFTER: Final = 25.0

PROTOCOL_VERSION: Final = 0x02
CATEGORY_PROJECTOR: Final = 0x0A
COMMUNITY_LENGTH: Final = 4

# Header (2) + community (4) + response (1) + item (2) + data length (1).
PREFIX_LENGTH: Final = 10

# Infrared emulation items are SET only, with two zero data bytes as the manual
# shows. VERIFIED on a VPL-VW270ES: this twelve byte form is accepted and acts on
# the projector, so the ten byte form pysdcp sends is not what this generation
# wants.
IR_SET_VALUE: Final[int | None] = 0x0000


class Request(IntEnum):
    """Request kinds, sent in the first byte of the command field."""

    SET = 0x00
    GET = 0x01


class Response(IntEnum):
    """Response kinds, returned in the first byte of the command field."""

    NG = 0x00
    OK = 0x01


# Item errors, category 0x01.
ERR_INVALID_ITEM: Final = 0x0101
ERR_INVALID_ITEM_REQUEST: Final = 0x0102
ERR_INVALID_LENGTH: Final = 0x0103
ERR_INVALID_DATA: Final = 0x0104
ERR_SHORT_DATA: Final = 0x0111
ERR_NOT_APPLICABLE: Final = 0x0180

# An item the projector does not implement at all, as opposed to one that is
# merely irrelevant right now.
ERRORS_UNSUPPORTED: Final = frozenset({ERR_INVALID_ITEM, ERR_INVALID_ITEM_REQUEST})


class SdcpError(Exception):
    """Base error for the SDCP client."""


class SdcpConnectionError(SdcpError):
    """Raised when the projector is unreachable or drops the connection."""


class SdcpProtocolError(SdcpError):
    """Raised when the reply is not a well formed SDCP packet for our request."""


class SdcpNgError(SdcpError):
    """Raised when the projector answers NG. Carries the 16 bit error code."""

    def __init__(self, code: int, item: int) -> None:
        """Initialize the error."""
        super().__init__(f"Item 0x{item:04X} was rejected with error 0x{code:04X}")
        self.code = code
        self.item = item


class SdcpItemError(SdcpNgError):
    """Raised for 0x01xx: the item is unknown, not applicable, or the data was bad."""


class SdcpCommunityError(SdcpNgError):
    """Raised for 0x02xx: the projector rejected the community string."""


class SdcpDeviceError(SdcpNgError):
    """Raised for 0x10xx, 0x20xx, 0xF0xx and 0xF1xx: a fault inside the projector."""


def _ng_error(code: int, item: int) -> SdcpNgError:
    """Map a 16 bit NG error code onto the matching exception class."""
    match code >> 8:
        case 0x01:
            return SdcpItemError(code, item)
        case 0x02:
            return SdcpCommunityError(code, item)
        case _:
            return SdcpDeviceError(code, item)


@dataclass(frozen=True, kw_only=True, slots=True)
class ResponseHeader:
    """The fixed length part of a response, before the data field."""

    ok: bool
    item: int
    data_length: int


def encode_community(community: str) -> bytes:
    """Return the community as exactly four ASCII bytes.

    Raises ValueError if it is not four ASCII characters. UnicodeEncodeError is
    itself a ValueError, so a single ``except ValueError`` covers both cases.
    """
    encoded = community.encode("ascii")
    if len(encoded) != COMMUNITY_LENGTH:
        raise ValueError(
            f"Community must be exactly {COMMUNITY_LENGTH} characters, "
            f"got {len(encoded)}"
        )
    return encoded


def build_request(
    request: Request, item: int, value: int | None, community: bytes
) -> bytes:
    """Build a request packet."""
    data = b"" if value is None else value.to_bytes(2, "big")
    return (
        bytes((PROTOCOL_VERSION, CATEGORY_PROJECTOR))
        + community
        + bytes((request,))
        + item.to_bytes(2, "big")
        + bytes((len(data),))
        + data
    )


def parse_response_header(prefix: bytes) -> ResponseHeader:
    """Parse the fixed length part of a response.

    A mismatched version or category is only warned about, because it is
    cosmetic. A real stream desynchronisation is caught by the item check in
    ``check_response``, which is where returning the wrong value for the wrong
    entity would actually do harm.
    """
    if len(prefix) != PREFIX_LENGTH:
        raise SdcpProtocolError(
            f"Response header is {len(prefix)} bytes, expected {PREFIX_LENGTH}"
        )
    if prefix[0] != PROTOCOL_VERSION or prefix[1] != CATEGORY_PROJECTOR:
        _LOGGER.warning(
            "Unexpected response header version 0x%02X category 0x%02X",
            prefix[0],
            prefix[1],
        )
    return ResponseHeader(
        ok=prefix[6] == Response.OK,
        item=int.from_bytes(prefix[7:9], "big"),
        data_length=prefix[9],
    )


def check_response(header: ResponseHeader, data: bytes, expected_item: int) -> bytes:
    """Validate a response against the item it should answer, and return its data."""
    if not header.ok:
        # The manual specifies a two byte error code. Be lenient about the length
        # so a firmware quirk surfaces as a protocol error rather than an
        # IndexError.
        if len(data) < 2:
            raise SdcpProtocolError(
                f"Item 0x{expected_item:04X} was rejected without an error code"
            )
        raise _ng_error(int.from_bytes(data[:2], "big"), expected_item)
    if header.item != expected_item:
        raise SdcpProtocolError(
            f"Response is for item 0x{header.item:04X}, expected "
            f"0x{expected_item:04X}; the connection is out of sync"
        )
    return data


class SdcpClient:
    """Talk to a Sony VPL projector over SDCP.

    One TCP connection is used per burst of commands rather than one per command
    or one held open forever. The projector closes an idle connection after 30
    seconds and accepts only one at a time, so a permanently open socket would
    race its own close on nearly every poll, while a connection per command turns
    a twelve item poll into twelve handshakes on a small embedded stack.
    """

    def __init__(
        self,
        *,
        host: str,
        port: int = DEFAULT_PORT,
        community: str = DEFAULT_COMMUNITY,
        timeout: float = DEFAULT_TIMEOUT,
        idle_timeout: float = IDLE_REOPEN_AFTER,
    ) -> None:
        """Initialize the client."""
        self._host = host
        self._port = port
        self._community = encode_community(community)
        self._timeout = timeout
        self._idle_timeout = idle_timeout
        # Every round trip takes this lock, because the projector accepts one
        # command at a time. The lock is held per round trip and never for a
        # whole poll cycle, so a user action waits for at most one reply.
        self._lock = asyncio.Lock()
        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None
        self._holders = 0
        self._unsupported: set[int] = set()
        self._last_used = 0.0
        self._tainted = False

    @property
    def host(self) -> str:
        """Return the projector's host."""
        return self._host

    @property
    def unsupported_items(self) -> frozenset[int]:
        """Return the items this projector answered "invalid item" for."""
        return frozenset(self._unsupported)

    @asynccontextmanager
    async def connection(self) -> AsyncIterator[None]:
        """Reuse one TCP connection for every command sent inside this block.

        Nestable by reference count, so a user action arriving while a poll cycle
        is in progress joins the open connection instead of trying to open a
        second one. Opening stays lazy and happens under the lock; this only
        keeps the socket from being closed between commands.
        """
        self._holders += 1
        try:
            yield
        finally:
            self._holders -= 1
            if not self._holders:
                await self.async_close()

    async def async_close(self) -> None:
        """Close the connection if one is open."""
        writer, self._writer, self._reader = self._writer, None, None
        if writer is None:
            return
        writer.close()
        # The projector may already be gone, in which case waiting for the close
        # handshake fails. There is nothing useful to do about that here, and
        # TimeoutError is itself an OSError.
        with suppress(OSError):
            await writer.wait_closed()

    def _is_stale(self) -> bool:
        """Return True when the open connection has been idle too long to trust.

        Checked before sending rather than after failing, because a socket the
        projector has already closed accepts the write and then returns an EOF,
        which is indistinguishable from the command having been lost. Reopening
        first means no command is ever sent twice.
        """
        return (
            self._idle_timeout > 0
            and asyncio.get_running_loop().time() - self._last_used > self._idle_timeout
        )

    async def _async_connect(
        self, *, for_read: bool = True
    ) -> tuple[asyncio.StreamReader, asyncio.StreamWriter]:
        """Return a live connection, opening one if needed.

        ``for_read`` is False for infrared commands, which write and never read.
        A connection an infrared command was written on is only dangerous for a
        *read*, since a reply some firmware volunteered would be taken for the
        answer to that read. Writing another infrared command on it is harmless,
        so a burst of keypresses stays on one connection.
        """
        if (
            self._reader is not None
            and self._writer is not None
            and not self._writer.is_closing()
        ):
            tainted = for_read and self._tainted
            if not self._is_stale() and not tainted:
                return self._reader, self._writer
            _LOGGER.debug(
                "Reopening the connection: %s",
                "an infrared command was written on it"
                if tainted
                else f"idle for more than {self._idle_timeout:.0f}s",
            )

        await self.async_close()
        try:
            async with asyncio.timeout(self._timeout):
                self._reader, self._writer = await asyncio.open_connection(
                    self._host, self._port
                )
        except OSError as err:
            raise SdcpConnectionError(
                f"Could not connect to {self._host}:{self._port}: {err}"
            ) from err
        self._last_used = asyncio.get_running_loop().time()
        self._tainted = False
        return self._reader, self._writer

    async def _async_round_trip(
        self, request: Request, item: int, value: int | None
    ) -> bytes:
        """Send one command and read its reply. Assumes the lock is held."""
        reader, writer = await self._async_connect()

        try:
            async with asyncio.timeout(self._timeout):
                writer.write(build_request(request, item, value, self._community))
                await writer.drain()
                header = parse_response_header(await reader.readexactly(PREFIX_LENGTH))
                data = (
                    await reader.readexactly(header.data_length)
                    if header.data_length
                    else b""
                )
        except (OSError, asyncio.IncompleteReadError) as err:
            await self.async_close()
            raise SdcpConnectionError(
                f"Lost the connection to {self._host} while reading item "
                f"0x{item:04X}: {err}"
            ) from err
        except SdcpProtocolError:
            # The stream is no longer aligned to packet boundaries, so anything
            # read after this would be garbage.
            await self.async_close()
            raise

        self._last_used = asyncio.get_running_loop().time()
        try:
            return check_response(header, data, item)
        except SdcpProtocolError:
            await self.async_close()
            raise

    async def _async_send(
        self,
        request: Request,
        item: int,
        value: int | None = None,
        *,
        retry: bool = False,
    ) -> bytes:
        """Send one command, resending it once after a dropped connection if asked."""
        async with self.connection(), self._lock:
            try:
                return await self._async_round_trip(request, item, value)
            except SdcpConnectionError:
                if not retry:
                    raise
            # With "Network management" off the projector drops the first packet
            # that wakes its Ethernet interface, so the documented remedy is to
            # send the command a second time. Only idempotent commands get here.
            _LOGGER.debug("Resending item 0x%04X after a dropped connection", item)
            return await self._async_round_trip(request, item, value)

    async def async_get_raw(self, item: int, *, retry: bool = False) -> bytes:
        """Read an item and return its raw data, which may be any length."""
        return await self._async_send(Request.GET, item, None, retry=retry)

    async def async_get_value(self, item: int, *, retry: bool = False) -> int:
        """Read a two byte item and return it as an integer."""
        raw = await self.async_get_raw(item, retry=retry)
        if len(raw) != 2:
            raise SdcpProtocolError(
                f"Item 0x{item:04X} returned {len(raw)} bytes, expected 2"
            )
        return int.from_bytes(raw, "big")

    def _note_if_unsupported(self, err: SdcpItemError, item: int) -> None:
        """Remember an item the projector does not implement."""
        if err.code in ERRORS_UNSUPPORTED:
            _LOGGER.info(
                "Projector does not support item 0x%04X, not asking again", item
            )
            self._unsupported.add(item)
        else:
            _LOGGER.debug("Item 0x%04X is not applicable right now", item)

    async def async_try_get(self, item: int) -> int | None:
        """Read a two byte item, returning None when the projector will not answer.

        Two NG codes are normal rather than exceptional:

        - "not applicable" means the setting does not apply while the lamp is off
          or with the current input or signal. The caller should report that
          entity as unavailable.
        - "invalid item" means this projector does not implement the item at all.
          It is remembered and never requested again, which is what makes an
          unverified item number cheap to be wrong about.
        """
        if item in self._unsupported:
            return None
        try:
            return await self.async_get_value(item)
        except SdcpItemError as err:
            self._note_if_unsupported(err, item)
            return None

    async def async_try_get_raw(self, item: int) -> bytes | None:
        """Read a variable length item, returning None when it is unsupported."""
        if item in self._unsupported:
            return None
        try:
            return await self.async_get_raw(item)
        except SdcpItemError as err:
            self._note_if_unsupported(err, item)
            return None

    async def async_set_value(
        self, item: int, value: int, *, retry: bool = False
    ) -> None:
        """Write a two byte item."""
        await self._async_send(Request.SET, item, value, retry=retry)

    async def async_send_ir(self, item: int) -> None:
        """Replay an infrared remote code, without waiting for a reply.

        The projector does not answer these. The manual says so for the serial
        transport, "when Infrared Remote Command is sent, return data is not sent",
        and it was confirmed to hold over SDCP too on a VPL-VW270ES: the command
        takes effect but nothing comes back. Waiting would therefore stall for the
        whole command timeout on every keypress and then report a failure that did
        not happen.

        Two consequences follow. The command is never retried, because these are
        relative actions and resending "cursor right" after an ambiguous failure
        would move the cursor twice. And the connection is marked so that it is not
        reused for a read: if some firmware did volunteer a reply, it would
        otherwise be mistaken for the answer to whatever command came next.

        A failure to write is still raised. What cannot be detected is the
        projector rejecting the code itself, since that rejection is exactly the
        reply it does not send. Callers must leave at least IR_COMMAND_INTERVAL
        between two of these; without a round trip there is nothing else pacing
        them.
        """
        async with self.connection(), self._lock:
            _, writer = await self._async_connect(for_read=False)
            try:
                async with asyncio.timeout(self._timeout):
                    writer.write(
                        build_request(Request.SET, item, IR_SET_VALUE, self._community)
                    )
                    await writer.drain()
            except OSError as err:
                await self.async_close()
                raise SdcpConnectionError(
                    f"Could not send infrared item 0x{item:04X} to {self._host}: {err}"
                ) from err
            self._tainted = True
