"""Shared fixtures for the orcon_mvs15 test suite."""

from __future__ import annotations

from collections.abc import Iterator

import pytest

pytest_plugins = "pytest_homeassistant_custom_component"


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(
    enable_custom_integrations: None,
) -> Iterator[None]:
    """Allow every test to load this custom integration."""
    yield
