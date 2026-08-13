"""Tests for the SDCP client against a real socket.

A genuine ``asyncio`` server on loopback is used rather than a patched
``open_connection``, because the things most likely to break in a binary protocol
client are exactly the ones a mock cannot reach: framing across two reads, a reply
split over two segments, end of file mid packet, the reconnect path, and whether
the lock really stops two commands overlapping.
"""

import asyncio
from collections.abc import AsyncIterator
from contextlib import suppress
from typing import Self

from custom_components.sony_vpl.api import (
    ERR_INVALID_DATA,
    ERR_INVALID_ITEM,
    ERR_NOT_APPLICABLE,
    PREFIX_LENGTH,
    SdcpClient,
    SdcpCommunityError,
    SdcpConnectionError,
    SdcpDeviceError,
    SdcpItemError,
    SdcpProtocolError,
)
import pytest

ITEM_POWER = 0x0102
ITEM_LAMP = 0x0113
ITEM_MODEL = 0x8001
ITEM_SET_POWER = 0x0130
ITEM_IR_MENU = 0x1729


class FakeProjector:
    """A minimal SDCP server on loopback.

    Replies are written from a separate task rather than inline, so that a client
    which pipelined its commands would be observable as two requests in flight at
    once. A correctly locked client never produces that.
    """

    def __init__(self) -> None:
        """Initialize the fake projector."""
        self.values: dict[int, int | bytes] = {ITEM_POWER: 3, ITEM_LAMP: 1234}
        self.ng: dict[int, int] = {}
        self.requests: list[tuple[int, int, int | None]] = []
        self.connections = 0
        self.delay = 0.0
        self.split_replies = False
        self.silent_first_request = False
        self.answer_with_item: int | None = None
        # The real projector acts on an infrared item and sends nothing back.
        self.silent_items: set[int] = {ITEM_IR_MENU}
        self.max_in_flight = 0
        self._in_flight = 0
        self._server: asyncio.Server | None = None
        self._tasks: set[asyncio.Task[None]] = set()
        self._writers: set[asyncio.StreamWriter] = set()

    async def wait_for_requests(self, count: int, timeout: float = 2.0) -> None:
        """Wait until the server has actually read ``count`` requests.

        Needed for infrared commands: nothing is read back, so returning from the
        client means only that the bytes left our buffer, not that the peer has seen
        them. Waiting for a reply used to provide this synchronisation for free.
        """
        async with asyncio.timeout(timeout):
            while len(self.requests) < count:
                await asyncio.sleep(0.005)

    @property
    def port(self) -> int:
        """Return the port the server is listening on."""
        assert self._server is not None
        return self._server.sockets[0].getsockname()[1]

    async def __aenter__(self) -> Self:
        """Start listening."""
        self._server = await asyncio.start_server(self._handle, "127.0.0.1", 0)
        return self

    async def __aexit__(self, *args: object) -> None:
        """Stop listening and tear everything down deterministically.

        Since Python 3.12 ``Server.wait_closed`` also waits for the connection
        handlers, so a pending reply task or an open writer would hang the
        teardown rather than just leaking a warning.
        """
        for task in self._tasks:
            task.cancel()
        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)
        for writer in self._writers:
            writer.close()
        assert self._server is not None
        self._server.close()
        with suppress(TimeoutError):
            async with asyncio.timeout(5):
                await self._server.wait_closed()

    async def _handle(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        """Serve one connection."""
        self.connections += 1
        self._writers.add(writer)
        try:
            while True:
                prefix = await reader.readexactly(PREFIX_LENGTH)
                data_length = prefix[9]
                data = await reader.readexactly(data_length) if data_length else b""
                request, item = prefix[6], int.from_bytes(prefix[7:9], "big")
                value = int.from_bytes(data, "big") if data else None
                self.requests.append((request, item, value))

                if self.silent_first_request and len(self.requests) == 1:
                    # Reproduce the standby quirk: the packet that wakes the
                    # Ethernet interface is dropped without a reply.
                    writer.close()
                    return

                if item in self.silent_items:
                    # Infrared items are acted on but never answered.
                    continue

                self._in_flight += 1
                self.max_in_flight = max(self.max_in_flight, self._in_flight)
                task = asyncio.create_task(self._reply(writer, request, item))
                self._tasks.add(task)
                task.add_done_callback(self._tasks.discard)
        except asyncio.IncompleteReadError, ConnectionResetError, BrokenPipeError:
            pass

    async def _reply(
        self, writer: asyncio.StreamWriter, request: int, item: int
    ) -> None:
        """Write one reply, optionally slowly or in two segments."""
        try:
            if self.delay:
                await asyncio.sleep(self.delay)
            frame = self._build_reply(request, item)
            if self.split_replies:
                writer.write(frame[:PREFIX_LENGTH])
                await writer.drain()
                await asyncio.sleep(0)
                writer.write(frame[PREFIX_LENGTH:])
            else:
                writer.write(frame)
            await writer.drain()
        except ConnectionResetError, BrokenPipeError:
            pass
        finally:
            self._in_flight -= 1

    def _build_reply(self, request: int, item: int) -> bytes:
        """Build the response frame for one request."""
        answered = self.answer_with_item if self.answer_with_item is not None else item
        if (code := self.ng.get(item)) is not None:
            return self._frame(ok=False, item=answered, data=code.to_bytes(2, "big"))
        if request == 0x00:  # SET carries no data back
            return self._frame(ok=True, item=answered, data=b"")
        value = self.values.get(item, 0)
        data = value if isinstance(value, bytes) else value.to_bytes(2, "big")
        return self._frame(ok=True, item=answered, data=data)

    @staticmethod
    def _frame(*, ok: bool, item: int, data: bytes) -> bytes:
        """Assemble a response frame."""
        return (
            bytes((0x02, 0x0A))
            + b"SONY"
            + bytes((0x01 if ok else 0x00,))
            + item.to_bytes(2, "big")
            + bytes((len(data),))
            + data
        )


@pytest.fixture
async def projector() -> AsyncIterator[FakeProjector]:
    """Yield a running fake projector."""
    async with FakeProjector() as fake:
        yield fake


def _client(projector: FakeProjector, **kwargs: object) -> SdcpClient:
    """Build a client pointed at the fake projector."""
    return SdcpClient(host="127.0.0.1", port=projector.port, **kwargs)  # type: ignore[arg-type]


async def test_get_value(projector: FakeProjector) -> None:
    """A GET returns the projector's value."""
    client = _client(projector)
    assert await client.async_get_value(ITEM_POWER) == 3
    assert projector.requests == [(0x01, ITEM_POWER, None)]
    await client.async_close()


async def test_set_value(projector: FakeProjector) -> None:
    """A SET sends the value and expects no data back."""
    client = _client(projector)
    await client.async_set_value(ITEM_SET_POWER, 1)
    assert projector.requests == [(0x00, ITEM_SET_POWER, 1)]
    await client.async_close()


async def test_get_raw_handles_variable_length(projector: FakeProjector) -> None:
    """The equipment information items return more than two bytes."""
    projector.values[ITEM_MODEL] = b"VPL-VW270ES\x00"
    client = _client(projector)
    assert await client.async_get_raw(ITEM_MODEL) == b"VPL-VW270ES\x00"
    await client.async_close()


async def test_get_value_rejects_wrong_length(projector: FakeProjector) -> None:
    """A two byte accessor must not silently truncate a longer field."""
    projector.values[ITEM_MODEL] = b"VPL-VW270ES\x00"
    client = _client(projector)
    with pytest.raises(SdcpProtocolError, match="expected 2"):
        await client.async_get_value(ITEM_MODEL)
    await client.async_close()


async def test_reply_split_across_segments(projector: FakeProjector) -> None:
    """Framing survives a reply that arrives in two TCP segments."""
    projector.split_replies = True
    client = _client(projector)
    assert await client.async_get_value(ITEM_POWER) == 3
    await client.async_close()


async def test_eof_mid_conversation_raises_connection_error(
    projector: FakeProjector,
) -> None:
    """A projector that hangs up without replying is a connection error."""
    projector.silent_first_request = True
    client = _client(projector)
    with pytest.raises(SdcpConnectionError):
        await client.async_get_value(ITEM_POWER)
    await client.async_close()


async def test_mismatched_item_raises_protocol_error(
    projector: FakeProjector,
) -> None:
    """A reply for the wrong item means the stream is out of sync."""
    projector.answer_with_item = ITEM_LAMP
    client = _client(projector)
    with pytest.raises(SdcpProtocolError, match="out of sync"):
        await client.async_get_value(ITEM_POWER)
    await client.async_close()


async def test_refused_connection_raises_connection_error() -> None:
    """Nothing listening on the port is a connection error, not a crash."""
    # Bind and immediately close, so the port is almost certainly free.
    server = await asyncio.start_server(lambda r, w: None, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    server.close()
    await server.wait_closed()

    client = SdcpClient(host="127.0.0.1", port=port, timeout=1.0)
    with pytest.raises(SdcpConnectionError):
        await client.async_get_value(ITEM_POWER)


async def test_timeout_raises_connection_error(projector: FakeProjector) -> None:
    """A projector that answers too slowly times out rather than hanging."""
    # Only just slower than the client allows: a long delay here would leave a
    # sleeping reply task behind for the teardown to clean up.
    projector.delay = 0.5
    client = _client(projector, timeout=0.05)
    with pytest.raises(SdcpConnectionError):
        await client.async_get_value(ITEM_POWER)
    await client.async_close()


async def test_commands_never_overlap(projector: FakeProjector) -> None:
    """Ten concurrent reads are serialised into ten sequential round trips.

    The projector accepts one command at a time, so this is the real test of the
    client's lock: the fake replies from a separate task, so a client that
    pipelined would show two requests in flight at once.
    """
    projector.delay = 0.01
    client = _client(projector)
    async with client.connection():
        results = await asyncio.gather(
            *(client.async_get_value(ITEM_POWER) for _ in range(10))
        )
    assert results == [3] * 10
    assert len(projector.requests) == 10
    assert projector.max_in_flight == 1


async def test_connection_block_reuses_one_socket(projector: FakeProjector) -> None:
    """A burst inside a connection block costs a single TCP handshake."""
    client = _client(projector)
    async with client.connection():
        for _ in range(12):
            await client.async_get_value(ITEM_POWER)
    assert projector.connections == 1
    assert len(projector.requests) == 12


async def test_without_a_connection_block_each_command_reconnects(
    projector: FakeProjector,
) -> None:
    """Outside a block the socket is opened and closed per command."""
    client = _client(projector)
    for _ in range(3):
        await client.async_get_value(ITEM_POWER)
    assert projector.connections == 3


async def test_nested_connection_blocks_reuse_one_socket(
    projector: FakeProjector,
) -> None:
    """A write arriving during a poll cycle joins the open connection.

    This is what the reference count is for: the projector accepts only one
    connection at a time, so a second one would be refused.
    """
    client = _client(projector)
    async with client.connection():
        await client.async_get_value(ITEM_POWER)
        async with client.connection():
            await client.async_set_value(ITEM_SET_POWER, 1)
        # The inner block must not have closed the socket the outer one is using.
        await client.async_get_value(ITEM_LAMP)
    assert projector.connections == 1


async def test_retry_resends_after_a_dropped_first_packet(
    projector: FakeProjector,
) -> None:
    """With retry the standby wake up quirk is invisible to the caller."""
    projector.silent_first_request = True
    client = _client(projector)
    assert await client.async_get_value(ITEM_POWER, retry=True) == 3
    assert len(projector.requests) == 2
    await client.async_close()


async def test_without_retry_a_dropped_packet_surfaces(
    projector: FakeProjector,
) -> None:
    """Only commands that opt in are resent."""
    projector.silent_first_request = True
    client = _client(projector)
    with pytest.raises(SdcpConnectionError):
        await client.async_get_value(ITEM_POWER)
    assert len(projector.requests) == 1
    await client.async_close()


async def test_infrared_command_succeeds_without_a_reply(
    projector: FakeProjector,
) -> None:
    """An infrared code is fire and forget, because the projector never answers.

    Confirmed on a VPL-VW270ES: the menu opens but nothing comes back. Waiting for
    a reply would stall for the whole command timeout on every keypress and then
    report a failure that did not happen.
    """
    client = _client(projector, timeout=0.5)
    await client.async_send_ir(ITEM_IR_MENU)
    await projector.wait_for_requests(1)
    assert projector.requests == [(0x00, ITEM_IR_MENU, 0)]
    await client.async_close()


async def test_infrared_burst_is_not_slowed_by_the_missing_replies(
    projector: FakeProjector,
) -> None:
    """Three codes in a row cost nothing like three command timeouts."""
    client = _client(projector, timeout=5.0)
    started = asyncio.get_running_loop().time()
    async with client.connection():
        for _ in range(3):
            await client.async_send_ir(ITEM_IR_MENU)
    elapsed = asyncio.get_running_loop().time() - started
    assert elapsed < 1.0, (
        f"a fire and forget burst should be quick, took {elapsed:.1f}s"
    )
    await projector.wait_for_requests(3)
    # A burst of keypresses stays on one connection: writing another infrared
    # command on a tainted socket is harmless, only reading from it is not.
    assert projector.connections == 1
    await client.async_close()


async def test_infrared_command_is_sent_exactly_once(
    projector: FakeProjector,
) -> None:
    """An infrared code is never sent twice, even if the projector hangs up.

    These are relative actions, so resending "menu" after an ambiguous failure
    would open and then close the menu again. The retry that the power and status
    commands rely on must never reach this path.
    """
    projector.silent_first_request = True
    client = _client(projector)
    await client.async_send_ir(ITEM_IR_MENU)
    await projector.wait_for_requests(1)
    # Give a retry every chance to appear before concluding there was not one.
    await asyncio.sleep(0.1)
    assert projector.requests == [(0x00, ITEM_IR_MENU, 0)]
    await client.async_close()


async def test_infrared_write_failure_is_reported() -> None:
    """An unreachable projector is still an error, not a silent success."""
    server = await asyncio.start_server(lambda r, w: None, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    server.close()
    await server.wait_closed()

    client = SdcpClient(host="127.0.0.1", port=port, timeout=1.0)
    with pytest.raises(SdcpConnectionError):
        await client.async_send_ir(ITEM_IR_MENU)


async def test_connection_is_not_reused_after_an_infrared_command(
    projector: FakeProjector,
) -> None:
    """A read must never land on a reply the projector volunteered afterwards.

    Nothing is read after an infrared write, so any reply some firmware did send
    would still be sitting in the socket and would be taken for the answer to the
    next command. Replacing the connection removes that whole class of bug.
    """
    client = _client(projector)
    async with client.connection():
        await client.async_get_value(ITEM_POWER)
        assert projector.connections == 1
        await client.async_send_ir(ITEM_IR_MENU)
        assert await client.async_get_value(ITEM_POWER) == 3
    assert projector.connections == 2


async def test_not_applicable_returns_none(projector: FakeProjector) -> None:
    """A setting that does not apply right now is not an error."""
    projector.ng[ITEM_LAMP] = ERR_NOT_APPLICABLE
    client = _client(projector)
    assert await client.async_try_get(ITEM_LAMP) is None
    assert ITEM_LAMP not in client.unsupported_items
    await client.async_close()


async def test_invalid_item_is_asked_for_only_once(projector: FakeProjector) -> None:
    """An item this projector does not implement is remembered and dropped.

    This is what makes an unverified item number in items.py cheap to be wrong
    about: it costs one round trip for the lifetime of the config entry.
    """
    projector.ng[ITEM_LAMP] = ERR_INVALID_ITEM
    client = _client(projector)

    assert await client.async_try_get(ITEM_LAMP) is None
    assert ITEM_LAMP in client.unsupported_items
    assert len(projector.requests) == 1

    assert await client.async_try_get(ITEM_LAMP) is None
    assert len(projector.requests) == 1, "the item must not be requested again"
    await client.async_close()


async def test_invalid_item_also_short_circuits_raw_reads(
    projector: FakeProjector,
) -> None:
    """The unsupported memory applies to variable length items too."""
    projector.ng[ITEM_MODEL] = ERR_INVALID_ITEM
    client = _client(projector)
    assert await client.async_try_get_raw(ITEM_MODEL) is None
    assert await client.async_try_get_raw(ITEM_MODEL) is None
    assert len(projector.requests) == 1
    await client.async_close()


async def test_community_error_is_distinguishable(projector: FakeProjector) -> None:
    """A rejected community must be its own exception, to drive reauth."""
    projector.ng[ITEM_POWER] = 0x0201
    client = _client(projector)
    with pytest.raises(SdcpCommunityError):
        await client.async_get_value(ITEM_POWER)
    await client.async_close()


async def test_invalid_data_is_an_item_error(projector: FakeProjector) -> None:
    """A refused value is an item error, which becomes a validation error."""
    projector.ng[ITEM_SET_POWER] = ERR_INVALID_DATA
    client = _client(projector)
    with pytest.raises(SdcpItemError) as err:
        await client.async_set_value(ITEM_SET_POWER, 1)
    assert err.value.code == ERR_INVALID_DATA
    await client.async_close()


@pytest.mark.parametrize("code", [0x1001, 0x2001, 0xF010, 0xF120])
async def test_device_errors_are_device_errors(
    projector: FakeProjector, code: int
) -> None:
    """Request, network, communication and NVRAM faults share one class."""
    projector.ng[ITEM_POWER] = code
    client = _client(projector)
    with pytest.raises(SdcpDeviceError):
        await client.async_get_value(ITEM_POWER)
    await client.async_close()


async def test_community_must_be_four_ascii_characters() -> None:
    """The client refuses an impossible community before opening a socket."""
    with pytest.raises(ValueError, match="exactly 4"):
        SdcpClient(host="127.0.0.1", community="SON")


async def test_close_is_idempotent(projector: FakeProjector) -> None:
    """Closing twice, or without ever connecting, is harmless."""
    client = _client(projector)
    await client.async_close()
    await client.async_get_value(ITEM_POWER)
    await client.async_close()
    await client.async_close()


async def test_idle_connection_is_reopened_before_use(projector: FakeProjector) -> None:
    """A socket left idle too long is replaced rather than written to.

    PJ Talk drops a connection that has been idle for 30 seconds. Writing to it
    then succeeds locally and the read returns an EOF, which is indistinguishable
    from the command having been lost, so the stale socket has to be spotted
    beforehand rather than recovered from afterwards.
    """
    client = _client(projector, idle_timeout=0.05)
    async with client.connection():
        await client.async_get_value(ITEM_POWER)
        assert projector.connections == 1

        # Back to back, the same socket is reused.
        await client.async_get_value(ITEM_POWER)
        assert projector.connections == 1

        await asyncio.sleep(0.1)
        await client.async_get_value(ITEM_POWER)
        assert projector.connections == 2, "the idle socket should have been replaced"


async def test_idle_reopen_can_be_disabled(projector: FakeProjector) -> None:
    """A zero idle timeout keeps the socket for as long as the block lasts."""
    client = _client(projector, idle_timeout=0)
    async with client.connection():
        await client.async_get_value(ITEM_POWER)
        await asyncio.sleep(0.05)
        await client.async_get_value(ITEM_POWER)
    assert projector.connections == 1
