"""Tests for entity names and availability."""

from __future__ import annotations

from types import ModuleType
from unittest.mock import Mock

import pytest
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant

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
