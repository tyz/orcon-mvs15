"""Tests for the Ramses ESP session."""

from __future__ import annotations

from unittest.mock import AsyncMock, Mock

import pytest
from homeassistant.components.mqtt import ReceiveMessage
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.device_registry import DeviceRegistry

from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.orcon_mvs15 import ramses_esp as ramses_esp_module
from custom_components.orcon_mvs15.codes import Code12a0
from custom_components.orcon_mvs15.const import (
    CONF_MQTT_TOPIC,
    CONF_REMOTE_ID,
    DOMAIN,
)
from custom_components.orcon_mvs15.mqtt import MQTTException
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
    assert session.pending_packets == 1
    assert packet.expected_response is not None
    assert packet.expected_response.cancel_retry_handler is cancel_retry


async def test_handled_codes_reports_the_registered_handlers(
    hass: HomeAssistant,
) -> None:
    """Diagnostics see which packet codes the session handles."""
    session = make_session(hass)

    assert session.handled_codes == set()

    session.add_handler("31D9", Mock())

    assert session.handled_codes == {"31D9"}


async def test_init_fan_starts_humidity_polling(
    hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch
) -> None:
    """12A0 is not broadcast, so polling must not depend on a response."""
    track = Mock(return_value=Mock())
    monkeypatch.setattr(ramses_esp_module, "async_track_time_interval", track)
    session = make_session(hass)
    session.publish = AsyncMock()

    await session.init_fan(discovered_fan_id=RamsesID(FAN_ID))

    track.assert_called_once()
    assert track.call_args.args[1] == session.req_humidity


async def test_humidity_polling_starts_once_and_is_cleaned_up(
    hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Repeated fan setup does not add intervals, and cleanup removes it."""
    unsub = Mock()
    track = Mock(return_value=unsub)
    monkeypatch.setattr(ramses_esp_module, "async_track_time_interval", track)
    session = make_session(hass)
    session.publish = AsyncMock()

    await session.init_fan(discovered_fan_id=RamsesID(FAN_ID))
    await session.init_fan(discovered_fan_id=RamsesID(FAN_ID))
    session.cleanup()

    track.assert_called_once()
    unsub.assert_called_once_with()


async def test_set_preset_mode_rejects_an_unknown_mode(hass: HomeAssistant) -> None:
    """An unknown preset is a user error, not a silent no-op."""
    session = make_session(hass)

    with pytest.raises(HomeAssistantError, match="Turbo"):
        await session.set_preset_mode("Turbo")


async def test_set_preset_mode_reports_a_publish_failure(hass: HomeAssistant) -> None:
    """A failed command must reach the caller so Home Assistant can report it."""
    session = make_session(hass)

    class FailingMQTT:
        async def publish(self, packet: RamsesPacket) -> None:
            raise MQTTException("broker is offline")

    session.mqtt = FailingMQTT()  # pytest stub, duck typed on purpose

    with pytest.raises(HomeAssistantError, match="broker is offline"):
        await session.set_preset_mode("Low")

    assert len(session._send_queue) == 0
