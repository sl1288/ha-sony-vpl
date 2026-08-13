"""SDCP item numbers and value maps for Sony VPL video projectors.

Item numbers come from the VPL-VW320/VW520 protocol manual, whose on-screen menu
the VPL-VW270ES shares almost completely. Every value map whose numbering could not
simply be read off that manual has since been measured on a real VW270ES with
``tools/map_values.py``, and says so; the marker UNVERIFIED is left for anything
still taken on trust. **On a different VPL model, treat the measured maps as
unverified again and re-run that tool.**

Being wrong about an entry is cheap by design: the client in ``api.py`` remembers
any item the projector rejects as "invalid item" and never asks for it again, so a
bad guess costs one round trip for the lifetime of the config entry rather than
breaking the integration.

This module deliberately has no Home Assistant imports so it can be unit tested
on its own.
"""

from collections.abc import Mapping
from enum import IntEnum
import logging
from typing import Final

_LOGGER = logging.getLogger(__name__)

type OptionMap = Mapping[str, int]
"""Home Assistant option slug to raw SDCP value.

Declared once per setting; the entity derives both the option list and the reverse
lookup from it, so the two directions cannot drift apart.
"""

# --- Status, GET only --------------------------------------------------------
ITEM_STATUS_ERROR: Final = 0x0101
ITEM_STATUS_POWER: Final = 0x0102
ITEM_LAMP_TIMER: Final = 0x0113
ITEM_SW_VERSION: Final = 0x011E
ITEM_STATUS_ERROR2: Final = 0x0125
ITEM_FPGA_VERSION: Final = 0x013A

# --- Power, SET only. Always read the state back through ITEM_STATUS_POWER. --
# The SET values coincide with the Status Power constants, so "on" is literally
# the start-up state. Do not collapse the two into one constant: 0x0130 cannot be
# read and 0x0102 cannot be written.
ITEM_SET_POWER: Final = 0x0130
POWER_SET_OFF: Final = 0x0000
POWER_SET_ON: Final = 0x0001

# --- Equipment and network information, GET only, variable length data -------
ITEM_MODEL_NAME: Final = 0x8001
ITEM_SERIAL_NUMBER: Final = 0x8002
ITEM_MAC_ADDRESS: Final = 0x9000

# --- Picture ----------------------------------------------------------------
ITEM_INPUT: Final = 0x0001
ITEM_CALIBRATION_PRESET: Final = 0x0002
ITEM_CONTRAST: Final = 0x0010
ITEM_BRIGHTNESS: Final = 0x0011
ITEM_COLOR: Final = 0x0012
ITEM_HUE: Final = 0x0013
ITEM_SHARPNESS: Final = 0x0014
ITEM_COLOR_TEMPERATURE: Final = 0x0017
ITEM_LAMP_CONTROL: Final = 0x001A
ITEM_CONTRAST_ENHANCER: Final = 0x001C
ITEM_FILM_MODE: Final = 0x001F
ITEM_ASPECT: Final = 0x0020
ITEM_GAMMA_CORRECTION: Final = 0x0022
ITEM_NOISE_REDUCTION: Final = 0x0025
ITEM_PICTURE_MUTING: Final = 0x0030
ITEM_COLOR_SPACE: Final = 0x003B
ITEM_MOTIONFLOW: Final = 0x0059
ITEM_XV_COLOR: Final = 0x005A
ITEM_REALITY_CREATION: Final = 0x0067
ITEM_REALITY_CREATION_RESOLUTION: Final = 0x0068
ITEM_REALITY_CREATION_NOISE_FILTERING: Final = 0x0069
ITEM_CLEAR_WHITE: Final = 0x006B
ITEM_MPEG_NOISE_REDUCTION: Final = 0x006C
ITEM_SMOOTH_GRADATION: Final = 0x006D
ITEM_HDMI1_DYNAMIC_RANGE: Final = 0x006E
ITEM_HDMI2_DYNAMIC_RANGE: Final = 0x006F
ITEM_REALITY_CREATION_DATABASE: Final = 0x0075
ITEM_HDR: Final = 0x007C
ITEM_COLOR_CORRECTION: Final = 0x0086
ITEM_INPUT_LAG_REDUCTION: Final = 0x0099


# --- Value maps -------------------------------------------------------------

BOOLEAN: Final[OptionMap] = {"off": 0x0000, "on": 0x0001}
"""Shared by every plain off/on item, so switches need only an item number."""

INPUT: Final[OptionMap] = {"hdmi1": 0x0002, "hdmi2": 0x0003}

CALIBRATION_PRESET: Final[OptionMap] = {
    "cinema_film_1": 0x0000,
    "cinema_film_2": 0x0001,
    "reference": 0x0002,
    "tv": 0x0003,
    "photo": 0x0004,
    "game": 0x0005,
    "bright_cinema": 0x0006,
    "bright_tv": 0x0007,
    "user": 0x0008,
}

ASPECT: Final[OptionMap] = {
    "normal": 0x0001,
    "v_stretch": 0x000B,
    "zoom_1_85": 0x000C,
    "zoom_2_35": 0x000D,
    "stretch": 0x000E,
    "squeeze": 0x000F,
}

# VERIFIED on a VPL-VW270ES with tools/map_values.py. The gap at 7 is real: the
# projector rejects that value outright rather than it being an undocumented
# option, so the manual's odd looking numbering is simply correct.
COLOR_TEMPERATURE: Final[OptionMap] = {
    "d93": 0x0000,
    "d75": 0x0001,
    "d65": 0x0002,
    "custom_1": 0x0003,
    "custom_2": 0x0004,
    "custom_3": 0x0005,
    "custom_4": 0x0006,
    "custom_5": 0x0008,
    "d55": 0x0009,
}

LAMP_CONTROL: Final[OptionMap] = {"low": 0x0000, "high": 0x0001}

# Note the ordering: Middle is 3, after High. That is what the manual says.
CONTRAST_ENHANCER: Final[OptionMap] = {
    "off": 0x0000,
    "low": 0x0001,
    "high": 0x0002,
    "middle": 0x0003,
}

FILM_MODE: Final[OptionMap] = {"off": 0x0000, "auto": 0x0002}

GAMMA_CORRECTION: Final[OptionMap] = {
    "off": 0x0000,
    "gamma_1_8": 0x0001,
    "gamma_2_0": 0x0002,
    "gamma_2_1": 0x0003,
    "gamma_2_2": 0x0004,
    "gamma_2_4": 0x0005,
    "gamma_2_6": 0x0006,
    "gamma_7": 0x0007,
    "gamma_8": 0x0008,
    "gamma_9": 0x0009,
    "gamma_10": 0x000A,
}

NOISE_REDUCTION: Final[OptionMap] = {
    "off": 0x0000,
    "low": 0x0001,
    "middle": 0x0002,
    "high": 0x0003,
    "auto": 0x0004,
}

SMOOTH_GRADATION: Final[OptionMap] = {
    "off": 0x0000,
    "low": 0x0001,
    "middle": 0x0002,
    "high": 0x0003,
}

CLEAR_WHITE: Final[OptionMap] = {"off": 0x0000, "low": 0x0001, "high": 0x0002}

# VERIFIED on a VPL-VW270ES with tools/map_values.py. The gaps at 1, 2 and 7 are
# real; those values are rejected, and presumably belonged to colour spaces on an
# older chassis.
COLOR_SPACE: Final[OptionMap] = {
    "bt709": 0x0000,
    "color_space_1": 0x0003,
    "color_space_2": 0x0004,
    "color_space_3": 0x0005,
    "custom": 0x0006,
    "bt2020": 0x0008,
}

# VERIFIED on a VPL-VW270ES with tools/map_values.py, including True Cinema at 5,
# which was the one value carried over from the sibling manual on trust. Impulse (3)
# and Combination (4) belong to higher models and are absent here.
MOTIONFLOW: Final[OptionMap] = {
    "off": 0x0000,
    "smooth_high": 0x0001,
    "smooth_low": 0x0002,
    "true_cinema": 0x0005,
}

DYNAMIC_RANGE: Final[OptionMap] = {"auto": 0x0000, "limited": 0x0001, "full": 0x0002}

REALITY_CREATION_DATABASE: Final[OptionMap] = {
    "mastered_in_4k": 0x0000,
    "normal": 0x0001,
}

# VERIFIED on a VPL-VW270ES with tools/map_values.py. The VW520 manual's
# Off=0/On=1/Auto=2 turned out to still hold: "On" is simply labelled HDR10 on this
# generation, and the two modes it gained were appended rather than renumbered.
HDR: Final[OptionMap] = {
    "off": 0x0000,
    "hdr10": 0x0001,
    "auto": 0x0002,
    "hlg": 0x0003,
    "hdr_reference": 0x0004,
}


class PowerStatus(IntEnum):
    """Values of ITEM_STATUS_POWER (0x0102)."""

    STANDBY = 0
    START_UP = 1
    START_UP_LAMP = 2
    POWER_ON = 3
    COOLING1 = 4
    COOLING2 = 5

    @property
    def slug(self) -> str:
        """Return the Home Assistant option slug for this state."""
        return self.name.lower()


POWER_STATUS_OPTIONS: Final[list[str]] = [state.slug for state in PowerStatus]

# Cooling counts as off. This is the mapping pysdcp has used against real Sony
# projectors for years, by way of the built-in sony_projector integration.
POWER_STATUS_ON: Final = frozenset(
    {PowerStatus.START_UP, PowerStatus.START_UP_LAMP, PowerStatus.POWER_ON}
)
POWER_STATUS_TRANSITIONAL: Final = frozenset(
    {
        PowerStatus.START_UP,
        PowerStatus.START_UP_LAMP,
        PowerStatus.COOLING1,
        PowerStatus.COOLING2,
    }
)

# 0x0101 and 0x0125 are BITFIELDS, not enumerations: the values are powers of two
# and the projector ORs them together, so 0x48 means "temperature warning and
# temperature error". Decoding them as an enum would report nothing at all
# exactly when two faults coincide.
ERROR_FLAGS: Final[Mapping[int, str]] = {
    0x01: "lamp",
    0x02: "fan",
    0x04: "cover",
    0x08: "temperature",
    0x10: "d5v",
    0x20: "power",
    0x40: "temperature_warning",
}
ERROR2_FLAGS: Final[Mapping[int, str]] = {0x20: "highland_warning"}


# --- Infrared remote emulation ----------------------------------------------
# Items 0x17xx, 0x19xx and 0x1Bxx replay an infrared remote code; the low byte is
# the code from the manual's tables 2-8 to 2-12. These are SET only.
#
# The lens codes are included because the VW270ES lens is motorised: its
# specification reads "2.06 times zoom lens (motorized)" and its manual warns
# never to turn the lens by hand. Lens *memory* (Picture Position, 0x1B20-0x1B24)
# is not included, since that menu is absent on this model.
IR_COMMANDS: Final[Mapping[str, int]] = {
    # Setup, 15 bit category
    "power_toggle": 0x1715,
    "power_on": 0x172E,
    "power_off": 0x172F,
    "picture_muting": 0x1724,
    "status_on": 0x1725,
    "status_off": 0x1726,
    "menu": 0x1729,
    "hdmi1": 0x172B,
    "hdmi2": 0x172C,
    "right": 0x1733,
    "left": 0x1734,
    "up": 0x1735,
    "down": 0x1736,
    "input": 0x1757,
    "enter": 0x175A,
    "reset": 0x177B,
    # Picture, 15 bit category
    "motionflow": 0x1705,
    "contrast_enhancer": 0x1707,
    "contrast_up": 0x1718,
    "contrast_down": 0x1719,
    "color_up": 0x171A,
    "color_down": 0x171B,
    "brightness_up": 0x171E,
    "brightness_down": 0x171F,
    "hue_up": 0x1720,
    "hue_down": 0x1721,
    "sharpness_up": 0x1722,
    "sharpness_down": 0x1723,
    # Lens, 15 bit category
    "lens_shift_up": 0x1772,
    "lens_shift_down": 0x1773,
    "lens_focus_far": 0x1774,
    "lens_focus_near": 0x1775,
    "lens_zoom_large": 0x1777,
    "lens_zoom_small": 0x1778,
    # Lens, 20 bit category
    "lens_shift_left": 0x1902,
    "lens_shift_right": 0x1903,
    "lens_zoom": 0x1962,
    "lens_shift": 0x1963,
    "lens_focus": 0x1964,
    "lens_toggle": 0x1978,
    # Picture and screen, 20 bit category
    "color_space": 0x194B,
    "reality_creation": 0x194C,
    "calib_preset_bright_tv": 0x1951,
    "calib_preset_tv": 0x1952,
    "calib_preset_cinema_film_1": 0x1953,
    "calib_preset_user": 0x1954,
    "calib_preset_reference": 0x1955,
    "calib_preset_game": 0x1956,
    "calib_preset_photo": 0x1957,
    "calib_preset_cinema_film_2": 0x1958,
    "calib_preset_bright_cinema": 0x1959,
    "picture_mode": 0x195B,
    "color_temperature": 0x195C,
    "gamma_correction": 0x195E,
    "aspect": 0x196E,
    # Screen and picture, 20 bit extended category
    "color_correction": 0x1B1C,
    "aspect_normal": 0x1B41,
    "aspect_v_stretch": 0x1B44,
    "aspect_zoom_1_85": 0x1B45,
    "aspect_zoom_2_35": 0x1B46,
    "aspect_stretch": 0x1B47,
    "aspect_squeeze": 0x1B48,
}

# The manual requires at least 45 ms between two infrared commands.
IR_COMMAND_INTERVAL: Final = 0.045


# --- Decoders ---------------------------------------------------------------


def power_status(raw: int) -> PowerStatus | None:
    """Decode ITEM_STATUS_POWER without raising on an unknown value.

    Never ``PowerStatus(raw)``: some Sony firmwares report states beyond the six
    documented here, and one unexpected byte inside a coordinator update would
    otherwise take the whole integration offline.
    """
    try:
        return PowerStatus(raw)
    except ValueError:
        _LOGGER.warning("Undocumented power status 0x%04X, reporting as unknown", raw)
        return None


def decode_flags(raw: int, flags: Mapping[int, str]) -> list[str]:
    """Decode a bitfield status item into a sorted list of flag names."""
    return sorted(name for bit, name in flags.items() if raw & bit)


def decode_text(raw: bytes) -> str | None:
    """Decode a null padded ASCII field, or None when it is empty."""
    return raw.rstrip(b"\x00").decode("ascii", errors="replace").strip() or None


def decode_serial_number(raw: bytes) -> str | None:
    """Decode the four byte serial number as eight decimal digits.

    The value is a big endian integer rather than text: the manual gives a range
    of 00000000 to 99999999, which does not fit in four ASCII characters, and
    pysdcp reads the same field out of the SDAP advertisement with ``>I``.
    """
    if len(raw) != 4:
        return None
    value = int.from_bytes(raw, "big")
    return f"{value:08d}" if value <= 99999999 else str(value)


def decode_mac_address(raw: bytes) -> str | None:
    """Decode the six byte MAC address into colon separated hex."""
    if len(raw) != 6:
        return None
    return ":".join(f"{byte:02x}" for byte in raw)


def _is_decimal_byte(byte: int) -> bool:
    """Return True when both nibbles of a byte are decimal digits."""
    return (byte >> 4) <= 9 and (byte & 0x0F) <= 9


def decode_version(raw: int) -> str:
    """Decode a version item, where 0x0123 means version 1.23.

    UNVERIFIED: 0x0123 is consistent both with BCD nibbles and with "high byte
    major, low byte two decimal digits". The two only diverge once a nibble
    exceeds 9, for instance 0x010A, so fall back to the raw value there and say
    so. A wrong guess is then visible in the device info rather than silently
    wrong forever.
    """
    high, low = raw >> 8, raw & 0xFF
    if _is_decimal_byte(high) and _is_decimal_byte(low):
        return f"{high:x}.{low:02x}"
    _LOGGER.warning(
        "Version item value 0x%04X is not decimal coded, reporting it verbatim", raw
    )
    return f"0x{raw:04X}"
