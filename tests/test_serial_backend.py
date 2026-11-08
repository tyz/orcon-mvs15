"""Tests for the serialx adapter behind the USB transport."""

from __future__ import annotations

import asyncio
import os
import pty

from collections.abc import AsyncIterator
from types import SimpleNamespace

import pytest
import serialx

from custom_components.orcon_mvs15.ramses.transport import TransportError
from custom_components.orcon_mvs15.serial_backend import (
    SerialxBackend,
    async_serial_number,
)


@pytest.fixture
async def pty_port() -> AsyncIterator[tuple[str, int]]:
    """Return a pseudo-terminal path and its master file descriptor."""
    master, slave = pty.openpty()
    try:
        yield os.ttyname(slave), master
    finally:
        for fd in (master, slave):
            try:
                os.close(fd)
            except OSError:
                pass


async def read_available(fd: int, timeout: float = 2.0) -> bytes:
    """Read whatever the pty master holds, waiting for the first byte."""
    loop = asyncio.get_running_loop()
    return await asyncio.wait_for(
        loop.run_in_executor(None, os.read, fd, 1024), timeout
    )


async def test_a_port_without_a_usb_serial_returns_none(
    pty_port: tuple[str, int],
) -> None:
    """A pty has no USB descriptor, so there is no serial number to read."""
    port, _ = pty_port

    assert await async_serial_number(port) is None


async def test_the_backend_writes_and_reads_bytes(
    pty_port: tuple[str, int],
) -> None:
    """The adapter carries bytes in both directions."""
    port, master = pty_port
    backend = SerialxBackend(port)
    received: list[bytes] = []

    await backend.start(received.append, lambda exc: None)
    try:
        await backend.write(b"hello\r")
        assert await read_available(master) == b"hello\r"

        os.write(master, b"frame\r\n")
        for _ in range(20):
            if received:
                break
            await asyncio.sleep(0.01)
    finally:
        await backend.stop()

    assert received == [b"frame\r\n"]


async def test_stopping_the_backend_reports_no_loss(
    pty_port: tuple[str, int],
) -> None:
    """Closing the adapter is intentional and must not look like a cable pull."""
    port, _ = pty_port
    backend = SerialxBackend(port)
    losses: list[Exception | None] = []

    await backend.start(lambda data: None, losses.append)
    await backend.stop()
    await asyncio.sleep(0.05)

    assert losses == []


async def test_losing_the_port_calls_the_closed_handler(
    pty_port: tuple[str, int],
) -> None:
    """An unplugged serial port is reported to the transport."""
    port, master = pty_port
    backend = SerialxBackend(port)
    losses: list[Exception | None] = []

    await backend.start(lambda data: None, losses.append)
    os.close(master)
    for _ in range(50):
        if losses:
            break
        await asyncio.sleep(0.01)

    await backend.stop()

    assert len(losses) == 1


async def test_a_write_needs_an_open_port(pty_port: tuple[str, int]) -> None:
    """Writing before the port is opened fails loudly."""
    port, _ = pty_port

    with pytest.raises(TransportError, match="not open"):
        await SerialxBackend(port).write(b"data")


async def test_an_unopenable_port_is_a_transport_error() -> None:
    """A missing device surfaces as a transport error, not an OSError."""
    backend = SerialxBackend("/dev/definitely-not-a-port")

    with pytest.raises(TransportError, match="Could not open"):
        await backend.start(lambda data: None, lambda exc: None)


async def test_the_serial_number_is_read_from_the_port_listing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """serialx reports the USB serial number of an enumerated port."""
    info = SimpleNamespace(device="/dev/ttyACM0", serial_number="34:85:18:AA:B7:C8")
    monkeypatch.setattr(serialx, "list_serial_ports", lambda: [info])

    assert await async_serial_number("/dev/ttyACM0") == "34:85:18:AA:B7:C8"
    assert await SerialxBackend("/dev/ttyACM0").serial_number() == ("34:85:18:AA:B7:C8")
