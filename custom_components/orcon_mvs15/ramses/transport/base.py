"""The boundary between the RAMSES session and a concrete gateway transport."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from enum import StrEnum
from typing import Protocol, runtime_checkable

from ..protocol.frame import RamsesID, RamsesPacket

type Envelope = dict[str, str]
type PacketHandler = Callable[[Envelope], Awaitable[None]]
type VersionHandler = Callable[[str], None]
type ConnectionHandler = Callable[[ConnectionState], None]


class ConnectionState(StrEnum):
    """Whether the transport can currently reach the gateway."""

    CONNECTED = "connected"
    DISCONNECTED = "disconnected"


class TransportError(Exception):
    """The transport could not reach or talk to the gateway."""


class TransportNotReady(TransportError):
    """The gateway is not reachable yet; setup should be retried."""


@runtime_checkable
class Transport(Protocol):
    """A gateway the session can send packets to and receive frames from.

    A new stick implements this protocol; it does not change the session.
    """

    @property
    def gateway_id(self) -> RamsesID: ...

    @property
    def connection_state(self) -> ConnectionState: ...

    async def init(self) -> None:
        """Discover the gateway before start() subscribes to its topics."""
        ...  # pragma: no cover

    async def start(self, handle_packet: PacketHandler) -> None:
        """Subscribe to the gateway and start delivering frames."""
        ...  # pragma: no cover

    async def stop(self) -> None:
        """Stop delivering frames and release the subscriptions."""
        ...  # pragma: no cover

    async def send(self, packet: RamsesPacket) -> None:
        """Publish one packet to the gateway."""
        ...  # pragma: no cover

    def subscribe_version(self, handler: VersionHandler) -> Callable[[], None]:
        """Subscribe to the gateway firmware version."""
        ...  # pragma: no cover

    def subscribe_connection(self, handler: ConnectionHandler) -> Callable[[], None]:
        """Subscribe to connection state changes."""
        ...  # pragma: no cover
