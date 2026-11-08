"""Tests for the in-memory loopback transport."""

from __future__ import annotations

from unittest.mock import AsyncMock, Mock

import pytest

from ramses.protocol import RamsesID, RamsesPacket
from ramses.transport import ConnectionState, Transport
from ramses.transport.loopback import LoopbackTransport

GATEWAY_ID = "18:149960"
FAN_ID = "29:224547"
TIMESTAMP = "2026-09-11T17:29:09+00:00"


def make_packet() -> RamsesPacket:
    """Build an outgoing request."""
    return RamsesPacket(
        src_id=RamsesID(GATEWAY_ID),
        dst_id=RamsesID(FAN_ID),
        type="RQ",
        code="12A0",
        data="00",
    )


def test_loopback_reports_the_gateway_and_connection_state() -> None:
    """The transport exposes the gateway and a changeable connection state."""
    transport = LoopbackTransport(gateway_id=RamsesID(GATEWAY_ID))

    assert transport.gateway_id == GATEWAY_ID
    assert transport.connection_state is ConnectionState.CONNECTED

    transport.set_connection_state(ConnectionState.DISCONNECTED)

    assert transport.connection_state is ConnectionState.DISCONNECTED


async def test_loopback_initialises_without_gateway_discovery() -> None:
    """The transport protocol carries init(), a no-op for a fixed gateway."""
    transport = LoopbackTransport()

    await transport.init()

    assert isinstance(transport, Transport)
    assert transport.gateway_id == "18:000000"


async def test_loopback_records_sent_packets() -> None:
    """Sent packets are kept for an offline tool to inspect."""
    transport = LoopbackTransport()
    packet = make_packet()

    await transport.send(packet)

    assert transport.sent == [packet]


async def test_loopback_delivers_frames_and_versions() -> None:
    """A started loopback feeds the subscribed callbacks and can be stopped."""
    transport = LoopbackTransport()
    packet_handler = AsyncMock()
    version_handler = Mock()
    latest_handler = Mock()
    connection_handler = Mock()

    transport.subscribe_version(version_handler)
    transport.subscribe_latest(latest_handler)
    transport.subscribe_connection(connection_handler)
    await transport.start(packet_handler)
    await transport.receive_frame("081  I --- --:------", TIMESTAMP)
    transport.receive_version("2026.10.1")
    transport.receive_latest("2026.11.0")
    transport.set_connection_state(ConnectionState.DISCONNECTED)

    packet_handler.assert_awaited_once_with(
        {"ts": TIMESTAMP, "msg": "081  I --- --:------"}
    )
    version_handler.assert_called_once_with("2026.10.1")
    latest_handler.assert_called_once_with("2026.11.0")
    connection_handler.assert_called_once_with(ConnectionState.DISCONNECTED)
    assert transport.started is True

    await transport.stop()

    assert transport.started is False
    assert transport.stopped is True


async def test_loopback_records_firmware_commands() -> None:
    """Offline tools can inspect the console commands the integration sends."""
    transport = LoopbackTransport()

    await transport.send_command("ota start")
    await transport.send_command("ota version 0.6.0")

    assert transport.commands == ["ota start", "ota version 0.6.0"]


async def test_loopback_only_reports_a_changed_connection_state() -> None:
    """Repeating the current state is not a transition."""
    transport = LoopbackTransport(connection_state=ConnectionState.CONNECTED)
    connection_handler = Mock()
    transport.subscribe_connection(connection_handler)

    transport.set_connection_state(ConnectionState.CONNECTED)
    transport.set_connection_state(ConnectionState.DISCONNECTED)
    transport.set_connection_state(ConnectionState.DISCONNECTED)

    connection_handler.assert_called_once_with(ConnectionState.DISCONNECTED)


async def test_loopback_unsubscribes() -> None:
    """Every subscription has its own unsubscribe callable."""
    transport = LoopbackTransport()
    version_handler = Mock()
    latest_handler = Mock()
    connection_handler = Mock()
    unsub_version = transport.subscribe_version(version_handler)
    unsub_latest = transport.subscribe_latest(latest_handler)
    unsub_connection = transport.subscribe_connection(connection_handler)

    unsub_version()
    unsub_latest()
    unsub_connection()
    await transport.start(AsyncMock())
    transport.receive_version("2026.10.1")
    transport.receive_latest("2026.11.0")
    transport.set_connection_state(ConnectionState.DISCONNECTED)

    version_handler.assert_not_called()
    latest_handler.assert_not_called()
    connection_handler.assert_not_called()


async def test_loopback_refuses_to_deliver_before_start() -> None:
    """An unstarted transport has nowhere to deliver to."""
    transport = LoopbackTransport()

    with pytest.raises(RuntimeError, match="has not been called"):
        await transport.receive({"ts": TIMESTAMP, "msg": "081  I --- --:------"})

    with pytest.raises(RuntimeError, match="has not been called"):
        transport.receive_version("2026.10.1")

    with pytest.raises(RuntimeError, match="has not been called"):
        transport.receive_latest("2026.11.0")
