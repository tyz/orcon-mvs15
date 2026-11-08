"""Tests for the RAMSES ESP USB serial transport."""

from __future__ import annotations

import asyncio

from collections.abc import Callable
from datetime import datetime
from unittest.mock import AsyncMock, Mock

import pytest

from ramses.protocol import RamsesID, RamsesPacket
from ramses.transport import ConnectionState, Transport, TransportError
from ramses.transport.ramses_esp.backend import SerialClosedHandler, SerialDataHandler
from ramses.transport.ramses_esp.serial import (
    FRAME_QUEUE_SIZE,
    MAX_LINE_LENGTH,
    RamsesESPSerial,
    gateway_id_from_serial,
)

GATEWAY_ID = "18:149960"
FAN_ID = "29:224547"
MAC = "34:85:18:AA:B7:C8"
MAC_GATEWAY_ID = "18:178120"
FRAME = f"044 RP --- {FAN_ID} {GATEWAY_ID} --:------ 31D9 003 000001"


class FakeSerialBackend:
    """A serial port that records writes and replays received bytes."""

    def __init__(
        self,
        serial_number: str | None = MAC,
        *,
        fail_start: bool = False,
    ) -> None:
        self._serial_number = serial_number
        self.fail_start = fail_start
        self.data_handler: SerialDataHandler | None = None
        self.closed_handler: SerialClosedHandler | None = None
        self.writes: list[bytes] = []
        self.started = False
        self.stopped = False
        self.start_calls = 0
        self.fail_write = False
        self.write_error: Exception | None = None
        self.stop_error: Exception | None = None
        self.lose_on_stop = False

    async def serial_number(self) -> str | None:
        return self._serial_number

    async def start(
        self, handle_data: SerialDataHandler, handle_closed: SerialClosedHandler
    ) -> None:
        if self.fail_start:
            raise OSError("the port is busy")
        self.start_calls += 1
        self.started = True
        self.data_handler = handle_data
        self.closed_handler = handle_closed

    async def stop(self) -> None:
        if self.lose_on_stop and self.closed_handler is not None:
            self.closed_handler(None)
        if self.stop_error is not None:
            raise self.stop_error
        self.stopped = True

    async def write(self, data: bytes) -> None:
        if self.write_error is not None:
            raise self.write_error
        if self.fail_write:
            raise OSError("the port is gone")
        self.writes.append(data)

    def feed(self, data: bytes) -> None:
        assert self.data_handler is not None
        self.data_handler(data)

    def lose(self, exc: Exception | None = None) -> None:
        assert self.closed_handler is not None
        self.closed_handler(exc)


async def settle() -> None:
    """Let the frame consumer task run."""
    for _ in range(10):
        await asyncio.sleep(0)


def make_packet() -> RamsesPacket:
    """Build an outgoing humidity request."""
    return RamsesPacket(
        src_id=RamsesID(GATEWAY_ID),
        dst_id=RamsesID(FAN_ID),
        type="RQ",
        code="12A0",
        data="00",
    )


@pytest.mark.parametrize(
    ("serial_number", "expected"),
    [
        (MAC, MAC_GATEWAY_ID),
        ("34-85-18-AA-B7-C8", MAC_GATEWAY_ID),
        ("AA:BB:CC:DD:EE:FF", "18:126719"),
        ("", ""),
        ("34:85:18", ""),
        ("not-a-mac", ""),
        (None, ""),
    ],
)
def test_the_gateway_id_comes_from_the_usb_serial_number(
    serial_number: str | None, expected: str
) -> None:
    """The firmware derives its id from the last three factory-MAC bytes."""
    assert gateway_id_from_serial(serial_number) == RamsesID(expected)


async def test_init_derives_the_gateway_id() -> None:
    """A USB transport learns its gateway before the port is opened."""
    transport = RamsesESPSerial(FakeSerialBackend())

    await transport.init()

    assert transport.gateway_id == MAC_GATEWAY_ID


async def test_init_prefers_the_configured_gateway_id() -> None:
    """A stored gateway id is used without another lookup."""
    transport = RamsesESPSerial(
        FakeSerialBackend(serial_number=None), gateway_id=RamsesID(GATEWAY_ID)
    )

    await transport.init()

    assert transport.gateway_id == GATEWAY_ID


async def test_init_requires_a_serial_number_to_derive_the_id() -> None:
    """A port without a USB serial cannot identify its gateway."""
    transport = RamsesESPSerial(FakeSerialBackend(serial_number=None))

    with pytest.raises(TransportError, match="derive the gateway id"):
        await transport.init()


async def test_a_failed_serial_lookup_raises_a_transport_error() -> None:
    """A broken serial lookup does not escape as an OSError."""

    class BrokenBackend(FakeSerialBackend):
        async def serial_number(self) -> str | None:
            raise OSError("no udev")

    transport = RamsesESPSerial(BrokenBackend())

    with pytest.raises(TransportError, match="USB serial number"):
        await transport.init()


async def test_start_reports_connected_and_stop_disconnects() -> None:
    """Opening and closing the port changes the connection state."""
    backend = FakeSerialBackend()
    transport = RamsesESPSerial(backend, gateway_id=RamsesID(GATEWAY_ID))
    states: list[ConnectionState] = []
    transport.subscribe_connection(states.append)

    await transport.start(AsyncMock())

    assert isinstance(transport, Transport)
    assert backend.started is True
    assert transport.connection_state is ConnectionState.CONNECTED

    await transport.stop()

    assert backend.stopped is True
    assert transport.connection_state is ConnectionState.DISCONNECTED
    assert states == [ConnectionState.CONNECTED, ConnectionState.DISCONNECTED]


async def test_a_start_failure_is_a_transport_error() -> None:
    """A port that cannot be opened fails setup with a clear error."""
    transport = RamsesESPSerial(
        FakeSerialBackend(fail_start=True), gateway_id=RamsesID(GATEWAY_ID)
    )

    with pytest.raises(TransportError, match="Could not open"):
        await transport.start(AsyncMock())


async def test_received_lines_become_timestamped_envelopes() -> None:
    """A chunk may hold several lines, or only part of one."""
    backend = FakeSerialBackend()
    transport = RamsesESPSerial(backend, gateway_id=RamsesID(GATEWAY_ID))
    received: list[dict[str, str]] = []

    async def handle(envelope: dict[str, str]) -> None:
        received.append(envelope)

    await transport.start(handle)
    try:
        backend.feed(b"044 RP --- 29:22")
        backend.feed(f"4547 {GATEWAY_ID} --:------ 31D9 003 000001\r\n".encode())
        backend.feed(b"# ramses_esp 0.5.0\n")
        await settle()
    finally:
        await transport.stop()

    assert len(received) == 1
    assert received[0]["msg"] == FRAME
    assert datetime.fromisoformat(received[0]["ts"]).tzinfo is not None


async def test_the_boot_banner_reports_the_version() -> None:
    """The firmware banner is the only place the serial port names a version."""
    backend = FakeSerialBackend()
    transport = RamsesESPSerial(backend, gateway_id=RamsesID(GATEWAY_ID))
    versions: list[str] = []
    transport.subscribe_version(versions.append)

    await transport.start(AsyncMock())
    try:
        backend.feed(b"# ramses_esp 0.5.0\n")
    finally:
        await transport.stop()

    assert versions == ["0.5.0"]


async def test_a_console_echo_glued_to_a_frame_is_split() -> None:
    """The firmware echo of a written frame may share the received frame's line."""
    backend = FakeSerialBackend()
    transport = RamsesESPSerial(backend, gateway_id=RamsesID(GATEWAY_ID))
    received: list[dict[str, str]] = []
    frame = "074  I --- 32:093949 29:223489 32:093949 31E0 008 0000000001001E"

    async def handle(envelope: dict[str, str]) -> None:
        received.append(envelope)

    await transport.start(handle)
    try:
        backend.feed(
            f"{frame}# RQ --- 18:149960 29:224547 --:------ 10E0 001 00\n".encode()
        )
        await settle()
    finally:
        await transport.stop()

    assert [envelope["msg"] for envelope in received] == [frame]


async def test_a_console_line_glued_to_a_frame_is_still_read() -> None:
    """A console line after the echo separator is not lost with the frame."""
    backend = FakeSerialBackend()
    transport = RamsesESPSerial(backend, gateway_id=RamsesID(GATEWAY_ID))
    versions: list[str] = []
    transport.subscribe_version(versions.append)

    await transport.start(AsyncMock())
    try:
        backend.feed(f"{FRAME}# ramses_esp 0.5.4\n".encode())
        await settle()
    finally:
        await transport.stop()

    assert versions == ["0.5.4"]


async def test_the_latest_version_line_is_reported() -> None:
    """The OTA check prints the newest version on the console."""
    backend = FakeSerialBackend()
    transport = RamsesESPSerial(backend, gateway_id=RamsesID(GATEWAY_ID))
    versions: list[str] = []
    latest: list[str] = []
    transport.subscribe_version(versions.append)
    transport.subscribe_latest(latest.append)

    await transport.start(AsyncMock())
    try:
        backend.feed(b"# ramses_esp 0.5.3\n")
        backend.feed(b"# Latest firmware version: 0.6.0\n")
    finally:
        await transport.stop()

    assert versions == ["0.5.3"]
    assert latest == ["0.6.0"]


async def test_send_command_writes_the_console_line() -> None:
    """A firmware command is a plain console line, not an HGI80 frame."""
    backend = FakeSerialBackend()
    transport = RamsesESPSerial(backend, gateway_id=RamsesID(GATEWAY_ID))
    await transport.start(AsyncMock())

    try:
        await transport.send_command("ota start")
    finally:
        await transport.stop()

    assert backend.writes == [b"ota start\r"]


async def test_send_command_before_start_raises() -> None:
    """An unopened port cannot send a firmware command."""
    transport = RamsesESPSerial(FakeSerialBackend(), gateway_id=RamsesID(GATEWAY_ID))

    with pytest.raises(TransportError, match="not connected"):
        await transport.send_command("ota start")


async def test_a_command_write_failure_is_a_transport_error() -> None:
    """A vanished port is reported as a failed firmware command."""
    backend = FakeSerialBackend()
    backend.fail_write = True
    transport = RamsesESPSerial(backend, gateway_id=RamsesID(GATEWAY_ID))
    await transport.start(AsyncMock())

    try:
        with pytest.raises(TransportError, match="Failed to send serial command"):
            await transport.send_command("ota start")
    finally:
        await transport.stop()


async def test_console_and_debug_lines_are_ignored() -> None:
    """Only HGI80 frame lines reach the session."""
    backend = FakeSerialBackend()
    transport = RamsesESPSerial(backend, gateway_id=RamsesID(GATEWAY_ID))
    received: list[dict[str, str]] = []

    async def handle(envelope: dict[str, str]) -> None:
        received.append(envelope)

    await transport.start(handle)
    try:
        backend.feed(b"# cmd\n")
        backend.feed(b"I (123) wifi: state: run\n")
        backend.feed(b"\n")
        backend.feed(b"\xff\xfe\n")
    finally:
        await transport.stop()

    assert received == []


async def test_an_oversized_line_is_dropped() -> None:
    """A line that never ends cannot grow the buffer without limit."""
    backend = FakeSerialBackend()
    transport = RamsesESPSerial(backend, gateway_id=RamsesID(GATEWAY_ID))
    received: list[dict[str, str]] = []

    async def handle(envelope: dict[str, str]) -> None:
        received.append(envelope)

    await transport.start(handle)
    try:
        backend.feed(b"0" * (MAX_LINE_LENGTH + 1))
        backend.feed(b"\n")
        await settle()
    finally:
        await transport.stop()

    assert received == []
    assert len(transport._buffer) == 0


async def test_send_writes_the_firmware_console_command() -> None:
    """The transport sends the same message the MQTT transport publishes."""
    backend = FakeSerialBackend()
    transport = RamsesESPSerial(backend, gateway_id=RamsesID(GATEWAY_ID))
    await transport.start(AsyncMock())
    try:
        await transport.send(make_packet())
    finally:
        await transport.stop()

    assert backend.writes == [
        f"RQ --- {GATEWAY_ID} {FAN_ID} --:------ 12A0 001 00\r".encode("ascii")
    ]


async def test_send_before_start_raises() -> None:
    """An unopened port cannot transmit."""
    transport = RamsesESPSerial(FakeSerialBackend(), gateway_id=RamsesID(GATEWAY_ID))

    with pytest.raises(TransportError, match="not connected"):
        await transport.send(make_packet())


async def test_a_write_failure_is_a_transport_error() -> None:
    """A vanished port is reported as a failed command."""
    backend = FakeSerialBackend()
    backend.fail_write = True
    transport = RamsesESPSerial(backend, gateway_id=RamsesID(GATEWAY_ID))
    await transport.start(AsyncMock())

    try:
        with pytest.raises(TransportError, match="Failed to send"):
            await transport.send(make_packet())
    finally:
        await transport.stop()


async def test_an_unexpected_close_marks_the_transport_disconnected() -> None:
    """Losing the cable makes the entities unavailable."""
    backend = FakeSerialBackend()
    transport = RamsesESPSerial(backend, gateway_id=RamsesID(GATEWAY_ID))
    states: list[ConnectionState] = []
    transport.subscribe_connection(states.append)
    await transport.start(AsyncMock())

    backend.lose(OSError("unplugged"))

    assert transport.connection_state is ConnectionState.DISCONNECTED
    assert states == [ConnectionState.CONNECTED, ConnectionState.DISCONNECTED]

    await transport.stop()
    assert states == [ConnectionState.CONNECTED, ConnectionState.DISCONNECTED]


async def test_an_intentional_close_is_not_reported_as_a_loss() -> None:
    """Stopping the transport must not emit a second disconnect."""
    backend = FakeSerialBackend()
    transport = RamsesESPSerial(backend, gateway_id=RamsesID(GATEWAY_ID))
    states: list[ConnectionState] = []
    transport.subscribe_connection(states.append)
    await transport.start(AsyncMock())

    await transport.stop()
    backend.lose()

    assert states == [ConnectionState.CONNECTED, ConnectionState.DISCONNECTED]


async def test_subscriptions_can_be_removed() -> None:
    """Every subscription returns its own unsubscribe callable."""
    backend = FakeSerialBackend()
    transport = RamsesESPSerial(backend, gateway_id=RamsesID(GATEWAY_ID))
    version_handler: Callable[[str], None] = Mock()
    latest_handler: Callable[[str], None] = Mock()
    connection_handler: Callable[[ConnectionState], None] = Mock()
    unsub_version = transport.subscribe_version(version_handler)
    unsub_latest = transport.subscribe_latest(latest_handler)
    unsub_connection = transport.subscribe_connection(connection_handler)

    unsub_version()
    unsub_latest()
    unsub_connection()
    await transport.start(AsyncMock())
    try:
        backend.feed(b"# ramses_esp 0.5.0\n")
        backend.feed(b"# Latest firmware version: 0.6.0\n")
    finally:
        await transport.stop()

    version_handler.assert_not_called()
    latest_handler.assert_not_called()
    connection_handler.assert_not_called()


async def test_starting_twice_opens_the_port_once() -> None:
    """A repeated start must not open a second connection."""
    backend = FakeSerialBackend()
    transport = RamsesESPSerial(backend, gateway_id=RamsesID(GATEWAY_ID))

    await transport.start(AsyncMock())
    await transport.start(AsyncMock())

    try:
        assert backend.start_calls == 1
    finally:
        await transport.stop()


async def test_a_backend_stop_failure_does_not_block_shutdown(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A port that will not close still leaves the transport disconnected."""
    backend = FakeSerialBackend()
    backend.stop_error = OSError("device busy")
    transport = RamsesESPSerial(backend, gateway_id=RamsesID(GATEWAY_ID))
    await transport.start(AsyncMock())
    caplog.set_level("DEBUG")

    await transport.stop()

    assert transport.connection_state is ConnectionState.DISCONNECTED
    assert "Closing the USB gateway failed" in caplog.text


async def test_a_transport_error_on_write_is_not_wrapped() -> None:
    """A write that already failed in transport terms keeps its message."""
    backend = FakeSerialBackend()
    backend.write_error = TransportError("the port is gone")
    transport = RamsesESPSerial(backend, gateway_id=RamsesID(GATEWAY_ID))
    await transport.start(AsyncMock())

    try:
        with pytest.raises(TransportError, match="the port is gone"):
            await transport.send(make_packet())
    finally:
        await transport.stop()


async def test_a_failing_frame_handler_is_logged(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """One broken delivery must not stop the consumer."""
    backend = FakeSerialBackend()
    transport = RamsesESPSerial(backend, gateway_id=RamsesID(GATEWAY_ID))
    received: list[dict[str, str]] = []

    async def handle(envelope: dict[str, str]) -> None:
        received.append(envelope)
        if len(received) == 1:
            raise RuntimeError("the handler broke")

    await transport.start(handle)
    try:
        backend.feed(f"{FRAME}\n".encode())
        backend.feed(f"{FRAME}\n".encode())
        await settle()
    finally:
        await transport.stop()

    assert len(received) == 2
    assert "Failed to deliver" in caplog.text


async def test_a_full_frame_queue_drops_new_frames(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A stuck consumer cannot make the buffer grow without limit."""
    transport = RamsesESPSerial(FakeSerialBackend(), gateway_id=RamsesID(GATEWAY_ID))
    await transport.start(AsyncMock())

    try:
        for _ in range(FRAME_QUEUE_SIZE + 1):
            transport._handle_line(FRAME.encode("ascii"))
    finally:
        await transport.stop()

    assert "queue is full" in caplog.text


async def test_a_close_during_stop_is_not_reported() -> None:
    """The port may report a close while the transport is already closing."""
    backend = FakeSerialBackend()
    backend.lose_on_stop = True
    transport = RamsesESPSerial(backend, gateway_id=RamsesID(GATEWAY_ID))
    states: list[ConnectionState] = []
    transport.subscribe_connection(states.append)
    await transport.start(AsyncMock())

    await transport.stop()

    assert states == [ConnectionState.CONNECTED, ConnectionState.DISCONNECTED]
