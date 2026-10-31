"""Tests for the Ramses ESP session."""

from __future__ import annotations

from unittest.mock import Mock

from homeassistant.components.mqtt import ReceiveMessage
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceRegistry

from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.orcon_mvs15.const import (
    CONF_MQTT_TOPIC,
    CONF_REMOTE_ID,
    DOMAIN,
)
from custom_components.orcon_mvs15.ramses_esp import RamsesESP
from custom_components.orcon_mvs15.ramses_packet import RamsesID

GATEWAY_ID = "18:149960"
FAN_ID = "29:224547"
REMOTE_ID = "29:163058"
MQTT_TOPIC = "RAMSES/GATEWAY"


def make_session(hass: HomeAssistant, config_entry_id: str = "test_entry") -> RamsesESP:
    """Build a session without an MQTT connection."""
    return RamsesESP(
        hass=hass,
        mqtt=Mock(),
        remote_id=RamsesID(REMOTE_ID),
        fan_id=RamsesID(FAN_ID),
        co2_id=RamsesID(),
        gateway_id=RamsesID(GATEWAY_ID),
        config_entry_id=config_entry_id,
    )


async def test_version_message_updates_the_gateway_device(
    hass: HomeAssistant, device_registry: DeviceRegistry
) -> None:
    """The gateway firmware version belongs to the gateway device."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_REMOTE_ID: REMOTE_ID, CONF_MQTT_TOPIC: MQTT_TOPIC},
    )
    entry.add_to_hass(hass)
    device = device_registry.async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={(DOMAIN, GATEWAY_ID)},
    )
    session = make_session(hass, entry.entry_id)
    msg = ReceiveMessage(
        topic=f"{MQTT_TOPIC}/{GATEWAY_ID}/info/version",
        payload=b"2026.10.1",
        qos=0,
        retain=False,
        subscribed_topic=f"{MQTT_TOPIC}/{GATEWAY_ID}/info/version",
        timestamp=0.0,
    )

    await session.handle_ramses_mqtt_version_message(msg)

    updated = device_registry.async_get(device.id)
    assert updated is not None
    assert updated.sw_version == "2026.10.1"
