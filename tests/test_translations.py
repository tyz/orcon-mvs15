"""Tests that icons and translations stay in sync with the fan presets."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from custom_components.orcon_mvs15.codes import Code22f1

COMPONENT = Path(__file__).parent.parent / "custom_components" / "orcon_mvs15"
TRANSLATION_FILES = [
    "strings.json",
    "translations/en.json",
    "translations/nl.json",
]


def load_json(name: str) -> dict[str, Any]:
    """Load a JSON file shipped with the integration."""
    return json.loads((COMPONENT / name).read_text(encoding="utf-8"))


def key_tree(value: object) -> object:
    """Return the nested key structure of a translation file."""
    if isinstance(value, dict):
        return {key: key_tree(child) for key, child in value.items()}
    return None


def preset_state_keys(name: str) -> set[str]:
    """Return the translated fan preset identifiers from a file."""
    states = load_json(name)["entity"]["fan"]["fan_states"]["state_attributes"][
        "preset_mode"
    ]["state"]
    return set(states)


def test_icons_cover_every_preset() -> None:
    """Every selectable preset has an icon, and no icon is unreachable."""
    icons = load_json("icons.json")
    states = icons["entity"]["fan"]["fan_states"]["state_attributes"]["preset_mode"][
        "state"
    ]

    assert set(states) == set(Code22f1.presets())


@pytest.mark.parametrize("name", TRANSLATION_FILES)
def test_every_preset_has_a_display_name(name: str) -> None:
    """Preset identifiers are translated, not shown raw in the frontend."""
    assert preset_state_keys(name) == set(Code22f1.presets())


def test_translation_files_have_the_same_keys() -> None:
    """English and Dutch translations mirror the source strings."""
    source = key_tree(load_json("strings.json"))

    for name in TRANSLATION_FILES[1:]:
        assert key_tree(load_json(name)) == source
