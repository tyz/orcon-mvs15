"""Tests for the Home Assistant MQTT backend and the Ramses ESP transport."""

from __future__ import annotations

import asyncio
import json
import logging

from collections.abc import Callable
from unittest.mock import AsyncMock, Mock

import pytest
from homeassistant.components.mqtt import ReceiveMessage
from homeassistant.core import HomeAssistant

from custom_components.orcon_mvs15 import mqtt as mqtt_module
from custom_components.orcon_mvs15.mqtt import HassMqttBackend
from custom_components.orcon_mvs15.ramses.protocol import RamsesID, RamsesPacket
from custom_components.orcon_mvs15.ramses.transport import (
    ConnectionState,
    TransportError,
    TransportNotReady,
)
from custom_components.orcon_mvs15.ramses.transport.ramses_esp import RamsesESP

GATEWAY_ID = "18:149960"
FAN_ID = "29:224547"
MQTT_TOPIC = "RAMSES/GATEWAY"


def make_transport(
    hass: HomeAssistant,
    gateway_id: str = "",
    discovery_timeout: float = 10.0,
) -> RamsesESP:
    """Build the transport on top of Home Assistant's MQTT client."""
    return RamsesESP(
        HassMqttBackend(hass),
        MQTT_TOPIC,
        gateway_id=RamsesID(gateway_id),
        discovery_timeout=discovery_timeout,
    )


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
    transport = make_transport(hass, discovery_timeout=0.01)

    with pytest.raises(TransportError, match="gateway"):
        await transport.init()

    subscribe.assert_called_once()
    unsub.assert_called_once_with()


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
    transport = make_transport(hass, discovery_timeout=1)
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
    monkeypatch.setattr(
        mqtt_module.mqtt, "async_wait_for_mqtt_client", AsyncMock(return_value=True)
    )
    monkeypatch.setattr(mqtt_module.mqtt, "is_connected", lambda hass_: True)
    observed: list[ConnectionState] = []
    transport = make_transport(hass, gateway_id=GATEWAY_ID)
    transport.subscribe_connection(observed.append)
    await transport.init()
    await transport.start(Mock())

    assert len(connection_callbacks) == 1
    with caplog.at_level(logging.INFO):
        connection_callbacks[0](False)
        connection_callbacks[0](False)
        connection_callbacks[0](True)
        connection_callbacks[0](True)

    assert observed == [ConnectionState.DISCONNECTED, ConnectionState.CONNECTED]
    assert caplog.text.count("MQTT connection lost") == 1
    assert caplog.text.count("MQTT connection restored") == 1

    await transport.stop()
    status_unsub.assert_called_once_with()


def gateway_status(payload: bytes, topic: str) -> ReceiveMessage:
    """Build a retained message the gateway publishes on its own topic."""
    return ReceiveMessage(
        topic=topic,
        payload=payload,
        qos=1,
        retain=True,
        subscribed_topic=topic,
        timestamp=0.0,
    )


async def test_the_gateway_last_will_is_subscribed(
    hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The retained online/offline topic becomes the gateway's availability."""
    subscriptions: dict[str, Callable] = {}

    async def fake_subscribe(
        hass_: HomeAssistant, topic: str, handler: Callable
    ) -> Callable[[], None]:
        subscriptions[topic] = handler
        return Mock()

    monkeypatch.setattr(mqtt_module.mqtt, "async_subscribe", fake_subscribe)
    monkeypatch.setattr(
        mqtt_module.mqtt,
        "async_subscribe_connection_status",
        Mock(return_value=Mock()),
    )
    monkeypatch.setattr(
        mqtt_module.mqtt, "async_wait_for_mqtt_client", AsyncMock(return_value=True)
    )
    monkeypatch.setattr(mqtt_module.mqtt, "is_connected", lambda hass_: True)
    transport = make_transport(hass, gateway_id=GATEWAY_ID)
    await transport.init()
    observed: list[ConnectionState] = []
    transport.subscribe_connection(observed.append)

    await transport.start(Mock())

    assert transport.lwt_topic == f"{MQTT_TOPIC}/{GATEWAY_ID}"
    assert set(subscriptions) == {
        transport.sub_topic,
        transport.version_topic,
        transport.latest_topic,
        transport.lwt_topic,
    }
    handler = subscriptions[transport.lwt_topic]

    await handler(gateway_status(b"offline", transport.lwt_topic))
    assert transport.connection_state is ConnectionState.DISCONNECTED

    await handler(gateway_status(b"online", transport.lwt_topic))
    assert transport.connection_state is ConnectionState.CONNECTED

    await handler(gateway_status(b"offline", transport.lwt_topic))
    await handler(gateway_status(b"offline", transport.lwt_topic))
    assert observed == [
        ConnectionState.DISCONNECTED,
        ConnectionState.CONNECTED,
        ConnectionState.DISCONNECTED,
    ]

    await transport.stop()


async def test_the_gateway_and_the_broker_must_both_be_up(
    hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A reachable broker does not make an offline gateway available."""
    connection_callbacks: list[Callable[[bool], None]] = []
    subscriptions: dict[str, Callable] = {}

    async def fake_subscribe(
        hass_: HomeAssistant, topic: str, handler: Callable
    ) -> Callable[[], None]:
        subscriptions[topic] = handler
        return Mock()

    def fake_connection_status(
        hass_: HomeAssistant, callback: Callable[[bool], None]
    ) -> Callable[[], None]:
        connection_callbacks.append(callback)
        return Mock()

    monkeypatch.setattr(mqtt_module.mqtt, "async_subscribe", fake_subscribe)
    monkeypatch.setattr(
        mqtt_module.mqtt, "async_subscribe_connection_status", fake_connection_status
    )
    monkeypatch.setattr(
        mqtt_module.mqtt, "async_wait_for_mqtt_client", AsyncMock(return_value=True)
    )
    monkeypatch.setattr(mqtt_module.mqtt, "is_connected", lambda hass_: True)
    transport = make_transport(hass, gateway_id=GATEWAY_ID)
    await transport.init()
    observed: list[ConnectionState] = []
    transport.subscribe_connection(observed.append)
    await transport.start(Mock())
    handler = subscriptions[transport.lwt_topic]

    await handler(gateway_status(b"offline", transport.lwt_topic))
    connection_callbacks[0](False)
    connection_callbacks[0](True)
    assert transport.connection_state is ConnectionState.DISCONNECTED

    await handler(gateway_status(b"online", transport.lwt_topic))
    assert transport.connection_state is ConnectionState.CONNECTED
    assert observed == [ConnectionState.DISCONNECTED, ConnectionState.CONNECTED]

    await transport.stop()


async def test_an_unknown_gateway_status_is_ignored(
    hass: HomeAssistant, caplog: pytest.LogCaptureFixture
) -> None:
    """Only the firmware's online/offline payloads change availability."""
    transport = make_transport(hass, gateway_id=GATEWAY_ID)
    await transport.init()
    transport._broker_connected = True
    transport._connection_state = ConnectionState.CONNECTED
    observed: list[ConnectionState] = []
    transport.subscribe_connection(observed.append)

    with caplog.at_level(logging.DEBUG):
        await transport._handle_gateway_status(transport.lwt_topic, b"starting")

    assert observed == []
    assert transport.connection_state is ConnectionState.CONNECTED
    assert "Ignoring gateway status" in caplog.text


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
    transport = make_transport(hass, gateway_id=GATEWAY_ID)

    await transport.init()

    subscribe.assert_not_called()
    assert transport.gateway_id == GATEWAY_ID
    assert transport.sub_topic == f"{MQTT_TOPIC}/{GATEWAY_ID}/rx"


async def test_online_message_is_ignored_when_the_gateway_is_known(
    hass: HomeAssistant,
) -> None:
    """A second gateway on the wildcard topic must not replace the stored one."""
    transport = make_transport(hass, gateway_id=GATEWAY_ID)

    await transport._handle_online_message(f"{MQTT_TOPIC}/18:999999", b"online")

    assert transport.gateway_id == GATEWAY_ID
    assert not transport._discovery_event.is_set()


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
    transport = make_transport(hass, gateway_id=GATEWAY_ID)
    await transport.init()
    packet = make_packet()

    await transport.send(packet)

    assert published == [
        (f"{MQTT_TOPIC}/{GATEWAY_ID}/tx", json.dumps(packet.ramses_esp_envelope()))
    ]


async def test_publish_wraps_transport_errors(
    hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A broker failure becomes a transport error for the caller."""

    async def failing_publish(hass_: HomeAssistant, topic: str, payload: str) -> None:
        raise RuntimeError("broker is offline")

    monkeypatch.setattr(mqtt_module.mqtt, "async_publish", failing_publish)
    transport = make_transport(hass, gateway_id=GATEWAY_ID)
    await transport.init()

    with pytest.raises(TransportError, match="broker is offline"):
        await transport.send(make_packet())


async def test_a_malformed_payload_is_logged(
    hass: HomeAssistant, caplog: pytest.LogCaptureFixture
) -> None:
    """Invalid JSON is reported instead of killing the subscription."""
    transport = make_transport(hass, gateway_id=GATEWAY_ID)

    with caplog.at_level(logging.ERROR):
        await transport._handle_packet_message(
            f"{MQTT_TOPIC}/{GATEWAY_ID}/rx", b"not json"
        )

    assert "Failed to process Ramses-ESP MQTT message" in caplog.text


async def test_backend_reports_a_missing_mqtt_client(
    hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The backend tells the session that MQTT is not usable yet."""
    monkeypatch.setattr(
        mqtt_module.mqtt,
        "async_wait_for_mqtt_client",
        AsyncMock(return_value=False),
    )
    backend = HassMqttBackend(hass)

    with pytest.raises(TransportNotReady):
        await backend.start()


def test_transport_starts_disconnected(hass: HomeAssistant) -> None:
    """No connection has been observed until the transport starts."""
    transport = make_transport(hass, gateway_id=GATEWAY_ID)

    assert transport.connection_state is ConnectionState.DISCONNECTED


async def test_latest_version_and_commands_use_the_gateway_topics(
    hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The newest version is subscribed and OTA commands go to cmd/cmd."""
    monkeypatch.setattr(
        mqtt_module.mqtt, "async_wait_for_mqtt_client", AsyncMock(return_value=True)
    )
    monkeypatch.setattr(
        mqtt_module.mqtt, "async_subscribe", AsyncMock(return_value=Mock())
    )
    monkeypatch.setattr(
        mqtt_module.mqtt,
        "async_subscribe_connection_status",
        Mock(return_value=Mock()),
    )
    monkeypatch.setattr(mqtt_module.mqtt, "is_connected", lambda hass_: True)
    latest_handler = Mock()
    transport = make_transport(hass, gateway_id=GATEWAY_ID)
    transport.subscribe_latest(latest_handler)
    await transport.init()

    assert transport.latest_topic == f"{MQTT_TOPIC}/{GATEWAY_ID}/info/latest"
    assert transport.cmd_topic == f"{MQTT_TOPIC}/{GATEWAY_ID}/cmd/cmd"

    await transport.start(AsyncMock())
    await transport._handle_latest_message(
        f"{MQTT_TOPIC}/{GATEWAY_ID}/info/latest", b"0.6.0"
    )
    await transport._handle_latest_message(
        f"{MQTT_TOPIC}/{GATEWAY_ID}/info/latest", "0.6.1"
    )

    assert [call.args[0] for call in latest_handler.call_args_list] == [
        "0.6.0",
        "0.6.1",
    ]

    transport._backend.publish = AsyncMock()
    await transport.send_command("ota start")
    transport._backend.publish.assert_awaited_once_with(
        f"{MQTT_TOPIC}/{GATEWAY_ID}/cmd/cmd", "ota start"
    )

    await transport.stop()


async def test_send_command_wraps_an_unexpected_backend_failure(
    hass: HomeAssistant,
) -> None:
    """A command that cannot be published is a transport error."""
    transport = make_transport(hass, gateway_id=GATEWAY_ID)
    await transport.init()
    transport._backend.publish = AsyncMock(side_effect=RuntimeError("broker down"))

    with pytest.raises(TransportError, match="Failed to publish command"):
        await transport.send_command("ota start")


async def test_send_command_passes_a_transport_error_through(
    hass: HomeAssistant,
) -> None:
    """A backend transport error is not wrapped a second time."""
    transport = make_transport(hass, gateway_id=GATEWAY_ID)
    await transport.init()
    transport._backend.publish = AsyncMock(side_effect=TransportError("broker offline"))

    with pytest.raises(TransportError, match="broker offline"):
        await transport.send_command("ota start")


async def test_transport_subscriptions_can_be_removed(
    hass: HomeAssistant,
) -> None:
    """Each subscription returns its own unsubscribe callable."""
    transport = make_transport(hass, gateway_id=GATEWAY_ID)
    handlers = [Mock(), Mock(), Mock()]
    unsubs = [
        transport.subscribe_version(handlers[0]),
        transport.subscribe_latest(handlers[1]),
        transport.subscribe_connection(handlers[2]),
    ]

    for unsub in unsubs:
        unsub()
        unsub()

    assert transport._version_handlers == []
    assert transport._latest_handlers == []
    assert transport._connection_handlers == []


async def test_send_wraps_an_unexpected_backend_failure(
    hass: HomeAssistant,
) -> None:
    """A backend that is not the Home Assistant adapter is still contained."""
    transport = make_transport(hass, gateway_id=GATEWAY_ID)
    await transport.init()
    transport._backend.publish = AsyncMock(side_effect=RuntimeError("broker down"))

    with pytest.raises(TransportError, match="Failed to publish payload"):
        await transport.send(make_packet())


async def test_received_messages_reach_the_handlers(
    hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The transport hands decoded envelopes and version strings to the session."""
    monkeypatch.setattr(
        mqtt_module.mqtt, "async_wait_for_mqtt_client", AsyncMock(return_value=True)
    )
    monkeypatch.setattr(
        mqtt_module.mqtt, "async_subscribe", AsyncMock(return_value=Mock())
    )
    monkeypatch.setattr(
        mqtt_module.mqtt,
        "async_subscribe_connection_status",
        Mock(return_value=Mock()),
    )
    monkeypatch.setattr(mqtt_module.mqtt, "is_connected", lambda hass_: True)
    packet_handler = AsyncMock()
    version_handler = Mock()
    transport = make_transport(hass, gateway_id=GATEWAY_ID)
    transport.subscribe_version(version_handler)
    await transport.init()
    await transport.start(packet_handler)
    envelope = {"ts": "2026-09-11T17:29:09+00:00", "msg": "081  I --- --:------"}

    await transport._handle_packet_message(
        f"{MQTT_TOPIC}/{GATEWAY_ID}/rx", json.dumps(envelope).encode()
    )
    await transport._handle_version_message(
        f"{MQTT_TOPIC}/{GATEWAY_ID}/info/version", b"2026.10.1"
    )
    await transport._handle_version_message(
        f"{MQTT_TOPIC}/{GATEWAY_ID}/info/version", "2026.10.1"
    )

    packet_handler.assert_awaited_once_with(envelope)
    assert [call.args[0] for call in version_handler.call_args_list] == [
        "2026.10.1",
        "2026.10.1",
    ]

    await transport.stop()
