"""Tests for entity names and availability."""

from __future__ import annotations

from types import ModuleType
from unittest.mock import AsyncMock, Mock

import pytest
from homeassistant.const import EntityCategory
from homeassistant.core import CoreState, HomeAssistant

from pytest_homeassistant_custom_component.common import MockConfigEntry

import custom_components.orcon_mvs15.binary_sensor as binary_sensor_module
import custom_components.orcon_mvs15.fan as fan_module
import custom_components.orcon_mvs15.sensor as sensor_module
from custom_components.orcon_mvs15.binary_sensor import FaultBinarySensor
from custom_components.orcon_mvs15.const import CONF_MQTT_TOPIC, DOMAIN
from custom_components.orcon_mvs15.coordinator import (
    OrconMVS15DataUpdateCoordinator,
)
from custom_components.orcon_mvs15.fan import OrconFan
from custom_components.orcon_mvs15.models import OrconMVS15Config
from custom_components.orcon_mvs15.ramses_packet import RamsesID
from custom_components.orcon_mvs15.sensor import (
    Co2Sensor,
    HumiditySensor,
    SignalStrengthSensor,
)

FAN_ID = RamsesID("29:224547")
MQTT_TOPIC = "RAMSES/GATEWAY"


def make_coordinator(hass: HomeAssistant) -> OrconMVS15DataUpdateCoordinator:
    """Build an empty push coordinator for an entry."""
    entry = MockConfigEntry(domain=DOMAIN, data={CONF_MQTT_TOPIC: MQTT_TOPIC})
    entry.add_to_hass(hass)
    coordinator = OrconMVS15DataUpdateCoordinator(hass, entry)
    coordinator.data = {}
    return coordinator


@pytest.mark.parametrize(
    ("entity_class", "discovery_key", "data_key", "value", "translation_key"),
    [
        (OrconFan, "fan", "fan_mode", "low", "fan_states"),
        (Co2Sensor, "co2", "co2", 800, "co2"),
        (HumiditySensor, "humidity", "relative_humidity", 55, "humidity"),
        (SignalStrengthSensor, "fan", "fan_signal_strength", -68, "signal_strength"),
        (SignalStrengthSensor, "co2", "co2_signal_strength", -70, "signal_strength"),
        (FaultBinarySensor, "fan", "fan_fault", False, "fault"),
    ],
)
async def test_entity_is_unavailable_until_its_data_arrives(
    hass: HomeAssistant,
    entity_class: type,
    discovery_key: str,
    data_key: str,
    value: object,
    translation_key: str,
) -> None:
    """No state means unavailable, not an optimistic default."""
    coordinator = make_coordinator(hass)
    entity = entity_class(
        hass=hass,
        ramses_id=FAN_ID,
        config=OrconMVS15Config(mqtt_topic=MQTT_TOPIC),
        coordinator=coordinator,
        ramses_esp=Mock(),
        discovery_key=discovery_key,
    )

    assert entity.has_entity_name is True
    assert entity.translation_key == translation_key
    assert entity.available is False

    coordinator.data = {data_key: value}

    assert entity.available is True


async def test_entities_follow_the_coordinator_availability(
    hass: HomeAssistant,
) -> None:
    """A lost MQTT connection makes pushed entities unavailable."""
    coordinator = make_coordinator(hass)
    coordinator.data = {"fan_mode": "low"}
    entity = OrconFan(
        hass=hass,
        ramses_id=FAN_ID,
        config=OrconMVS15Config(mqtt_topic=MQTT_TOPIC),
        coordinator=coordinator,
        ramses_esp=Mock(),
        discovery_key="fan",
    )

    assert entity.available is True

    coordinator.async_set_available(False)
    assert entity.available is False

    coordinator.async_set_available(True)
    assert entity.available is True


async def test_push_coordinator_keeps_the_data_it_was_given(
    hass: HomeAssistant,
) -> None:
    """A refresh never polls; it returns the pushed data it already has."""
    coordinator = make_coordinator(hass)

    assert await coordinator._async_update_data() == {}

    coordinator.data = {"fan_mode": "low"}

    assert await coordinator._async_update_data() == {"fan_mode": "low"}


async def test_unchanged_availability_does_not_notify_listeners(
    hass: HomeAssistant,
) -> None:
    """Repeating the current connection state is not a state change."""
    coordinator = make_coordinator(hass)
    listener = Mock()
    coordinator.async_add_listener(listener)

    coordinator.async_set_available(True)

    listener.assert_not_called()

    coordinator.async_set_available(False)

    listener.assert_called_once_with()


def test_signal_strength_is_a_diagnostic_entity(hass: HomeAssistant) -> None:
    """Signal strength describes the radio link, not the fan's function."""
    entity = SignalStrengthSensor(
        hass=hass,
        ramses_id=FAN_ID,
        config=OrconMVS15Config(mqtt_topic=MQTT_TOPIC),
        coordinator=make_coordinator(hass),
        ramses_esp=Mock(),
        discovery_key="fan",
    )

    assert entity.entity_category is EntityCategory.DIAGNOSTIC


@pytest.mark.parametrize("module", [fan_module, sensor_module, binary_sensor_module])
def test_platforms_declare_parallel_updates(module: ModuleType) -> None:
    """Every platform states how many entity calls may run at once."""
    assert module.PARALLEL_UPDATES == 0


def make_fan(hass: HomeAssistant, ramses_esp: Mock | None = None) -> OrconFan:
    """Build a fan entity without adding it to a platform."""
    return OrconFan(
        hass=hass,
        ramses_id=FAN_ID,
        config=OrconMVS15Config(mqtt_topic=MQTT_TOPIC),
        coordinator=make_coordinator(hass),
        ramses_esp=ramses_esp or Mock(),
        discovery_key="fan",
    )


async def test_fan_command_is_forwarded_to_the_session(
    hass: HomeAssistant,
) -> None:
    """A preset change is a session command, not local-only state."""
    ramses_esp = Mock()
    ramses_esp.set_preset_mode = AsyncMock()
    entity = make_fan(hass, ramses_esp)

    await entity.async_set_preset_mode("high")

    ramses_esp.set_preset_mode.assert_awaited_once_with("high")


async def test_fan_update_tracks_the_mode_and_fault(hass: HomeAssistant) -> None:
    """31D9 drives both the preset and the fault attribute."""
    entity = make_fan(hass)
    entity.async_write_ha_state = Mock()
    entity.coordinator.data = {"fan_mode": "high", "fan_fault": True}

    entity._handle_coordinator_update()

    assert entity.preset_mode == "high"
    assert entity.extra_state_attributes["fan_fault"] is True
    entity.async_write_ha_state.assert_called_once_with()


def make_co2_sensor(hass: HomeAssistant, ramses_esp: Mock | None = None) -> Co2Sensor:
    """Build a CO2 sensor without adding it to a platform."""
    return Co2Sensor(
        hass=hass,
        ramses_id=FAN_ID,
        config=OrconMVS15Config(mqtt_topic=MQTT_TOPIC),
        coordinator=make_coordinator(hass),
        ramses_esp=ramses_esp or Mock(),
        discovery_key="co2",
    )


async def test_co2_sensor_fetches_its_state_when_added_while_running(
    hass: HomeAssistant,
) -> None:
    """A sensor created after startup requests its own 1298 payload."""
    hass.set_state(CoreState.running)
    ramses_esp = Mock()
    ramses_esp.init_co2 = AsyncMock()
    entity = make_co2_sensor(hass, ramses_esp)
    entity.hass = hass

    await entity.async_added_to_hass()

    ramses_esp.init_co2.assert_awaited_once_with(discovered_co2_id=FAN_ID)


async def test_co2_update_tracks_the_level_and_vent_demand(
    hass: HomeAssistant,
) -> None:
    """The CO2 sensor exposes both the concentration and the vent demand."""
    entity = make_co2_sensor(hass)
    entity.async_write_ha_state = Mock()
    entity.coordinator.data = {"co2": 800, "vent_demand": 40}

    entity._handle_coordinator_update()

    assert entity.native_value == 800
    assert entity.extra_state_attributes["vent_demand"] == 40
    entity.async_write_ha_state.assert_called_once_with()


async def test_humidity_update_tracks_the_level(hass: HomeAssistant) -> None:
    """A 12A0 response updates the humidity sensor."""
    entity = HumiditySensor(
        hass=hass,
        ramses_id=FAN_ID,
        config=OrconMVS15Config(mqtt_topic=MQTT_TOPIC),
        coordinator=make_coordinator(hass),
        ramses_esp=Mock(),
        discovery_key="humidity",
    )
    entity.async_write_ha_state = Mock()
    entity.coordinator.data = {"relative_humidity": 55}

    entity._handle_coordinator_update()

    assert entity.native_value == 55
    entity.async_write_ha_state.assert_called_once_with()


async def test_signal_strength_update_tracks_the_radio_level(
    hass: HomeAssistant,
) -> None:
    """A packet from the fan updates the fan's signal strength sensor."""
    entity = SignalStrengthSensor(
        hass=hass,
        ramses_id=FAN_ID,
        config=OrconMVS15Config(mqtt_topic=MQTT_TOPIC),
        coordinator=make_coordinator(hass),
        ramses_esp=Mock(),
        discovery_key="fan",
    )
    entity.async_write_ha_state = Mock()
    entity.coordinator.data = {"fan_signal_strength": -68}

    entity._handle_coordinator_update()

    assert entity.native_value == -68
    entity.async_write_ha_state.assert_called_once_with()
