#!/usr/bin/env python3
# ruff: noqa: T201  # a command line tool whose whole job is printing a report
"""Read every known SDCP item off a Sony VPL projector and print what came back.

This is how the value maps in ``items.py`` get corrected from ground truth. The
protocol client has no Home Assistant imports, so it runs standalone::

    python tools/probe.py 10.10.10.10

Run it three times to settle the unverified entries: with the projector in
standby, powered on with an ordinary source, and on an HDR source. Items reported
as "invalid item" are not implemented by this model; items reported as "not
applicable" exist but do not apply in the current state.
"""

import argparse
import asyncio
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "custom_components"))

from sony_vpl import items
from sony_vpl.api import (
    DEFAULT_COMMUNITY,
    DEFAULT_PORT,
    ERR_INVALID_ITEM,
    ERR_INVALID_ITEM_REQUEST,
    ERR_NOT_APPLICABLE,
    SdcpClient,
    SdcpError,
    SdcpItemError,
    SdcpNgError,
)

# Items that return text or a longer field rather than a two byte value.
RAW_ITEMS = {
    items.ITEM_MODEL_NAME: items.decode_text,
    items.ITEM_SERIAL_NUMBER: items.decode_serial_number,
    items.ITEM_MAC_ADDRESS: items.decode_mac_address,
}

# Items that are set only, so probing them would actually change something.
SKIP = {items.ITEM_SET_POWER}

NG_NAMES = {
    ERR_INVALID_ITEM: "invalid item (not implemented by this model)",
    ERR_INVALID_ITEM_REQUEST: "invalid item request",
    ERR_NOT_APPLICABLE: "not applicable in the current state",
}

# Item to the option map that is supposed to describe its values, so the probe can
# say whether the value it read is actually covered by items.py.
VALUE_MAPS = {
    items.ITEM_INPUT: items.INPUT,
    items.ITEM_CALIBRATION_PRESET: items.CALIBRATION_PRESET,
    items.ITEM_ASPECT: items.ASPECT,
    items.ITEM_COLOR_TEMPERATURE: items.COLOR_TEMPERATURE,
    items.ITEM_LAMP_CONTROL: items.LAMP_CONTROL,
    items.ITEM_CONTRAST_ENHANCER: items.CONTRAST_ENHANCER,
    items.ITEM_FILM_MODE: items.FILM_MODE,
    items.ITEM_GAMMA_CORRECTION: items.GAMMA_CORRECTION,
    items.ITEM_NOISE_REDUCTION: items.NOISE_REDUCTION,
    items.ITEM_MPEG_NOISE_REDUCTION: items.NOISE_REDUCTION,
    items.ITEM_SMOOTH_GRADATION: items.SMOOTH_GRADATION,
    items.ITEM_CLEAR_WHITE: items.CLEAR_WHITE,
    items.ITEM_COLOR_SPACE: items.COLOR_SPACE,
    items.ITEM_MOTIONFLOW: items.MOTIONFLOW,
    items.ITEM_HDMI1_DYNAMIC_RANGE: items.DYNAMIC_RANGE,
    items.ITEM_HDMI2_DYNAMIC_RANGE: items.DYNAMIC_RANGE,
    items.ITEM_REALITY_CREATION_DATABASE: items.REALITY_CREATION_DATABASE,
    items.ITEM_HDR: items.HDR,
    items.ITEM_PICTURE_MUTING: items.BOOLEAN,
    items.ITEM_XV_COLOR: items.BOOLEAN,
    items.ITEM_REALITY_CREATION: items.BOOLEAN,
    items.ITEM_COLOR_CORRECTION: items.BOOLEAN,
    items.ITEM_INPUT_LAG_REDUCTION: items.BOOLEAN,
}


def _describe(item: int, name: str, value: int) -> str:
    """Return a human readable rendering of a raw value."""
    if item == items.ITEM_STATUS_POWER:
        state = items.power_status(value)
        return state.slug if state else "UNDOCUMENTED STATE"
    if item == items.ITEM_STATUS_ERROR:
        return ", ".join(items.decode_flags(value, items.ERROR_FLAGS)) or "no error"
    if item == items.ITEM_STATUS_ERROR2:
        return ", ".join(items.decode_flags(value, items.ERROR2_FLAGS)) or "no error"
    if item in (items.ITEM_SW_VERSION, items.ITEM_FPGA_VERSION):
        return items.decode_version(value)
    if (mapping := VALUE_MAPS.get(item)) is not None:
        for option, mapped in mapping.items():
            if mapped == value:
                return option
        return f"*** {value} IS NOT IN THE MAP FOR {name} ***"
    return str(value)


async def _probe(client: SdcpClient) -> None:
    """Read every item and print one line each."""
    names = sorted(
        (name for name in dir(items) if name.startswith("ITEM_")),
        key=lambda name: getattr(items, name),
    )

    print(f"{'item':<38} {'hex':<8} {'raw':<12} decoded")
    print("-" * 96)

    unsupported: list[str] = []
    async with client.connection():
        for name in names:
            item = getattr(items, name)
            label = name.removeprefix("ITEM_").lower()
            if item in SKIP:
                print(f"{label:<38} 0x{item:04X}   {'-':<12} skipped (set only)")
                continue

            try:
                if (decoder := RAW_ITEMS.get(item)) is not None:
                    raw = await client.async_get_raw(item)
                    print(f"{label:<38} 0x{item:04X}   {raw.hex():<12} {decoder(raw)}")
                else:
                    value = await client.async_get_value(item)
                    print(
                        f"{label:<38} 0x{item:04X}   "
                        f"{value:<12} {_describe(item, label, value)}"
                    )
            except SdcpItemError as err:
                note = NG_NAMES.get(err.code, f"NG 0x{err.code:04X}")
                if err.code in (ERR_INVALID_ITEM, ERR_INVALID_ITEM_REQUEST):
                    unsupported.append(f"{label} (0x{item:04X})")
                print(f"{label:<38} 0x{item:04X}   {'-':<12} {note}")
            except SdcpNgError as err:
                print(
                    f"{label:<38} 0x{item:04X}   {'-':<12} "
                    f"NG 0x{err.code:04X} ({type(err).__name__})"
                )

    if unsupported:
        print(f"\nNot implemented by this projector ({len(unsupported)}):")
        for entry in unsupported:
            print(f"  - {entry}")


async def _main() -> int:
    """Parse arguments and run the probe."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("host", help="hostname or IP address of the projector")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--community", default=DEFAULT_COMMUNITY)
    parser.add_argument("--timeout", type=float, default=5.0)
    args = parser.parse_args()

    client = SdcpClient(
        host=args.host,
        port=args.port,
        community=args.community,
        timeout=args.timeout,
    )
    try:
        await _probe(client)
    except SdcpError as err:
        print(f"error: {err}", file=sys.stderr)
        return 1
    finally:
        await client.async_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_main()))
