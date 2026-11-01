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
from custom_components.orcon_mvs15.ramses_packet import RamsesID

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


async def test_vmc_device_info_updates_the_registered_device(
    hass: HomeAssistant, device_registry: DeviceRegistry
) -> None:
    """The VMC-15RPS34 reports product 5F and is still an Orcon fan."""
    entry, handlers = make_entry_handlers(hass)
    device = device_registry.async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={(DOMAIN, FAN_ID)},
    )

    handlers._device_info_handler(
        device_info_payload(
            product_id="5F",
            software_ver_id="0E",
            description="VMC-15RPS34",
        )
    )

    updated = device_registry.async_get(device.id)
    assert updated is not None
    assert updated.sw_version == "14"
    assert updated.model_id == "VMC-15RPS34"


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


async def test_unknown_product_id_is_ignored(
    hass: HomeAssistant,
    device_registry: DeviceRegistry,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A known manufacturer with an unknown product is not an MVS-15."""
    entry, handlers = make_entry_handlers(hass)
    device = device_registry.async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={(DOMAIN, FAN_ID)},
    )

    with caplog.at_level(logging.WARNING):
        handlers._device_info_handler(device_info_payload(product_id="99"))

    assert "99" in caplog.text
    updated = device_registry.async_get(device.id)
    assert updated is not None
    assert updated.model_id is None


class RecordingCoordinator:
    """Coordinator stand-in that keeps the data it is given."""

    def __init__(self) -> None:
        self.data: dict[str, object] = {}

    def async_set_updated_data(self, data: dict[str, object]) -> None:
        self.data = data


def make_recording_handlers(hass: HomeAssistant) -> DataHandlers:
    """Build handlers whose coordinators record pushed data."""
    entry = SimpleNamespace(
        runtime_data=SimpleNamespace(
            co2_coordinator=RecordingCoordinator(),
            fan_coordinator=RecordingCoordinator(),
        )
    )
    return DataHandlers(hass, entry)


def test_powerup_handler_stores_the_announced_fan(
    hass: HomeAssistant,
) -> None:
    """042F announces the fan ID and the strength of the startup broadcast."""
    handlers = make_recording_handlers(hass)
    payload = SimpleNamespace(
        values={"signal_strength": -61},
        packet=SimpleNamespace(ann_id=FAN_ID),
    )

    handlers._powerup_handler(payload)

    assert handlers.fan_coordinator.data == {
        "discovered_fan_id": FAN_ID,
        "fan_signal_strength": -61,
    }


def test_powerup_handler_falls_back_to_the_sender(hass: HomeAssistant) -> None:
    """A 042F without an announced ID still names the fan as its sender."""
    handlers = make_recording_handlers(hass)
    payload = SimpleNamespace(
        values={"signal_strength": -61},
        packet=SimpleNamespace(ann_id=RamsesID(), src_id=RamsesID(FAN_ID)),
    )

    handlers._powerup_handler(payload)

    assert handlers.fan_coordinator.data["discovered_fan_id"] == FAN_ID


def test_fan_state_handler_stores_mode_fault_and_signal(
    hass: HomeAssistant,
) -> None:
    """31D9 updates the mode, the fault flag and the radio signal."""
    handlers = make_recording_handlers(hass)
    handlers.fan_coordinator.data = {"relative_humidity": 47}
    payload = SimpleNamespace(
        values={"fan_mode": "low", "has_fault": False, "signal_strength": -60},
        packet=SimpleNamespace(src_id=FAN_ID),
    )

    handlers._fan_state_handler(payload)

    assert handlers.fan_coordinator.data == {
        "relative_humidity": 47,
        "fan_mode": "low",
        "fan_fault": False,
        "fan_signal_strength": -60,
        "discovered_fan_id": FAN_ID,
    }


def test_humidity_handler_stores_level_and_signal(hass: HomeAssistant) -> None:
    """12A0 updates the humidity sensor and the fan's signal strength."""
    handlers = make_recording_handlers(hass)
    payload = SimpleNamespace(
        values={"level": 47, "signal_strength": -44},
        packet=SimpleNamespace(src_id=FAN_ID),
    )

    handlers._relative_humidity_handler(payload)

    assert handlers.fan_coordinator.data == {
        "relative_humidity": 47,
        "fan_signal_strength": -44,
        "discovered_humidity_id": FAN_ID,
        "discovered_fan_id": FAN_ID,
    }


def test_co2_handler_stores_level_and_signal(hass: HomeAssistant) -> None:
    """1298 updates the CO2 sensor and its signal strength."""
    handlers = make_recording_handlers(hass)
    payload = SimpleNamespace(
        values={"level": 461, "signal_strength": -50},
        packet=SimpleNamespace(src_id=FAN_ID),
    )

    handlers._co2_handler(payload)

    assert handlers.co2_coordinator.data == {
        "co2": 461,
        "co2_signal_strength": -50,
    }


def test_vent_demand_handler_stores_percentage_and_signal(
    hass: HomeAssistant,
) -> None:
    """31E0 updates the vent demand attribute of the CO2 sensor."""
    handlers = make_recording_handlers(hass)
    payload = SimpleNamespace(
        values={"percentage": 50, "unknown": "1E", "signal_strength": -45},
        packet=SimpleNamespace(src_id=FAN_ID),
    )

    handlers._vent_demand_handler(payload)

    assert handlers.co2_coordinator.data == {
        "vent_demand": 50,
        "co2_signal_strength": -45,
        "discovered_co2_id": FAN_ID,
    }
