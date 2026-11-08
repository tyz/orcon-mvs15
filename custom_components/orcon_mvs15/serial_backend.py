"""serialx adapter for the RAMSES ESP USB transport."""

from __future__ import annotations

import asyncio
import logging
import os

import serialx

from .ramses.transport.base import TransportError
from .ramses.transport.ramses_esp.backend import (
    SerialClosedHandler,
    SerialDataHandler,
)

_LOGGER = logging.getLogger(__name__)

BAUDRATE = 115200


def _serial_number_for_port(port: str) -> str | None:
    """Look up the USB serial number of an already enumerated port."""
    target = os.path.realpath(port)
    for info in serialx.list_serial_ports():
        if info.device == port or os.path.realpath(info.device) == target:
            return info.serial_number
    return None


async def async_serial_number(port: str) -> str | None:
    """Return the USB serial number for a port without opening it."""
    return await asyncio.get_running_loop().run_in_executor(
        None, _serial_number_for_port, port
    )


class _Protocol(asyncio.Protocol):
    """Forward the serialx protocol callbacks to the backend."""

    def __init__(self, backend: SerialxBackend) -> None:
        self._backend = backend

    def data_received(self, data: bytes) -> None:
        self._backend.data_received(data)

    def connection_lost(self, exc: Exception | None) -> None:
        self._backend.connection_lost(exc)


class SerialxBackend:
    """Open a USB serial port and expose it as a byte channel."""

    def __init__(self, port: str) -> None:
        self._port = port
        self._transport: serialx.BaseSerialTransport | None = None
        self._data_handler: SerialDataHandler | None = None
        self._closed_handler: SerialClosedHandler | None = None
        self._closing = False

    async def serial_number(self) -> str | None:
        """Return the USB serial number of the port."""
        return await async_serial_number(self._port)

    async def start(
        self, handle_data: SerialDataHandler, handle_closed: SerialClosedHandler
    ) -> None:
        """Open the port and start forwarding its bytes."""
        self._data_handler = handle_data
        self._closed_handler = handle_closed
        self._closing = False
        try:
            transport, _ = await serialx.create_serial_connection(
                asyncio.get_running_loop(),
                lambda: _Protocol(self),
                self._port,
                BAUDRATE,
            )
        except (serialx.SerialException, OSError, ValueError) as err:
            raise TransportError(f"Could not open {self._port}: {err}") from err
        self._transport = transport

    async def stop(self) -> None:
        """Close the port without reporting it as an unexpected loss."""
        self._closing = True
        transport = self._transport
        self._transport = None
        if transport is not None:
            transport.close()
        self._data_handler = None
        self._closed_handler = None

    async def write(self, data: bytes) -> None:
        """Write bytes to the open port."""
        if self._transport is None:
            raise TransportError(f"The serial port {self._port} is not open")
        self._transport.write(data)

    def data_received(self, data: bytes) -> None:
        """Forward one received chunk."""
        if self._data_handler is not None:
            self._data_handler(data)

    def connection_lost(self, exc: Exception | None) -> None:
        """Report an unexpected loss of the port."""
        self._transport = None
        if self._closed_handler is not None and not self._closing:
            _LOGGER.debug("The serial port %s was lost: %s", self._port, exc)
            self._closed_handler(exc)
