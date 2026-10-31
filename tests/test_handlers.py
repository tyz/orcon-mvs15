"""Tests for the payload handlers."""

from __future__ import annotations

import logging
from types import SimpleNamespace

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceRegistry

from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.orcon_mvs15.const import DOMAIN
from custom_components.orcon_mvs15.handlers import DataHandlers

FAN_ID = "29:224547"


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


def make_entry_handlers(
    hass: HomeAssistant,
) -> tuple[MockConfigEntry, DataHandlers]:
    """Build handlers for an entry that can own devices."""
    entry = MockConfigEntry(domain=DOMAIN, data={})
    entry.add_to_hass(hass)
    entry.runtime_data = SimpleNamespace(
        co2_coordinator=SimpleNamespace(data={}),
        fan_coordinator=SimpleNamespace(data={}),
    )
    return entry, DataHandlers(hass, entry)


def device_info_payload(**values: object) -> SimpleNamespace:
    """Build a 10E0 payload with the fields the handler reads."""
    return SimpleNamespace(
        values={
            "manufacturer_sub_id": "C8",
            "product_id": "26",
            "software_ver_id": "2A",
            "description": "Orcon MVS-15",
            "signal_strength": -50,
            **values,
        },
        packet=SimpleNamespace(src_id=FAN_ID),
    )


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


async def test_device_info_updates_the_registered_device(
    hass: HomeAssistant, device_registry: DeviceRegistry
) -> None:
    """A supported 10E0 payload is stored on the fan device."""
    entry, handlers = make_entry_handlers(hass)
    device = device_registry.async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={(DOMAIN, FAN_ID)},
    )

    handlers._device_info_handler(device_info_payload())

    updated = device_registry.async_get(device.id)
    assert updated is not None
    assert updated.sw_version == "42"
    assert updated.model_id == "Orcon MVS-15"


async def test_incomplete_device_info_is_ignored(
    hass: HomeAssistant, device_registry: DeviceRegistry
) -> None:
    """A payload without the version and model does not write placeholders."""
    entry, handlers = make_entry_handlers(hass)
    device = device_registry.async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={(DOMAIN, FAN_ID)},
    )

    handlers._device_info_handler(
        device_info_payload(software_ver_id=None, description=None)
    )

    updated = device_registry.async_get(device.id)
    assert updated is not None
    assert updated.sw_version is None
    assert updated.model_id is None
