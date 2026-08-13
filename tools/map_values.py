#!/usr/bin/env python3
# ruff: noqa: T201  # an interactive command line tool; printing is the point
"""Work out which device value belongs to which menu option, on a real projector.

The work the right way round: it writes each candidate value and you simply read
the label off the projector's own on-screen menu, rather than navigating that menu
twenty times. Values the projector rejects never appear.

    python tools/map_values.py 10.10.10.10              # all four
    python tools/map_values.py 10.10.10.10 hdr          # just one
    python tools/map_values.py 10.10.10.10 --read-only  # never write anything

All four maps were derived from a sibling model's manual and have since been
confirmed on a VPL-VW270ES with this tool. On any other VPL model, treat them as
unverified again and re-run.

It prints a dict ready to paste into ``items.py``, with a diff against what is
currently assumed.

Safety: every value written here only *selects* an existing picture preset, so
nothing is overwritten and nothing is stored in NVRAM. The original value is read
first and restored at the end, including after Ctrl-C. Writing to colour
temperature selects one of the Custom slots; it does not alter what is calibrated
into them.
"""

import argparse
import asyncio
from dataclasses import dataclass, field
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "custom_components"))

from sony_vpl import items
from sony_vpl.api import (
    DEFAULT_COMMUNITY,
    DEFAULT_PORT,
    ERR_NOT_APPLICABLE,
    SdcpClient,
    SdcpError,
    SdcpItemError,
)

# The options each menu actually offers on a VPL-VW270ES, from its Operating
# Instructions, paired with the slug items.py should use.
HDR_OPTIONS = [
    ("Auto", "auto"),
    ("HDR10", "hdr10"),
    ("HDR Reference", "hdr_reference"),
    ("HLG", "hlg"),
    ("Off", "off"),
]
COLOR_TEMPERATURE_OPTIONS = [
    ("D93", "d93"),
    ("D75", "d75"),
    ("D65", "d65"),
    ("D55", "d55"),
    ("Custom 1", "custom_1"),
    ("Custom 2", "custom_2"),
    ("Custom 3", "custom_3"),
    ("Custom 4", "custom_4"),
    ("Custom 5", "custom_5"),
]
COLOR_SPACE_OPTIONS = [
    ("BT.709", "bt709"),
    ("BT.2020", "bt2020"),
    ("Color Space 1", "color_space_1"),
    ("Color Space 2", "color_space_2"),
    ("Color Space 3", "color_space_3"),
    ("Custom", "custom"),
]
MOTIONFLOW_OPTIONS = [
    ("Smooth High", "smooth_high"),
    ("Smooth Low", "smooth_low"),
    ("True Cinema", "true_cinema"),
    ("Off", "off"),
]


@dataclass(frozen=True, kw_only=True, slots=True)
class Target:
    """One setting to be mapped."""

    item: int
    map_name: str
    menu_name: str
    options: list[tuple[str, str]]
    current: dict[str, int] = field(default_factory=dict)
    note: str = ""
    max_value: int = 15


TARGETS: dict[str, Target] = {
    "hdr": Target(
        item=items.ITEM_HDR,
        map_name="HDR",
        menu_name="Picture, HDR",
        options=HDR_OPTIONS,
        current=dict(items.HDR),
        note=(
            "Needs an HDMI signal: with no source the menu greys HDR out and the\n"
            "  projector will reject every value as not applicable."
        ),
    ),
    "color_temperature": Target(
        item=items.ITEM_COLOR_TEMPERATURE,
        map_name="COLOR_TEMPERATURE",
        menu_name="Picture, Color Temp.",
        options=COLOR_TEMPERATURE_OPTIONS,
        current=dict(items.COLOR_TEMPERATURE),
        note=(
            "Selecting a Custom slot does not change what is calibrated into it.\n"
            "  Read the label, do not judge by eye: from the factory Custom 1 to 4\n"
            "  are copies of D93, D75, D65 and D55, so those pairs look identical on\n"
            "  screen while being different values."
        ),
    ),
    "color_space": Target(
        item=items.ITEM_COLOR_SPACE,
        map_name="COLOR_SPACE",
        menu_name="Picture, Expert Setting, Color Space",
        options=COLOR_SPACE_OPTIONS,
        current=dict(items.COLOR_SPACE),
        note=(
            "Set HDR to Off or HDR10 first, NOT Auto. With HDR on Auto the\n"
            "  projector restricts which colour spaces are selectable, so BT.2020\n"
            "  would look as though it does not exist."
        ),
    ),
    "motionflow": Target(
        item=items.ITEM_MOTIONFLOW,
        map_name="MOTIONFLOW",
        menu_name="Picture, Motionflow",
        options=MOTIONFLOW_OPTIONS,
        current=dict(items.MOTIONFLOW),
        note=(
            "Motionflow is greyed out for 4096x2160 sources and whenever Input Lag\n"
            "  Reduction is on, so use a 1080p or 3840x2160 source with that switch\n"
            "  off, or every value will be refused."
        ),
    ),
}


async def _ask(prompt: str) -> str:
    """Read one line from the user without blocking the event loop."""
    return (await asyncio.to_thread(input, prompt)).strip()


def _option_menu(target: Target) -> str:
    """Render the numbered option list the user picks from."""
    lines = [
        f"      {index:>2}  {label}"
        for index, (label, _) in enumerate(target.options, start=1)
    ]
    return "\n".join(lines)


async def _probe_by_writing(client: SdcpClient, target: Target) -> dict[int, str]:
    """Write each candidate value and ask what the projector's menu then shows."""
    original = await client.async_get_value(target.item)
    print(f"  current value: {original}")
    print(f"\n  Open the projector menu at: {target.menu_name}")
    print("  Leave it open, on screen. For each value below, read the label off it.\n")
    print(_option_menu(target))
    print("      s   skip / the menu did not change")
    print("      q   stop with this setting\n")

    found: dict[int, str] = {}
    accepted = 0
    try:
        for value in range(target.max_value + 1):
            try:
                # One short burst per candidate; the prompt below happens with no
                # connection open, so the projector's 30 second idle timeout
                # cannot bite while the user is reading the menu.
                async with client.connection():
                    await client.async_set_value(target.item, value)
                    read_back = await client.async_get_value(target.item)
            except SdcpItemError:
                # Rejected: this value does not exist for this setting.
                continue
            accepted += 1

            suffix = "" if read_back == value else f"  (reads back as {read_back}!)"
            while True:
                answer = await _ask(f"    value {value:>2} accepted{suffix} -> ")
                if answer.lower() == "q":
                    return found
                if answer.lower() in ("s", ""):
                    break
                if answer.isdigit() and 1 <= int(answer) <= len(target.options):
                    found[value] = target.options[int(answer) - 1][1]
                    break
                print("      please enter a number from the list, or s / q")
    finally:
        print(f"\n  restoring {original}")
        try:
            await client.async_set_value(target.item, original)
        except SdcpError as err:
            print(f"  WARNING: could not restore: {err}")
            print("  Set it back by hand in the projector menu.")

    if not accepted:
        # Every value refused means the setting itself is unavailable right now,
        # not that it has no values. Worth saying, because the two look identical
        # from here.
        print(
            "  The projector refused every value. That means this setting is\n"
            "  currently greyed out rather than that it has no values. Check that a\n"
            "  source is connected and displaying, and for colour space that HDR is\n"
            "  not on Auto."
        )
    return found


async def _probe_by_reading(client: SdcpClient, target: Target) -> dict[int, str]:
    """Ask the user to change the setting themselves, and read the value back.

    Slower than writing, but touches nothing.
    """
    print(f"\n  Open the projector menu at: {target.menu_name}")
    print("  Select each option in turn; press Enter after each one.\n")

    found: dict[int, str] = {}
    for label, slug in target.options:
        answer = await _ask(
            f"    set it to {label!r}, then Enter (s to skip, q to stop) "
        )
        if answer.lower() == "q":
            break
        if answer.lower() == "s":
            continue
        try:
            value = await client.async_get_value(target.item)
        except SdcpItemError as err:
            print(f"      the projector will not report it right now: 0x{err.code:04X}")
            continue
        if (clash := found.get(value)) is not None:
            print(f"      WARNING: {value} was already recorded as {clash!r}")
        found[value] = slug
        print(f"      {label} = {value}")
    return found


def _report(name: str, target: Target, found: dict[int, str]) -> bool:
    """Print the result for one setting. Returns True if it looks usable."""
    print(f"\n  --- {name} ---")
    if not found:
        print("  nothing recorded")
        return False

    by_slug = {slug: value for value, slug in sorted(found.items())}
    if len(by_slug) != len(found):
        print("  WARNING: two values were given the same label; re-run this setting.")

    print(f"  {target.map_name}: Final[OptionMap] = {{")
    for label, slug in target.options:
        if slug in by_slug:
            print(f'      "{slug}": 0x{by_slug[slug]:04X},  # {label}')
    print("  }")

    missing = [label for label, slug in target.options if slug not in by_slug]
    if missing:
        print(f"  not recorded: {', '.join(missing)}")

    if by_slug != target.current:
        print("\n  This differs from what items.py currently assumes:")

        def fmt(value: int | None) -> str:
            return "-" if value is None else f"0x{value:04X}"

        for slug in sorted(set(by_slug) | set(target.current)):
            was, now = target.current.get(slug), by_slug.get(slug)
            if was != now:
                print(f"      {slug:<16} {fmt(was)} -> {fmt(now)}")
    else:
        print("\n  This matches what items.py already assumes.")
    return True


async def _main() -> int:
    """Parse arguments and run the mapping session."""
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("host", help="hostname or IP address of the projector")
    parser.add_argument(
        "settings",
        nargs="*",
        choices=list(TARGETS),
        help="which settings to map (default: all of them)",
    )
    parser.add_argument(
        "--read-only",
        action="store_true",
        help="never write: you change the menu, the tool reads the value back",
    )
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--community", default=DEFAULT_COMMUNITY)
    parser.add_argument("--timeout", type=float, default=5.0)
    args = parser.parse_args()

    names = args.settings or list(TARGETS)
    client = SdcpClient(
        host=args.host,
        port=args.port,
        community=args.community,
        timeout=args.timeout,
    )

    results: dict[str, dict[int, str]] = {}
    try:
        # Deliberately no connection block around the whole session: PJ Talk closes
        # an idle socket after 30 seconds and a human reading the on-screen menu
        # takes longer than that. Each burst opens its own.
        power = items.power_status(
            await client.async_get_value(items.ITEM_STATUS_POWER, retry=True)
        )
        print(f"projector power state: {power.slug if power else 'unknown'}")
        if power is not items.PowerStatus.POWER_ON:
            print(
                "\nThe projector has to be fully on, showing a picture. Every "
                "picture setting\nis reported as not applicable otherwise."
            )
            return 1

        for name in names:
            target = TARGETS[name]
            print(f"\n{'=' * 72}\n{name}  (item 0x{target.item:04X})")
            if target.note:
                print(f"  NOTE: {target.note}")

            probe = _probe_by_reading if args.read_only else _probe_by_writing
            try:
                results[name] = await probe(client, target)
            except SdcpItemError as err:
                print(f"  the projector rejected this item: 0x{err.code:04X}")
                if err.code == ERR_NOT_APPLICABLE:
                    print("  check that a source is connected and displaying")
                results[name] = {}
    except KeyboardInterrupt:
        print("\ninterrupted")
    except SdcpError as err:
        print(f"error: {err}", file=sys.stderr)
        return 1
    finally:
        await client.async_close()

    print(f"\n{'=' * 72}\nRESULTS")
    usable = [name for name in results if _report(name, TARGETS[name], results[name])]

    if usable:
        print(
            "\nCompare each block against items.py. Where they differ, the block "
            "above is\nthe truth: it came off the projector."
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_main()))
