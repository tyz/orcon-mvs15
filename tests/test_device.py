"""Tests for the device registry helpers."""

from __future__ import annotations

from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceRegistry

from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.orcon_mvs15.const import DOMAIN
from custom_components.orcon_mvs15.device import (
    async_get_or_create_gateway,
    attached_device_info,
    co2_device_info,
    fan_device_info,
    gateway_device_info,
    update_device_info,
    update_gateway_version,
)
from custom_components.orcon_mvs15.ramses_packet import RamsesID

GATEWAY_ID = RamsesID("18:149960")
FAN_ID = RamsesID("29:224547")
CO2_ID = RamsesID("29:163058")


def make_entry(hass: HomeAssistant) -> MockConfigEntry:
    """Register a config entry for the device lookups."""
    entry = MockConfigEntry(domain=DOMAIN, data={})
    entry.add_to_hass(hass)
    return entry


def test_gateway_device_info() -> None:
    """The gateway is the Rameses ESP stick."""
    info = gateway_device_info(GATEWAY_ID)

    assert info["identifiers"] == {(DOMAIN, GATEWAY_ID)}
    assert info["manufacturer"] == "Indalo-Tech"
    assert info["model"] == "RAMSES_ESP"
    assert info["name"] == f"Indalo-Tech RAMSES_ESP ({GATEWAY_ID})"


def test_attached_device_info_does_not_change_the_device() -> None:
    """An attached entity only identifies its device."""
    info = attached_device_info(FAN_ID)

    assert info == {"identifiers": {(DOMAIN, FAN_ID)}}


async def test_fan_device_info_links_to_the_gateway(
    hass: HomeAssistant, device_registry: DeviceRegistry
) -> None:
    """The fan is connected through the gateway device."""
    entry = make_entry(hass)
    gateway = async_get_or_create_gateway(hass, entry.entry_id, GATEWAY_ID)

    info = fan_device_info(hass, entry.entry_id, GATEWAY_ID, FAN_ID)

    assert info["identifiers"] == {(DOMAIN, FAN_ID)}
    assert info["manufacturer"] == "Orcon"
    assert info["model"] == "MVS-15"
    assert info["name"] == f"Orcon MVS-15 fan ({FAN_ID})"
    assert info["via_device_id"] == gateway.id


async def test_co2_device_info_links_to_the_gateway(
    hass: HomeAssistant, device_registry: DeviceRegistry
) -> None:
    """The CO2 remote is connected through the gateway device."""
    entry = make_entry(hass)
    gateway = async_get_or_create_gateway(hass, entry.entry_id, GATEWAY_ID)

    info = co2_device_info(hass, entry.entry_id, GATEWAY_ID, CO2_ID)

    assert info["identifiers"] == {(DOMAIN, CO2_ID)}
    assert info["manufacturer"] == "Orcon"
    assert info["model"] == "MVS-15RH CO2B"
    assert info["via_device_id"] == gateway.id


async def test_device_info_without_a_registered_gateway(
    hass: HomeAssistant,
) -> None:
    """A missing gateway must not fabricate a via-device id."""
    entry = make_entry(hass)

    info = fan_device_info(hass, entry.entry_id, GATEWAY_ID, FAN_ID)

    assert info.get("via_device_id") is None


async def test_gateway_device_is_created_once(
    hass: HomeAssistant, device_registry: DeviceRegistry
) -> None:
    """Repeated setup returns the same gateway device."""
    entry = make_entry(hass)

    first = async_get_or_create_gateway(hass, entry.entry_id, GATEWAY_ID)
    second = async_get_or_create_gateway(hass, entry.entry_id, GATEWAY_ID)

    assert first.id == second.id
    assert second.manufacturer == "Indalo-Tech"
    assert second.model == "RAMSES_ESP"


async def test_update_gateway_version(
    hass: HomeAssistant, device_registry: DeviceRegistry
) -> None:
    """The firmware topic updates the gateway device."""
    entry = make_entry(hass)
    gateway = async_get_or_create_gateway(hass, entry.entry_id, GATEWAY_ID)

    update_gateway_version(hass, entry.entry_id, GATEWAY_ID, "2026.10.1")

    updated = device_registry.async_get(gateway.id)
    assert updated is not None
    assert updated.sw_version == "2026.10.1"


async def test_update_gateway_version_ignores_an_unknown_gateway(
    hass: HomeAssistant,
) -> None:
    """A version message before the gateway exists is not an error."""
    entry = make_entry(hass)

    update_gateway_version(hass, entry.entry_id, GATEWAY_ID, "2026.10.1")


async def test_update_device_info(
    hass: HomeAssistant, device_registry: DeviceRegistry
) -> None:
    """Decoded 10E0 values are stored on the matching device."""
    entry = make_entry(hass)
    device = device_registry.async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={(DOMAIN, FAN_ID)},
    )

    updated = update_device_info(
        hass, entry.entry_id, FAN_ID, software_ver_id="2A", description="Orcon MVS-15"
    )

    assert updated is True
    stored = device_registry.async_get(device.id)
    assert stored is not None
    assert stored.sw_version == "42"
    assert stored.model_id == "Orcon MVS-15"


async def test_update_device_info_ignores_an_unknown_device(
    hass: HomeAssistant,
) -> None:
    """Device info for an unregistered device is dropped quietly."""
    entry = make_entry(hass)

    updated = update_device_info(
        hass, entry.entry_id, FAN_ID, software_ver_id="2A", description="Orcon MVS-15"
    )

    assert updated is False
