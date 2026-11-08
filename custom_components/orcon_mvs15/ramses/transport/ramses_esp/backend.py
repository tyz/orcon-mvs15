"""The host operations a RAMSES ESP transport needs."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Protocol, runtime_checkable

from ..base import TransportError

type MessageHandler = Callable[[str, str | bytes | bytearray], Awaitable[None] | None]
type ConnectionHandler = Callable[[bool], None]
type SerialDataHandler = Callable[[bytes], None]
type SerialClosedHandler = Callable[[Exception | None], None]


class MqttBackendError(TransportError):
    """The host MQTT client could not publish or subscribe."""


@runtime_checkable
class MqttBackend(Protocol):
    """The small MQTT surface the Ramses ESP transport depends on."""

    async def start(self) -> None:
        """Wait until the MQTT client is usable."""
        ...  # pragma: no cover

    async def stop(self) -> None:
        """Release the client."""
        ...  # pragma: no cover

    async def subscribe(
        self, topic: str, handler: MessageHandler
    ) -> Callable[[], None]:
        """Subscribe to a topic and return its unsubscribe callable."""
        ...  # pragma: no cover

    async def publish(self, topic: str, payload: str) -> None:
        """Publish one payload."""
        ...  # pragma: no cover

    def subscribe_connection(self, handler: ConnectionHandler) -> Callable[[], None]:
        """Subscribe to connection state changes."""
        ...  # pragma: no cover

    def is_connected(self) -> bool:
        """Return whether the client is currently connected."""
        ...  # pragma: no cover


@runtime_checkable
class SerialBackend(Protocol):
    """The byte channel the USB transport depends on."""

    async def serial_number(self) -> str | None:
        """Return the USB serial number of the port, if the OS exposes it."""
        ...  # pragma: no cover

    async def start(
        self, handle_data: SerialDataHandler, handle_closed: SerialClosedHandler
    ) -> None:
        """Open the port and deliver received bytes to the handler."""
        ...  # pragma: no cover

    async def stop(self) -> None:
        """Close the port."""
        ...  # pragma: no cover

    async def write(self, data: bytes) -> None:
        """Write bytes to the port."""
        ...  # pragma: no cover
