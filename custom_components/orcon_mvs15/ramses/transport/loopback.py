"""In-memory transport for tests and offline tools."""

from __future__ import annotations

from collections.abc import Callable

from ..protocol.frame import RamsesID, RamsesPacket
from .base import (
    ConnectionHandler,
    ConnectionState,
    Envelope,
    PacketHandler,
    VersionHandler,
)


class LoopbackTransport:
    """A transport that keeps sent packets and replays frames on demand."""

    def __init__(
        self,
        gateway_id: RamsesID = RamsesID("18:000000"),
        connection_state: ConnectionState = ConnectionState.CONNECTED,
    ) -> None:
        self._gateway_id = gateway_id
        self._connection_state = connection_state
        self._packet_handler: PacketHandler | None = None
        self._version_handlers: list[VersionHandler] = []
        self._connection_handlers: list[ConnectionHandler] = []
        self.sent: list[RamsesPacket] = []
        self.started = False
        self.stopped = False

    @property
    def gateway_id(self) -> RamsesID:
        return self._gateway_id

    @property
    def connection_state(self) -> ConnectionState:
        return self._connection_state

    async def start(self, handle_packet: PacketHandler) -> None:
        self._packet_handler = handle_packet
        self.started = True

    async def stop(self) -> None:
        self.started = False
        self.stopped = True

    async def send(self, packet: RamsesPacket) -> None:
        self.sent.append(packet)

    def subscribe_version(self, handler: VersionHandler) -> Callable[[], None]:
        """Subscribe to the gateway firmware version."""
        self._version_handlers.append(handler)
        return lambda: self._version_handlers.remove(handler)

    def subscribe_connection(self, handler: ConnectionHandler) -> Callable[[], None]:
        """Subscribe to connection state changes."""
        self._connection_handlers.append(handler)
        return lambda: self._connection_handlers.remove(handler)

    async def receive(self, envelope: Envelope) -> None:
        """Deliver one gateway envelope as if it arrived from the stick."""
        if self._packet_handler is None:
            raise RuntimeError("LoopbackTransport.start() has not been called")
        await self._packet_handler(envelope)

    async def receive_frame(self, frame: str, timestamp: str) -> None:
        """Deliver a raw frame with the timestamp the gateway would attach."""
        await self.receive({"ts": timestamp, "msg": frame})

    def receive_version(self, version: str) -> None:
        """Deliver a gateway firmware version."""
        if not self.started:
            raise RuntimeError("LoopbackTransport.start() has not been called")
        for handler in tuple(self._version_handlers):
            handler(version)

    def set_connection_state(self, state: ConnectionState) -> None:
        """Change the connection state and notify the subscribers."""
        if state == self._connection_state:
            return
        self._connection_state = state
        for handler in tuple(self._connection_handlers):
            handler(state)
