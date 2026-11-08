"""Transport-agnostic RAMSES II session.

The session owns the frame queue, the codec dispatch and the retried requests.
It knows nothing about Home Assistant: a host subscribes to the callbacks it
needs, sends packets and reads the connection state.
"""

from __future__ import annotations

import asyncio
import inspect
import logging

from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from .protocol import (
    CODE_REGISTRY,
    Code,
    RamsesPacket,
    RamsesPacketResponse,
)
from .transport import ConnectionState, Envelope, Transport, TransportError

_LOGGER = logging.getLogger(__name__)

FRAME_QUEUE_SIZE = 100

type CodeHandler = Callable[[Code], Awaitable[None] | None]
type RawHandler = Callable[[Envelope], Awaitable[None] | None]
type ConnectionHandler = Callable[[ConnectionState], Awaitable[None] | None]
type VersionHandler = Callable[[str], Awaitable[None] | None]
type Scheduler = Callable[[float, Callable[[], None]], Callable[[], None]]


def loop_scheduler(delay: float, action: Callable[[], None]) -> Callable[[], None]:
    """Schedule an action on the running event loop."""
    timer = asyncio.get_running_loop().call_later(delay, action)
    return timer.cancel


@dataclass
class PendingRequest:
    """An outgoing request that is waiting for its expected response."""

    packet: RamsesPacket
    expected_response: RamsesPacketResponse
    attempts: int = 0
    cancel_timer: Callable[[], None] | None = None

    def matches(self, packet: RamsesPacket) -> bool:
        """Return whether a received packet answers this request."""
        return self.expected_response.matches(packet)

    def cancel(self) -> None:
        """Cancel the retry timer, if one is still armed."""
        if self.cancel_timer is not None:
            self.cancel_timer()
            self.cancel_timer = None


class RamsesSession:
    """Speak RAMSES II over one transport.

    Frames are decoded on a single consumer task so handlers run in order. Every
    subscription returns its own unsubscribe callable.
    """

    def __init__(
        self,
        transport: Transport,
        *,
        scheduler: Scheduler | None = None,
        queue_size: int = FRAME_QUEUE_SIZE,
    ) -> None:
        self._transport = transport
        self._scheduler = scheduler or loop_scheduler
        self._frames: asyncio.Queue[Envelope] = asyncio.Queue(maxsize=queue_size)
        self._code_handlers: dict[str, list[CodeHandler]] = {}
        self._raw_handlers: list[RawHandler] = []
        self._connection_handlers: list[ConnectionHandler] = []
        self._version_handlers: list[VersionHandler] = []
        self._latest_handlers: list[VersionHandler] = []
        self._pending: dict[str, PendingRequest] = {}
        self._unsubs: list[Callable[[], None]] = []
        self._consumer: asyncio.Task[None] | None = None
        self._closed = False

    @property
    def gateway_id(self) -> str:
        """Return the id of the gateway the transport talks to."""
        return self._transport.gateway_id

    @property
    def connection_state(self) -> ConnectionState:
        """Return the transport's current connection state."""
        return self._transport.connection_state

    @property
    def subscribed_codes(self) -> set[str]:
        """Return the code keys that currently have a subscriber."""
        return set(self._code_handlers)

    @property
    def pending_requests(self) -> tuple[PendingRequest, ...]:
        """Return the requests that are still waiting for a response."""
        return tuple(self._pending.values())

    async def start(self) -> None:
        """Start the transport and the frame consumer."""
        if self._consumer is not None:
            return
        await self._transport.start(self._enqueue_frame)
        self._unsubs.append(self._transport.subscribe_version(self._version_received))
        self._unsubs.append(self._transport.subscribe_latest(self._latest_received))
        self._unsubs.append(
            self._transport.subscribe_connection(self._connection_changed)
        )
        self._consumer = asyncio.create_task(self._consume_frames())

    async def stop(self) -> None:
        """Stop the consumer, the retries and the transport."""
        if self._closed:
            return
        self._closed = True
        while self._unsubs:
            self._unsubs.pop()()
        if self._consumer is not None:
            self._consumer.cancel()
            try:
                await self._consumer
            except asyncio.CancelledError:
                pass
            self._consumer = None
        for request in tuple(self._pending.values()):
            self._remove_request(request)
        await self._transport.stop()

    async def send(self, packet: RamsesPacket) -> None:
        """Publish one packet without waiting for a response."""
        if self._closed:
            raise TransportError("The RAMSES session is closed")
        await self._transport.send(packet)

    async def send_command(self, command: str) -> None:
        """Send a firmware console command to the gateway."""
        if self._closed:
            raise TransportError("The RAMSES session is closed")
        await self._transport.send_command(command)

    async def request(self, packet: RamsesPacket) -> None:
        """Publish a packet and retry it until its response arrives."""
        if packet.expected_response is None:
            raise ValueError(f"Request without an expected response: {packet}")
        if self._closed:
            raise TransportError("The RAMSES session is closed")
        request = PendingRequest(packet, packet.expected_response)
        self._pending[packet.packet_id] = request
        self._arm_retry(request)
        try:
            await self._transport.send(packet)
        except Exception:
            self._remove_request(request)
            raise

    def subscribe(self, code: str, handler: CodeHandler) -> Callable[[], None]:
        """Subscribe to decoded payloads for one code."""
        key = code.upper()
        handlers = self._code_handlers.setdefault(key, [])
        handlers.append(handler)

        def _unsubscribe() -> None:
            if handler in handlers:
                handlers.remove(handler)
            if not handlers:
                self._code_handlers.pop(key, None)

        return _unsubscribe

    def subscribe_raw(self, handler: RawHandler) -> Callable[[], None]:
        """Subscribe to every envelope, before it is decoded."""
        self._raw_handlers.append(handler)

        def _unsubscribe() -> None:
            if handler in self._raw_handlers:
                self._raw_handlers.remove(handler)

        return _unsubscribe

    def subscribe_connection(self, handler: ConnectionHandler) -> Callable[[], None]:
        """Subscribe to transport connection changes."""
        self._connection_handlers.append(handler)

        def _unsubscribe() -> None:
            if handler in self._connection_handlers:
                self._connection_handlers.remove(handler)

        return _unsubscribe

    def subscribe_version(self, handler: VersionHandler) -> Callable[[], None]:
        """Subscribe to the gateway firmware version topic."""
        self._version_handlers.append(handler)

        def _unsubscribe() -> None:
            if handler in self._version_handlers:
                self._version_handlers.remove(handler)

        return _unsubscribe

    def subscribe_latest(self, handler: VersionHandler) -> Callable[[], None]:
        """Subscribe to the newest firmware version the gateway found."""
        self._latest_handlers.append(handler)

        def _unsubscribe() -> None:
            if handler in self._latest_handlers:
                self._latest_handlers.remove(handler)

        return _unsubscribe

    async def _enqueue_frame(self, envelope: Envelope) -> None:
        """Queue one frame for the consumer."""
        if not self._closed:
            await self._frames.put(envelope)

    async def _consume_frames(self) -> None:
        """Decode and dispatch frames in arrival order."""
        while True:
            envelope = await self._frames.get()
            try:
                await self._handle_frame(envelope)
            except asyncio.CancelledError:
                raise
            except Exception:
                _LOGGER.error(
                    "Failed to process Ramses-ESP message %r",
                    envelope,
                    exc_info=True,
                )

    async def _handle_frame(self, envelope: Envelope) -> None:
        """Tap the envelope, decode the packet and notify the subscribers."""
        await self._dispatch_raw(self._raw_handlers, envelope)
        try:
            packet = RamsesPacket(envelope=envelope)
        except Exception:
            _LOGGER.error("Error parsing a received frame %s", envelope, exc_info=True)
            return
        if (code_class := CODE_REGISTRY.get(packet.code)) is None:
            _LOGGER.warning(
                "There is no class for code %s, using the generic Code", packet.code
            )
            code_class = Code
        payload = code_class(packet=packet)
        self._resolve_pending(packet)
        await self._dispatch_code(self._code_handlers.get(packet.code, ()), payload)

    async def _dispatch_raw(
        self, handlers: list[RawHandler], envelope: Envelope
    ) -> None:
        """Call every raw subscriber, isolating one failure from the others."""
        for handler in tuple(handlers):
            try:
                result = handler(envelope)
                if inspect.isawaitable(result):
                    await result
            except Exception:
                _LOGGER.error(
                    "A RAMSES subscriber failed while handling %r",
                    envelope,
                    exc_info=True,
                )

    async def _dispatch_code(
        self, handlers: list[CodeHandler] | tuple[CodeHandler, ...], payload: Code
    ) -> None:
        """Call every code subscriber, isolating one failure from the others."""
        for handler in tuple(handlers):
            try:
                result = handler(payload)
                if inspect.isawaitable(result):
                    await result
            except Exception:
                _LOGGER.error(
                    "A RAMSES subscriber failed while handling %r",
                    payload,
                    exc_info=True,
                )

    async def _dispatch_connection(
        self, handlers: list[ConnectionHandler], state: ConnectionState
    ) -> None:
        """Call every connection subscriber, isolating failures."""
        for handler in tuple(handlers):
            try:
                result = handler(state)
                if inspect.isawaitable(result):
                    await result
            except Exception:
                _LOGGER.error(
                    "A RAMSES subscriber failed while handling %r",
                    state,
                    exc_info=True,
                )

    async def _dispatch_version(
        self, handlers: list[VersionHandler], version: str
    ) -> None:
        """Call every version subscriber, isolating failures."""
        for handler in tuple(handlers):
            try:
                result = handler(version)
                if inspect.isawaitable(result):
                    await result
            except Exception:
                _LOGGER.error(
                    "A RAMSES subscriber failed while handling %r",
                    version,
                    exc_info=True,
                )

    def _resolve_pending(self, packet: RamsesPacket) -> None:
        """Remove the request that this packet answers."""
        for request in tuple(self._pending.values()):
            if request.matches(packet):
                self._remove_request(request)
                return

    def _arm_retry(self, request: PendingRequest) -> None:
        """Arm the retry timer for one pending request."""
        request.cancel_timer = self._scheduler(
            request.expected_response.timeout,
            lambda: self._retry(request),
        )

    def _retry(self, request: PendingRequest) -> None:
        """Retry a request whose response did not arrive in time."""
        if self._pending.get(request.packet.packet_id) is not request:
            return
        request.cancel_timer = None
        if request.attempts >= request.expected_response.max_retries:
            _LOGGER.warning("Request timed out: %s", request.packet)
            self._remove_request(request)
            return
        request.attempts += 1
        _LOGGER.debug(
            "Retry %s (%s/%s)",
            request.packet,
            request.attempts,
            request.expected_response.max_retries,
        )
        self._arm_retry(request)
        asyncio.get_running_loop().create_task(self._resend(request))

    async def _resend(self, request: PendingRequest) -> None:
        """Publish a retry if the request is still pending."""
        if self._pending.get(request.packet.packet_id) is not request:
            return
        try:
            await self._transport.send(request.packet)
        except Exception:
            _LOGGER.warning("Retry failed: %s", request.packet, exc_info=True)
            self._remove_request(request)

    def _remove_request(self, request: PendingRequest) -> None:
        """Forget a pending request and cancel its timer."""
        request.cancel()
        self._pending.pop(request.packet.packet_id, None)

    def _version_received(self, version: str) -> None:
        """Forward a gateway version to the subscribers."""
        asyncio.get_running_loop().create_task(
            self._dispatch_version(self._version_handlers, version)
        )

    def _latest_received(self, version: str) -> None:
        """Forward the newest firmware version to the subscribers."""
        asyncio.get_running_loop().create_task(
            self._dispatch_version(self._latest_handlers, version)
        )

    def _connection_changed(self, state: ConnectionState) -> None:
        """Forward a connection change to the subscribers."""
        asyncio.get_running_loop().create_task(
            self._dispatch_connection(self._connection_handlers, state)
        )
