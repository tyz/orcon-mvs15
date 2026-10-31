"""Tests for the MQTT transport and gateway discovery."""

from __future__ import annotations

import asyncio

from collections.abc import Callable
from unittest.mock import Mock

import pytest
from homeassistant.components.mqtt import ReceiveMessage
from homeassistant.core import HomeAssistant

from custom_components.orcon_mvs15 import mqtt as mqtt_module
from custom_components.orcon_mvs15.mqtt import MQTT, MQTTException
from custom_components.orcon_mvs15.ramses_packet import RamsesID

GATEWAY_ID = "18:149960"
MQTT_TOPIC = "RAMSES/GATEWAY"


def online_message(topic: str) -> ReceiveMessage:
    """Build the wildcard message a Rameses ESP publishes on boot."""
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
