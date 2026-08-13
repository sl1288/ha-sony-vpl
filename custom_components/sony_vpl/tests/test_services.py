"""Tests that the generated configuration cannot drift from the code.

``services.yaml``, the selector labels and the button entities all restate the
infrared command list in a form Home Assistant's interface can read. None of that
is checked at runtime: a command dropped from ``items.py`` would leave a dead
option in the dropdown, and one added would silently never appear. These tests are
what keeps the four copies in step.
"""

import json
from pathlib import Path
from typing import Any

from custom_components.sony_vpl.button import BUTTONS
from custom_components.sony_vpl.items import IR_COMMANDS
import pytest
import yaml

from homeassistant.util import slugify

COMPONENT = Path(__file__).resolve().parent.parent
LANGUAGES = ("strings.json", "translations/en.json", "translations/de.json")


def _load_json(name: str) -> dict[str, Any]:
    """Load one of the component's JSON files."""
    return json.loads((COMPONENT / name).read_text())


@pytest.fixture(scope="module")
def services() -> dict[str, Any]:
    """Return the parsed services.yaml."""
    return yaml.safe_load((COMPONENT / "services.yaml").read_text())


def test_send_command_options_match_the_code(services: dict[str, Any]) -> None:
    """The dropdown offers exactly the commands the remote actually accepts."""
    options = services["send_command"]["fields"]["command"]["selector"]["select"][
        "options"
    ]
    assert sorted(options) == sorted(IR_COMMANDS)


def test_send_command_options_are_sorted(services: dict[str, Any]) -> None:
    """Keep the generated list ordered, so a regeneration produces no noise."""
    options = services["send_command"]["fields"]["command"]["selector"]["select"][
        "options"
    ]
    assert options == sorted(options)


def test_send_command_targets_this_integration(services: dict[str, Any]) -> None:
    """The action is offered on this integration's remote, and nothing else."""
    target = services["send_command"]["target"]["entity"]
    assert target == {"integration": "sony_vpl", "domain": "remote"}


def test_delay_cannot_be_set_below_the_projector_minimum(
    services: dict[str, Any],
) -> None:
    """The manual requires 45 ms between two infrared commands."""
    delay = services["send_command"]["fields"]["delay_secs"]["selector"]["number"]
    assert delay["min"] == pytest.approx(0.045)


@pytest.mark.parametrize("language", LANGUAGES)
def test_every_command_has_a_label(language: str) -> None:
    """A command with no label would show as a bare slug in the dropdown."""
    options = _load_json(language)["selector"]["ir_command"]["options"]
    assert sorted(options) == sorted(IR_COMMANDS)


@pytest.mark.parametrize("language", LANGUAGES)
def test_no_label_is_empty(language: str) -> None:
    """An empty label renders as a blank row that cannot be told apart."""
    options = _load_json(language)["selector"]["ir_command"]["options"]
    assert all(label.strip() for label in options.values())


@pytest.mark.parametrize("language", LANGUAGES)
def test_labels_are_distinguishable(language: str) -> None:
    """Two commands sharing a label would be impossible to tell apart in the list."""
    options = _load_json(language)["selector"]["ir_command"]["options"]
    duplicates = {
        label for label in options.values() if list(options.values()).count(label) > 1
    }
    assert not duplicates


@pytest.mark.parametrize("language", LANGUAGES)
def test_the_action_itself_is_described(language: str) -> None:
    """The action and each of its fields need a name and description."""
    action = _load_json(language)["services"]["send_command"]
    assert action["name"] and action["description"]
    assert sorted(action["fields"]) == ["command", "delay_secs", "num_repeats"]
    for field in action["fields"].values():
        assert field["name"] and field["description"]


def test_every_button_maps_to_a_real_command() -> None:
    """A button naming a command that does not exist would fail only when pressed."""
    assert all(description.command in IR_COMMANDS for description in BUTTONS)


def test_buttons_are_disabled_by_default() -> None:
    """Which of these are useful depends on the installation, so none are forced."""
    assert not any(
        description.entity_registry_enabled_default for description in BUTTONS
    )


@pytest.mark.parametrize("language", LANGUAGES)
def test_every_button_has_a_label(language: str) -> None:
    """A button with no label falls back to an unhelpful generated name."""
    labels = _load_json(language)["entity"]["button"]
    assert sorted(labels) == sorted(description.key for description in BUTTONS)
    assert all(block["name"].strip() for block in labels.values())


def test_every_button_has_an_icon() -> None:
    """These live on dashboards, where the icon is most of what is seen."""
    icons = _load_json("icons.json")["entity"]["button"]
    assert sorted(icons) == sorted(description.key for description in BUTTONS)


@pytest.mark.parametrize("language", LANGUAGES)
def test_entity_names_produce_usable_entity_ids(language: str) -> None:
    """Every name slugifies to something non-empty and unique for its platform.

    Home Assistant derives the entity id from the *translated* name wherever the
    installation's language is one it generates native ids for, German included, so
    these names are not merely cosmetic. Two names colliding inside one platform
    would make Home Assistant append a number to whichever lost the race.

    Note what this cannot check: slugify drops diacritics rather than
    transliterating them, so "Schaerfe" would silently become the unrelated word
    "scharfe". Whether a given name survives that is a judgement, made when naming;
    ess-zett is fine, since it does become "ss".
    """
    for platform, blocks in _load_json(language)["entity"].items():
        slugs: dict[str, str] = {}
        for key, block in blocks.items():
            slug = slugify(block["name"])
            assert slug, f"{platform}.{key} slugifies to nothing"
            assert slug not in slugs, (
                f"{platform}.{key} and {platform}.{slugs[slug]} both slugify to {slug}"
            )
            slugs[slug] = key
