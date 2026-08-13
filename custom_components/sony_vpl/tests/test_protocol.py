"""Tests for the SDCP codec, the item table and the decoders.

No input or output at all: everything here is a pure function.

Run with:
    uv run --no-sync pytest ha-sony-vpl
"""

from collections.abc import Mapping
import re

from custom_components.sony_vpl import items
from custom_components.sony_vpl.api import (
    ERR_INVALID_DATA,
    ERR_INVALID_ITEM,
    ERR_NOT_APPLICABLE,
    PREFIX_LENGTH,
    Request,
    ResponseHeader,
    SdcpCommunityError,
    SdcpDeviceError,
    SdcpItemError,
    SdcpProtocolError,
    build_request,
    check_response,
    encode_community,
    parse_response_header,
)
import pytest

COMMUNITY = b"SONY"


def _reply(*, ok: bool, item: int, data: bytes) -> bytes:
    """Build a complete response frame the way the projector would."""
    return (
        bytes((0x02, 0x0A))
        + COMMUNITY
        + bytes((0x01 if ok else 0x00,))
        + item.to_bytes(2, "big")
        + bytes((len(data),))
        + data
    )


@pytest.mark.parametrize(
    ("request_type", "item", "value", "expected"),
    [
        # A GET has data length 0 and no data field, so 10 bytes.
        (Request.GET, 0x0102, None, b"\x02\x0aSONY\x01\x01\x02\x00"),
        # A SET carries a two byte big endian value, so 12 bytes. This is the
        # worked example from the protocol manual.
        (Request.SET, 0x0130, 0x0001, b"\x02\x0aSONY\x00\x01\x30\x02\x00\x01"),
        (Request.SET, 0x0130, 0x0000, b"\x02\x0aSONY\x00\x01\x30\x02\x00\x00"),
        # Manual section 4-3-2.8: set the picture mode to its first preset.
        (Request.SET, 0x0002, 0x0000, b"\x02\x0aSONY\x00\x00\x02\x02\x00\x00"),
        # Infrared emulation: the low byte of the item is the remote code.
        (Request.SET, 0x1729, 0x0000, b"\x02\x0aSONY\x00\x17\x29\x02\x00\x00"),
    ],
    ids=["get-power-status", "power-on", "power-off", "picture-mode", "ir-menu"],
)
def test_build_request(
    request_type: Request, item: int, value: int | None, expected: bytes
) -> None:
    """Requests match the byte layout in the protocol manual exactly."""
    assert build_request(request_type, item, value, COMMUNITY) == expected


def test_build_request_length() -> None:
    """A GET is ten bytes and a SET is twelve."""
    assert len(build_request(Request.GET, 0x0102, None, COMMUNITY)) == PREFIX_LENGTH
    assert len(build_request(Request.SET, 0x0130, 1, COMMUNITY)) == PREFIX_LENGTH + 2


@pytest.mark.parametrize("community", ["SONY", "abcd", "0000"])
def test_encode_community_accepts_four_ascii(community: str) -> None:
    """Exactly four ASCII characters are accepted."""
    assert encode_community(community) == community.encode("ascii")


@pytest.mark.parametrize("community", ["SON", "SONYX", "", "SÖNY"])
def test_encode_community_rejects_anything_else(community: str) -> None:
    """Wrong length or non ASCII raises ValueError.

    UnicodeEncodeError is itself a ValueError, so the config flow can catch both
    with a single except clause.
    """
    with pytest.raises(ValueError):
        encode_community(community)


def test_parse_response_header_ok() -> None:
    """An OK response with data is parsed into its three fields."""
    frame = _reply(ok=True, item=0x0102, data=b"\x00\x03")
    header = parse_response_header(frame[:PREFIX_LENGTH])
    assert header == ResponseHeader(ok=True, item=0x0102, data_length=2)
    assert check_response(header, frame[PREFIX_LENGTH:], 0x0102) == b"\x00\x03"


def test_parse_response_header_set_carries_no_data() -> None:
    """An OK response to a SET has no data field."""
    frame = _reply(ok=True, item=0x0130, data=b"")
    header = parse_response_header(frame)
    assert header.data_length == 0
    assert check_response(header, b"", 0x0130) == b""


@pytest.mark.parametrize("length", [0, 1, 9, 11])
def test_parse_response_header_rejects_wrong_length(length: int) -> None:
    """A truncated or overlong header is a protocol error."""
    with pytest.raises(SdcpProtocolError):
        parse_response_header(b"\x00" * length)


def test_parse_response_header_tolerates_odd_version(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A surprising version or category warns but still parses.

    Those two bytes are cosmetic; a real desynchronisation is caught by the item
    check instead, which is where a wrong value would actually reach an entity.
    """
    frame = bytearray(_reply(ok=True, item=0x0102, data=b"\x00\x03"))
    frame[0] = 0x09
    header = parse_response_header(bytes(frame[:PREFIX_LENGTH]))
    assert header.item == 0x0102
    assert "Unexpected response header" in caplog.text


def test_check_response_rejects_mismatched_item() -> None:
    """A reply for another item means the stream is out of sync."""
    header = ResponseHeader(ok=True, item=0x0113, data_length=2)
    with pytest.raises(SdcpProtocolError, match="out of sync"):
        check_response(header, b"\x00\x03", 0x0102)


@pytest.mark.parametrize(
    ("code", "expected"),
    [
        (ERR_INVALID_ITEM, SdcpItemError),
        (ERR_NOT_APPLICABLE, SdcpItemError),
        (ERR_INVALID_DATA, SdcpItemError),
        (0x0201, SdcpCommunityError),
        (0x1001, SdcpDeviceError),
        (0x2001, SdcpDeviceError),
        (0xF010, SdcpDeviceError),
        (0xF120, SdcpDeviceError),
    ],
    ids=[
        "invalid-item",
        "not-applicable",
        "invalid-data",
        "different-community",
        "request-error",
        "network-timeout",
        "checksum",
        "nvram-write",
    ],
)
def test_ng_codes_map_to_exceptions(code: int, expected: type[Exception]) -> None:
    """Every NG category maps to its own exception class."""
    header = ResponseHeader(ok=False, item=0x0102, data_length=2)
    with pytest.raises(expected) as err:
        check_response(header, code.to_bytes(2, "big"), 0x0102)
    assert err.value.code == code


def test_ng_without_error_code_is_a_protocol_error() -> None:
    """An NG reply that carries no code cannot be interpreted."""
    header = ResponseHeader(ok=False, item=0x0102, data_length=0)
    with pytest.raises(SdcpProtocolError):
        check_response(header, b"", 0x0102)


# --- The item table ---------------------------------------------------------
#
# These two guards scale to every option map at once and catch the whole class of
# copy and paste mistake that a table of fifteen maps invites.


def _option_map_names() -> list[str]:
    """Return the names of every option map in items.py.

    Selected structurally rather than from a hardcoded list, so a map added later
    is covered automatically. The two status bitfields map the other way round,
    from int to str, which is what excludes them here.
    """
    names = []
    for name in dir(items):
        if not name.isupper():
            continue
        value = getattr(items, name)
        if isinstance(value, Mapping) and all(isinstance(key, str) for key in value):
            names.append(name)
    return names


OPTION_MAP_NAMES = _option_map_names()


def test_option_maps_were_found() -> None:
    """Guard the guards: the reflection above must actually find the maps."""
    assert len(OPTION_MAP_NAMES) >= 15
    assert "ERROR_FLAGS" not in OPTION_MAP_NAMES


@pytest.mark.parametrize("name", OPTION_MAP_NAMES)
def test_option_maps_are_injective(name: str) -> None:
    """No two options of one setting may share a device value.

    A duplicate makes the reverse lookup in select.py non-deterministic, so one of
    the two options would silently never be reported back.
    """
    mapping: Mapping[str, int] = getattr(items, name)
    assert len(set(mapping.values())) == len(mapping)


@pytest.mark.parametrize("name", OPTION_MAP_NAMES)
def test_option_keys_are_slugs(name: str) -> None:
    """Option keys become translation keys, so they must be slugs."""
    mapping: Mapping[str, int] = getattr(items, name)
    assert all(re.fullmatch(r"[a-z0-9_]+", key) for key in mapping)


@pytest.mark.parametrize("name", OPTION_MAP_NAMES)
def test_option_values_fit_two_bytes(name: str) -> None:
    """Every device value has to fit the two byte data field."""
    mapping: Mapping[str, int] = getattr(items, name)
    assert all(0 <= value <= 0xFFFF for value in mapping.values())


@pytest.mark.parametrize(
    "name", [name for name in dir(items) if name.startswith("ITEM_")]
)
def test_item_numbers_fit_two_bytes(name: str) -> None:
    """Every item number has to fit the two byte item field."""
    assert 0 <= getattr(items, name) <= 0xFFFF


def test_ir_commands_are_slugs_and_fit_two_bytes() -> None:
    """Remote command names are user facing, and their items are real items."""
    assert items.IR_COMMANDS
    for name, item in items.IR_COMMANDS.items():
        assert re.fullmatch(r"[a-z0-9_]+", name), name
        # Infrared items live in the 0x17xx, 0x19xx and 0x1Bxx categories.
        assert item >> 8 in (0x17, 0x19, 0x1B), name


def test_ir_commands_have_no_duplicate_items() -> None:
    """Two names for the same code would be a copy and paste slip."""
    assert len(set(items.IR_COMMANDS.values())) == len(items.IR_COMMANDS)


# --- Decoders ---------------------------------------------------------------


@pytest.mark.parametrize("raw", [0, 1, 2, 3, 4, 5])
def test_power_status_decodes_documented_values(raw: int) -> None:
    """The six documented power states decode to the enum."""
    assert items.power_status(raw) is items.PowerStatus(raw)


@pytest.mark.parametrize("raw", [6, 7, 0xFF, 0xFFFF])
def test_power_status_returns_none_for_unknown(
    raw: int, caplog: pytest.LogCaptureFixture
) -> None:
    """An undocumented power state must not raise.

    Some Sony firmwares report saving and eco states beyond the documented six.
    Raising here would fail the whole coordinator update on one unexpected byte.
    """
    assert items.power_status(raw) is None
    assert "Undocumented power status" in caplog.text


def test_power_status_options_cover_the_enum() -> None:
    """The sensor's option list matches the enum, so no state can be unmapped."""
    assert items.POWER_STATUS_OPTIONS == [
        "standby",
        "start_up",
        "start_up_lamp",
        "power_on",
        "cooling1",
        "cooling2",
    ]


def test_power_status_on_excludes_cooling() -> None:
    """Cooling counts as off, matching what pysdcp reports in the field."""
    assert items.PowerStatus.COOLING1 not in items.POWER_STATUS_ON
    assert items.PowerStatus.COOLING2 not in items.POWER_STATUS_ON
    assert items.PowerStatus.START_UP in items.POWER_STATUS_ON


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (0x00, []),
        (0x01, ["lamp"]),
        (0x02, ["fan"]),
        # The status items are bitfields, so two faults at once must both appear.
        (0x48, ["temperature", "temperature_warning"]),
        (
            0x7F,
            [
                "cover",
                "d5v",
                "fan",
                "lamp",
                "power",
                "temperature",
                "temperature_warning",
            ],
        ),
    ],
    ids=["none", "lamp", "fan", "temperature-pair", "everything"],
)
def test_decode_flags(raw: int, expected: list[str]) -> None:
    """A bitfield status item decodes to every flag it has set."""
    assert items.decode_flags(raw, items.ERROR_FLAGS) == expected


def test_decode_flags_second_error_item() -> None:
    """The second status item only defines the highland warning."""
    assert items.decode_flags(0x20, items.ERROR2_FLAGS) == ["highland_warning"]
    assert items.decode_flags(0x00, items.ERROR2_FLAGS) == []


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (b"VPL-VW270ES\x00", "VPL-VW270ES"),
        (b"VPL-VW270ES\x00\x00\x00", "VPL-VW270ES"),
        (b"\x00" * 12, None),
        (b"", None),
    ],
    ids=["padded", "extra-padding", "all-padding", "empty"],
)
def test_decode_text(raw: bytes, expected: str | None) -> None:
    """A null padded ASCII field decodes to text, or None when it is blank."""
    assert items.decode_text(raw) == expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        # Four bytes big endian, rendered as eight digits. pysdcp reads the same
        # field out of the advertisement packet with ">I".
        ((1234567).to_bytes(4, "big"), "01234567"),
        ((0).to_bytes(4, "big"), "00000000"),
        ((99999999).to_bytes(4, "big"), "99999999"),
        (b"\x00\x00", None),
    ],
    ids=["seven-digits", "zero", "maximum", "wrong-length"],
)
def test_decode_serial_number(raw: bytes, expected: str | None) -> None:
    """The serial number is a big endian integer, not text."""
    assert items.decode_serial_number(raw) == expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (b"\x00\x24\xbe\x01\x02\x03", "00:24:be:01:02:03"),
        (b"\xaa\xbb\xcc\xdd\xee\xff", "aa:bb:cc:dd:ee:ff"),
        (b"\x00\x24\xbe", None),
    ],
    ids=["sony-oui", "upper-nibbles", "wrong-length"],
)
def test_decode_mac_address(raw: bytes, expected: str | None) -> None:
    """The MAC decodes to the same lower case form format_mac would produce."""
    assert items.decode_mac_address(raw) == expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        # The manual's own example: 0x0123 means version 1.23.
        (0x0123, "1.23"),
        (0x0100, "1.00"),
        (0x0999, "9.99"),
    ],
    ids=["manual-example", "dot-zero", "highest-decimal"],
)
def test_decode_version(raw: int, expected: str) -> None:
    """A decimal coded version renders as major.minor."""
    assert items.decode_version(raw) == expected


@pytest.mark.parametrize("raw", [0x010A, 0x0A00, 0x01FF])
def test_decode_version_falls_back_visibly(
    raw: int, caplog: pytest.LogCaptureFixture
) -> None:
    """A value that is not decimal coded is reported verbatim, and warns.

    0x0123 fits both a BCD reading and "high byte major, low byte two decimal
    digits"; the two only diverge once a nibble exceeds 9. Rather than guess, show
    the raw value so that a wrong assumption is visible in the device info.
    """
    assert items.decode_version(raw) == f"0x{raw:04X}"
    assert "not decimal coded" in caplog.text
