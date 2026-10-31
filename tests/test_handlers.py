"""Tests for the payload handlers."""

from __future__ import annotations

import logging
from types import SimpleNamespace

import pytest
from homeassistant.core import HomeAssistant

from custom_components.orcon_mvs15.handlers import DataHandlers


def make_handlers(hass: HomeAssistant) -> DataHandlers:
    """Build handlers with only the attributes they touch."""
    entry = SimpleNamespace(
        runtime_data=SimpleNamespace(
            co2_coordinator=SimpleNamespace(data={}),
            fan_coordinator=SimpleNamespace(data={}),
            ramses_esp=SimpleNamespace(),
            cleanup=[],
        )
    )
    return DataHandlers(hass, entry)


async def test_unsupported_device_info_logs_the_values(
    hass: HomeAssistant, caplog: pytest.LogCaptureFixture
) -> None:
    """A warning about an unknown device must show what was received."""
    payload = SimpleNamespace(
        values={"manufacturer_sub_id": "AA", "product_id": "26"},
        packet=SimpleNamespace(src_id="29:123456"),
    )

    with caplog.at_level(logging.WARNING):
        make_handlers(hass)._device_info_handler(payload)

    assert "AA" in caplog.text
