"""The MQTT operations a RAMSES ESP transport needs from its host."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Protocol, runtime_checkable

from ..base import TransportError

type MessageHandler = Callable[[str, str | bytes | bytearray], Awaitable[None] | None]
type ConnectionHandler = Callable[[bool], None]


class MqttBackendError(TransportError):
    """The host MQTT client could not publish or subscribe."""


@runtime_checkable
class MqttBackend(Protocol):
    """The small MQTT surface the Ramses ESP transport depends on."""

    async def start(self) -> None:
        """Wait until the MQTT client is usable."""
        ...

    async def stop(self) -> None:
        """Release the client."""
        ...

    async def subscribe(
        self, topic: str, handler: MessageHandler
    ) -> Callable[[], None]:
        """Subscribe to a topic and return its unsubscribe callable."""
        ...

    async def publish(self, topic: str, payload: str) -> None:
        """Publish one payload."""
        ...

    def subscribe_connection(self, handler: ConnectionHandler) -> Callable[[], None]:
        """Subscribe to connection state changes."""
        ...

    def is_connected(self) -> bool:
        """Return whether the client is currently connected."""
        ...
