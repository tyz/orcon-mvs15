"""The declared quality scale tier matches the rules that are met."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml

COMPONENT = Path(__file__).parent.parent / "custom_components" / "orcon_mvs15"


def load_manifest() -> dict[str, Any]:
    """Return the integration manifest."""
    return json.loads((COMPONENT / "manifest.json").read_text(encoding="utf-8"))


def load_rule_statuses() -> dict[str, str]:
    """Return the status of every rule in quality_scale.yaml."""
    data: dict[str, Any] = yaml.safe_load(
        (COMPONENT / "quality_scale.yaml").read_text(encoding="utf-8")
    )
    return {
        name: value if isinstance(value, str) else value["status"]
        for name, value in data["rules"].items()
    }


def test_manifest_declares_platinum() -> None:
    """The integration advertises the tier its rule file supports."""
    assert load_manifest()["quality_scale"] == "platinum"


def test_every_quality_scale_rule_is_met() -> None:
    """A tier claim only holds while no rule is still todo."""
    statuses = load_rule_statuses()

    assert len(statuses) == 54
    assert set(statuses.values()) == {"done", "exempt"}
