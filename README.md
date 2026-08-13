# Sony VPL Projector for Home Assistant

Home Assistant custom integration for Sony VPL video projectors over **PJ Talk /
SDCP**. Developed against a **VPL-VW270ES**; other VW-generation models share most
of the item table and should largely work.

## Requirements

Two settings on the projector, both important:

1. **Setup → Network Management = On.** Without this the projector refuses PJ Talk
   connections while in standby, so Home Assistant cannot switch it on and will
   show it unavailable whenever it is off. No amount of retrying helps — the
   network interface is simply asleep. (`Remote Start = On` is a weaker
   alternative that allows power-on but not full standby polling.)
2. **Web Setup → PJ Talk enabled**, port `53484`, community `SONY` (the default).

No user name or password is needed. SDCP authenticates with the four-character
community string alone; the projector's web credentials are not used and are not
stored anywhere by this integration.

## Installation

Add this repository to HACS as a custom repository. Then add the
integration from **Settings → Devices & Services → Add Integration → Sony VPL
Projector** and enter the host.

## Configuration

| Where | What |
|---|---|
| Add / **Reconfigure** | host, port, community |
| **Configure** (options) | poll interval while on (15 s), while in standby (30 s), for picture settings (120 s), and the per-command timeout (5 s) |

Changing the options reloads the entry, so new intervals take effect immediately.

## Entities

46 in total. The eight that matter day to day are enabled; the 26 picture-tuning
entities and the 12 buttons are disabled by default — see *Polling* below for why
that is more than cosmetic for the settings.

| Platform | Enabled by default | Disabled by default |
|---|---|---|
| `remote` | the projector itself: on/off and `remote.send_command` | |
| `select` | input, calibration preset, aspect | lamp control, contrast enhancer, film mode, gamma correction, noise reduction, MPEG noise reduction, smooth gradation, Clear White, Motionflow, HDR, color temperature, color space, Reality Creation database, HDMI 1/2 dynamic range |
| `number` | | contrast, brightness, color, hue, sharpness, Reality Creation resolution and noise filtering |
| `switch` | picture muting | Reality Creation, x.v.Color, color correction, input lag reduction |
| `sensor` | power state, lamp hours | |
| `binary_sensor` | problem | |
| `button` | | menu, cursor up/down/left/right, enter, lens focus nearer/further, lens zoom in/out, lens shift up/down |

### Sending infrared commands

62 codes are emulated, including the motorised lens controls, and there are three
ways to reach them.

**`sony_vpl.send_command`** is the one to use from the interface: it declares the
whole command list, so the action editor offers a searchable dropdown with
translated labels instead of a text box.

```yaml
action: sony_vpl.send_command
target:
  entity_id: remote.vpl_vw270es
data:
  command:
    - menu
    - down
    - enter
  num_repeats: 1
  delay_secs: 0.4
```

**Buttons** cover the dozen commands that get pressed repeatedly — menu
navigation and lens adjustment. They are disabled by default; enable the ones you
want and put them on a dashboard. Nudging a motorised lens into place is far
easier with buttons than with an action.

**`remote.send_command`** is the standard platform action and still works
unchanged, which is what YAML and existing automations want:

```yaml
action: remote.send_command
target:
  entity_id: remote.vpl_vw270es
data:
  command:
    - menu
    - down
    - enter
```

The full list is also on the remote entity as an `ir_commands` attribute, so it
can be read in the developer tools or from a template without consulting this
file. Available: `menu`, `up`, `down`, `left`, `right`, `enter`, `reset`, `input`,
`hdmi1`, `hdmi2`, `power_on`, `power_off`, `power_toggle`, `picture_muting`,
`status_on`, `status_off`, `aspect` and the six direct `aspect_*`,
`calib_preset_*` for all nine presets, `color_temperature`, `gamma_correction`,
`color_space`, `color_correction`, `reality_creation`, `motionflow`,
`contrast_enhancer`, `picture_mode`, the `contrast`/`brightness`/`color`/`hue`/
`sharpness` `_up`/`_down` pairs, and `lens_shift_up`/`_down`/`_left`/`_right`,
`lens_focus_far`/`_near`, `lens_zoom_large`/`_small`, `lens_zoom`, `lens_shift`,
`lens_focus`, `lens_toggle`.

`num_repeats` and `delay_secs` are honoured. The manual requires at least 45 ms
between codes, so a shorter `delay_secs` is raised to that floor — with no round
trip to pace them, that delay is the only thing that does.

These commands are **fire and forget**: the projector acts on them but sends
nothing back, which the manual states for the serial transport and which was
confirmed to hold over SDCP. So a failure to reach the projector is still
reported, but the projector refusing an individual code cannot be — that refusal
is exactly the reply it does not send.

## How it works

### Protocol

SDCP is a small binary protocol on TCP 53484:

```
request   VERSION(1)=0x02  CATEGORY(1)=0x0A  COMMUNITY(4)
          REQUEST(1)       ITEM_NO(2 BE)     DATA_LEN(1)  DATA(n)
response  same prefix, then RESPONSE(1)  ITEM_NO(2)  DATA_LEN(1)  DATA(n)
```

A GET is 10 bytes, a SET is 12. Power is a set-only item (`0x0130`) and its state
is read back through a separate get-only item (`0x0102`) — the two are not
interchangeable.

`api.py` and `items.py` have **no Home Assistant imports**, so the protocol can be
unit tested on its own and driven from `tools/probe.py`.

### Polling

The projector accepts one command at a time and takes 30–1000 ms per round trip,
up to about 3.2 s under load. Reading all 34 items naively would take half a
minute, so:

- **Two coordinators.** A fast one reads only power, the two fault items and —
  while the lamp is on — input and lamp hours. A slow one reads picture settings.
- **Settings are read on demand.** Each setting entity subscribes to the slow
  coordinator with its item number as the coordinator *context*, and the
  coordinator only requests `async_contexts()`. A disabled entity is never added
  to Home Assistant, so it registers no listener and **its item is never polled at
  all** — the slow coordinator is not even scheduled until you enable something.
  That is why the tuning entities ship disabled.
- **Nothing is polled while the lamp is off**, since every setting answers "not
  applicable" then.
- **Batches are capped at 12 items** and rotate, so no cycle occupies the
  projector for long while everything still refreshes within a few minutes.
- **One TCP connection per burst.** Not per command (which would mean 12
  handshakes per cycle on a small embedded stack) and not permanently open (the
  projector closes an idle socket after 30 s, so that would race its own close).
  The connection helper is reference counted, so a button press arriving during a
  poll joins the open connection rather than opening a second one the projector
  would refuse.
- **The lock is held per round trip, never per cycle**, so a user action waits for
  at most one reply rather than a whole batch.

### Error handling

| Projector says | Result |
|---|---|
| not applicable (`0x0180`) | that one entity goes `unavailable` — the setting genuinely does not apply to the current input or signal |
| invalid item (`0x0101`) | logged once, then **never requested again** |
| wrong community (`0x02xx`) | triggers the re-authentication flow |
| invalid data on a write (`0x0104`) | a validation error naming the entity, not a crash |
| unreachable / malformed | the device goes unavailable |

`unavailable` rather than `unknown` for "not applicable" is deliberate: the
setting does not exist right now, as opposed to us having failed to read it. It
also handles dependencies for free — Motionflow goes unavailable on a 4K source
because the projector says so, with no dependency table to maintain.

## Known limitations

- **The item table comes from a sibling model's manual.** It is the
  VPL-VW320/VW520 protocol manual, whose menu the VW270ES shares almost completely
  — but not exactly. Three maps that could not be derived with confidence shipped
  as **read-only sensors** and were promoted to `select` only after being measured
  on a real VW270ES with `tools/map_values.py`, because a guessed value written
  into a projector's calibration cannot be undone from Home Assistant:
    - **HDR**: the old `Off=0, On=1, Auto=2` still holds, with `On` now labelled
      HDR10 and `HLG=3`, `HDR Reference=4` appended.
    - **Color temperature** and **color space**: exactly as the manual documents.
      The odd-looking gaps are real — the projector rejects 7 for colour
      temperature, and 1, 2 and 7 for colour space.

  **Motionflow** was measured too, confirming `True Cinema = 5`, the one value
  there that came from the older manual.

  On any other VPL model, treat all four as unverified again and re-run the tool.
- **Version decoding is ambiguous, and cannot be settled by measurement.**
  `0x0123` means 1.23 under both plausible readings; they only diverge once a
  nibble exceeds 9, which no firmware seen so far produces. The decoder falls back
  to the raw hex and logs a warning rather than guessing silently.
- **Not implemented:** ADCP (its per-model command names are not in any manual
  Sony publishes publicly), SDAP autodiscovery, installation settings (blanking,
  panel alignment, trigger, anamorphic lens, image flip, IR receiver, high
  altitude, test pattern), and 3D settings.
- **Not applicable to this model:** lens memory / Picture Position (`0x0066`) and
  Trigger 2 (`0x00C3`), neither of which the VW270ES has.

## Verifying against your projector

### `tools/probe.py` — what does this projector support?

```bash
python tools/probe.py 10.10.10.10
```

Reads every known item and prints `item | hex | raw | decoded`, flagging any value
that falls outside the map that is supposed to describe it, and listing everything
the projector reports as not implemented. Run it three times — in standby, powered
on with an SDR source, and on an HDR source.

The same information is in the integration's **download diagnostics**, including
the accumulated list of unsupported items.

### `tools/map_values.py` — settle the three unverified maps

```bash
python tools/map_values.py 10.10.10.10                 # all three
python tools/map_values.py 10.10.10.10 hdr             # one setting
python tools/map_values.py 10.10.10.10 --read-only     # never writes
```

The work the useful way round: instead of navigating the on-screen menu twenty
times, the tool writes each candidate value and you read the resulting label off
the menu, picking it from a numbered list. It skips values the projector rejects,
warns if two labels land on the same value, restores the original at the end
(including after Ctrl-C), and prints a dict ready to paste into `items.py` along
with a diff against what is currently assumed.

The projector must be **fully on and displaying a picture** — every picture
setting reports "not applicable" otherwise. For colour space, set **HDR to Off or
HDR10 first, not Auto**: on Auto the projector restricts which colour spaces are
selectable, so BT.2020 would look as though it did not exist. The tool says both
of these before it starts.

`--read-only` inverts it: you change the menu, the tool reads the value back. Use
it if you would rather nothing was written at all.

Once a map is confirmed, its read-only sensor becomes a `select` entity. All four
maps this tool covers have been measured on a VW270ES, so on that model it is only
needed to re-check after a firmware update.

## Development

```bash
uv run --no-sync pytest ha-sony-vpl          # 234 tests, no device needed
uv run --no-sync ruff check ha-sony-vpl
```

Tests are in four layers: golden-byte codec tests and table guards over every
option map (`test_protocol.py`), the client exercised against a real `asyncio`
server on loopback (`test_api.py`), the poll scheduling as a pure function
(`test_batching.py`), and the generated configuration locked back against the code
(`test_services.py`).

That last one matters more than it looks. `services.yaml`, the selector labels in
three files and the button entities all restate the command list in a form the
interface can read, and none of it is checked at runtime — a command dropped from
`items.py` would leave a dead option in the dropdown, and one added would silently
never appear.
