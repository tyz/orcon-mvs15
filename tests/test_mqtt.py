"""Tests for the MQTT transport and gateway discovery."""

from __future__ import annotations

import asyncio
import json
import logging

from collections.abc import Callable
from unittest.mock import Mock

import pytest
from homeassistant.components.mqtt import ReceiveMessage
from homeassistant.core import HomeAssistant

from custom_components.orcon_mvs15 import mqtt as mqtt_module
from custom_components.orcon_mvs15.mqtt import MQTT, MQTTException
from custom_components.orcon_mvs15.ramses_packet import RamsesID, RamsesPacket

GATEWAY_ID = "18:149960"
FAN_ID = "29:224547"
MQTT_TOPIC = "RAMSES/GATEWAY"


def online_message(topic: str) -> ReceiveMessage:
    """Build the wildcard message a Ramses ESP publishes on boot."""
    return ReceiveMessage(
        topic=topic,
        payload=b"online",
        qos=0,
        retain=False,
        subscribed_topic=f"{MQTT_TOPIC}/+",
        timestamp=0.0,
    )


async def test_gateway_discovery_times_out(
    hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Setup must not wait forever when no gateway ever publishes."""
    unsub = Mock()
    subscribe = Mock(return_value=unsub)

    async def fake_subscribe(
        hass: HomeAssistant, topic: str, handler: Callable
    ) -> Callable[[], None]:
        return subscribe(hass, topic, handler)

    monkeypatch.setattr(mqtt_module.mqtt, "async_subscribe", fake_subscribe)
    transport = MQTT(hass, MQTT_TOPIC, discovery_timeout=0.01)

    with pytest.raises(MQTTException, match="gateway"):
        await transport.init()

    subscribe.assert_called_once()
    unsub.assert_called_once_with()
    assert transport._mqtt_unsubs == []


async def test_gateway_discovery_subscribes_to_the_gateway_topics(
    hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The first wildcard message selects the gateway and its topics."""
    subscriptions: list[tuple[str, Callable]] = []
    wildcard_unsub = Mock()

    async def fake_subscribe(
        hass: HomeAssistant, topic: str, handler: Callable
    ) -> Callable[[], None]:
        subscriptions.append((topic, handler))
        return wildcard_unsub

    monkeypatch.setattr(mqtt_module.mqtt, "async_subscribe", fake_subscribe)
    transport = MQTT(hass, MQTT_TOPIC, discovery_timeout=1)
    task = hass.async_create_task(transport.init())
    for _ in range(10):
        if subscriptions:
            break
        await asyncio.sleep(0)

    assert subscriptions[0][0] == f"{MQTT_TOPIC}/+"

    await subscriptions[0][1](online_message(f"{MQTT_TOPIC}/{GATEWAY_ID}"))
    await task

    assert transport.gateway_id == GATEWAY_ID
    assert transport.sub_topic == f"{MQTT_TOPIC}/{GATEWAY_ID}/rx"
    assert transport.pub_topic == f"{MQTT_TOPIC}/{GATEWAY_ID}/tx"
    assert transport.version_topic == f"{MQTT_TOPIC}/{GATEWAY_ID}/info/version"
    wildcard_unsub.assert_called_once_with()


async def test_connection_transitions_are_logged_once(
    hass: HomeAssistant,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Each lost and restored connection is reported exactly once."""
    connection_callbacks: list[Callable[[bool], None]] = []
    status_unsub = Mock()

    async def fake_subscribe(
        hass: HomeAssistant, topic: str, handler: Callable
    ) -> Callable[[], None]:
        return Mock()

    def fake_connection_status(
        hass_: HomeAssistant, callback: Callable[[bool], None]
    ) -> Callable[[], None]:
        connection_callbacks.append(callback)
        return status_unsub

    monkeypatch.setattr(mqtt_module.mqtt, "async_subscribe", fake_subscribe)
    monkeypatch.setattr(
        mqtt_module.mqtt,
        "async_subscribe_connection_status",
        fake_connection_status,
    )
    monkeypatch.setattr(mqtt_module.mqtt, "is_connected", lambda hass_: True)
    observed: list[bool] = []
    transport = MQTT(
        hass,
        MQTT_TOPIC,
        gateway_id=RamsesID(GATEWAY_ID),
        connection_callback=observed.append,
    )
    await transport.init()
    await transport.setup(Mock(), Mock())

    assert len(connection_callbacks) == 1
    with caplog.at_level(logging.INFO):
        connection_callbacks[0](False)
        connection_callbacks[0](False)
        connection_callbacks[0](True)
        connection_callbacks[0](True)

    assert observed == [False, True]
    assert caplog.text.count("MQTT connection lost") == 1
    assert caplog.text.count("MQTT connection restored") == 1

    transport.cleanup()
    status_unsub.assert_called_once_with()


async def test_configured_gateway_skips_discovery(
    hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A stored gateway id is used without subscribing to the wildcard."""
    subscribe = Mock()

    async def fake_subscribe(
        hass: HomeAssistant, topic: str, handler: Callable
    ) -> Callable[[], None]:
        subscribe(hass, topic, handler)
        return Mock()

    monkeypatch.setattr(mqtt_module.mqtt, "async_subscribe", fake_subscribe)
    transport = MQTT(hass, MQTT_TOPIC, gateway_id=RamsesID(GATEWAY_ID))

    await transport.init()

    subscribe.assert_not_called()
    assert transport.gateway_id == GATEWAY_ID
    assert transport.sub_topic == f"{MQTT_TOPIC}/{GATEWAY_ID}/rx"


async def test_online_message_is_ignored_when_the_gateway_is_known(
    hass: HomeAssistant,
) -> None:
    """A second gateway on the wildcard topic must not replace the stored one."""
    transport = MQTT(hass, MQTT_TOPIC, gateway_id=RamsesID(GATEWAY_ID))

    await transport._handle_online_message(online_message(f"{MQTT_TOPIC}/18:999999"))

    assert transport.gateway_id == GATEWAY_ID
    assert not transport._online_event.is_set()


def make_packet() -> RamsesPacket:
    """Build an outgoing request."""
    return RamsesPacket(
        src_id=RamsesID(GATEWAY_ID),
        dst_id=RamsesID(FAN_ID),
        type="RQ",
        code="12A0",
        data="00",
    )


async def test_publish_sends_the_packet_envelope(
    hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Publishing puts the gateway envelope JSON on the tx topic."""
    published: list[tuple[str, str]] = []

    async def fake_publish(hass_: HomeAssistant, topic: str, payload: str) -> None:
        published.append((topic, payload))

    monkeypatch.setattr(mqtt_module.mqtt, "async_publish", fake_publish)
    transport = MQTT(hass, MQTT_TOPIC, gateway_id=RamsesID(GATEWAY_ID))
    await transport.init()
    packet = make_packet()

    await transport.publish(packet)

    assert published == [
        (f"{MQTT_TOPIC}/{GATEWAY_ID}/tx", json.dumps(packet.ramses_esp_envelope()))
    ]


async def test_publish_wraps_transport_errors(
    hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A broker failure becomes an MQTTException for the caller."""

    async def failing_publish(hass_: HomeAssistant, topic: str, payload: str) -> None:
        raise RuntimeError("broker is offline")

    monkeypatch.setattr(mqtt_module.mqtt, "async_publish", failing_publish)
    transport = MQTT(hass, MQTT_TOPIC, gateway_id=RamsesID(GATEWAY_ID))
    await transport.init()

    with pytest.raises(MQTTException, match="broker is offline"):
        await transport.publish(make_packet())
