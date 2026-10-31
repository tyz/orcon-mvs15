"""Tests for the Ramses ESP session."""

from __future__ import annotations

from unittest.mock import Mock

import pytest
from homeassistant.components.mqtt import ReceiveMessage
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceRegistry

from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.orcon_mvs15 import ramses_esp as ramses_esp_module
from custom_components.orcon_mvs15.codes import Code12a0
from custom_components.orcon_mvs15.const import (
    CONF_MQTT_TOPIC,
    CONF_REMOTE_ID,
    DOMAIN,
)
from custom_components.orcon_mvs15.ramses_esp import RamsesESP
from custom_components.orcon_mvs15.ramses_packet import RamsesID, RamsesPacket

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


class RecordingMQTT:
    """Record whether a packet was already queued when it was published."""

    def __init__(self, session: RamsesESP) -> None:
        self.session = session
        self.published: list[RamsesPacket] = []
        self.queued_at_publish: list[bool] = []

    async def publish(self, packet: RamsesPacket) -> None:
        self.queued_at_publish.append(packet in self.session._send_queue)
        self.published.append(packet)


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


async def test_packet_is_queued_before_it_is_published(
    hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A fast response must find the packet in the retry queue."""
    cancel_retry = Mock()
    monkeypatch.setattr(
        ramses_esp_module, "async_call_later", Mock(return_value=cancel_retry)
    )
    session = make_session(hass)
    mqtt = RecordingMQTT(session)
    session.mqtt = mqtt  # pytest stub, duck typed on purpose
    packet = Code12a0.get(RamsesID(GATEWAY_ID), RamsesID(FAN_ID))

    await session.publish(packet)

    assert mqtt.queued_at_publish == [True]
    assert mqtt.published == [packet]
    assert packet in session._send_queue
    assert packet.expected_response is not None
    assert packet.expected_response.cancel_retry_handler is cancel_retry
