"""RAMSES ESP transport over the firmware's HGI80 serial console.

The firmware prints every received frame as an HGI80 line and accepts an
outgoing frame as a console command. The gateway id is derived from the board's
factory MAC address, which the USB serial number also carries.
"""

from __future__ import annotations

import asyncio
import logging
import re

from collections.abc import Callable
from datetime import UTC, datetime

from ...protocol.frame import RamsesID, RamsesPacket
from ..base import (
    ConnectionHandler,
    ConnectionState,
    Envelope,
    PacketHandler,
    TransportError,
    VersionHandler,
)
from .backend import SerialBackend

_LOGGER = logging.getLogger(__name__)

MAX_LINE_LENGTH = 1024
FRAME_QUEUE_SIZE = 100
GATEWAY_CLASS = 18
GATEWAY_ID_MASK = 0x3FFFF

_FRAME_RE = re.compile(r"^(?:\d{3}|---) +(?:RQ|RP|I|W) +--- ")
_BANNER_RE = re.compile(r"^#\s*(\S+)\s+(\S+)\s*$")
_MAC_RE = re.compile(r"^[0-9A-Fa-f]{2}(?:[:\-][0-9A-Fa-f]{2}){5}$")


def gateway_id_from_serial(serial_number: str | None) -> RamsesID:
    """Derive the gateway id from the USB serial number (the factory MAC).

    The firmware takes the last three MAC bytes, masks them to 18 bits and
    prefixes the gateway class. A serial number that is not a six-byte MAC
    yields an empty id rather than an id that would never match.
    """
    if serial_number is None or not _MAC_RE.match(serial_number.strip()):
        return RamsesID()
    octets = [int(part, 16) for part in re.split(r"[:\-]", serial_number.strip())]
    device_id = ((octets[3] << 16) | (octets[4] << 8) | octets[5]) & GATEWAY_ID_MASK
    return RamsesID(f"{GATEWAY_CLASS:02d}:{device_id:06d}")


class RamsesESPSerial:
    """Talk to a Ramses ESP stick over its USB serial port.

    The backend supplies the bytes; this class owns the line framing, the
    timestamps the session expects and the gateway identity.
    """

    def __init__(
        self,
        backend: SerialBackend,
        gateway_id: RamsesID = RamsesID(),
    ) -> None:
        self._backend = backend
        self._gateway_id = gateway_id
        self._version_handlers: list[VersionHandler] = []
        self._connection_handlers: list[ConnectionHandler] = []
        self._connection_state = ConnectionState.DISCONNECTED
        self._frames: asyncio.Queue[Envelope] = asyncio.Queue(FRAME_QUEUE_SIZE)
        self._consumer: asyncio.Task[None] | None = None
        self._buffer = bytearray()
        self._started = False
        self._closing = False

    @property
    def gateway_id(self) -> RamsesID:
        return self._gateway_id

    @property
    def connection_state(self) -> ConnectionState:
        return self._connection_state

    async def init(self) -> None:
        """Resolve the gateway id before start() opens the port."""
        if self._gateway_id:
            _LOGGER.info("Using the configured gateway %s", self._gateway_id)
            return
        try:
            serial_number = await self._backend.serial_number()
        except Exception as err:
            raise TransportError(
                f"Could not read the USB serial number of the gateway: {err}"
            ) from err
        self._gateway_id = gateway_id_from_serial(serial_number)
        if not self._gateway_id:
            raise TransportError(
                "Could not derive the gateway id from the USB serial number "
                f"{serial_number!r}"
            )
        _LOGGER.info("Discovered gateway %s over USB", self._gateway_id)

    async def start(self, handle_packet: PacketHandler) -> None:
        """Open the port and start delivering frames."""
        if self._started:
            return
        self._consumer = asyncio.create_task(self._consume_frames(handle_packet))
        try:
            await self._backend.start(self._handle_data, self._handle_closed)
        except Exception as err:
            await self._stop_consumer()
            raise TransportError(f"Could not open the USB gateway: {err}") from err
        self._started = True
        self._set_connection(ConnectionState.CONNECTED)

    async def stop(self) -> None:
        """Close the port and stop delivering frames."""
        self._closing = True
        try:
            if self._started:
                await self._backend.stop()
        except Exception as err:
            _LOGGER.debug("Closing the USB gateway failed: %s", err)
        finally:
            self._started = False
            self._closing = False
            self._buffer.clear()
            await self._stop_consumer()
            self._set_connection(ConnectionState.DISCONNECTED)

    async def send(self, packet: RamsesPacket) -> None:
        """Write one packet as the console command the firmware expects."""
        if not self._started:
            raise TransportError("The USB gateway is not connected")
        msg = packet.ramses_esp_envelope()["msg"]
        try:
            _LOGGER.debug("Send serial frame [%s]: %s", packet.packet_id, msg)
            await self._backend.write(f"{msg}\r".encode("ascii"))
        except TransportError:
            raise
        except Exception as err:
            raise TransportError(f"Failed to send serial frame {msg!r}: {err}") from err

    def subscribe_version(self, handler: VersionHandler) -> Callable[[], None]:
        """Subscribe to the gateway firmware version."""
        self._version_handlers.append(handler)
        return lambda: self._version_handlers.remove(handler)

    def subscribe_connection(self, handler: ConnectionHandler) -> Callable[[], None]:
        """Subscribe to connection state changes."""
        self._connection_handlers.append(handler)
        return lambda: self._connection_handlers.remove(handler)

    async def _consume_frames(self, handle_packet: PacketHandler) -> None:
        """Deliver queued frames in arrival order."""
        while True:
            envelope = await self._frames.get()
            try:
                await handle_packet(envelope)
            except Exception:
                _LOGGER.error(
                    "Failed to deliver a serial frame %r", envelope, exc_info=True
                )

    async def _stop_consumer(self) -> None:
        if self._consumer is None:
            return
        self._consumer.cancel()
        try:
            await self._consumer
        except asyncio.CancelledError:
            pass
        self._consumer = None

    def _handle_data(self, data: bytes) -> None:
        """Split a chunk into lines and pass each complete line on."""
        self._buffer.extend(data)
        while (end := self._buffer.find(b"\n")) >= 0:
            line = bytes(self._buffer[:end]).rstrip(b"\r")
            del self._buffer[: end + 1]
            self._handle_line(line)
        if len(self._buffer) > MAX_LINE_LENGTH:
            _LOGGER.warning(
                "Dropping an oversized serial line of %s bytes", len(self._buffer)
            )
            self._buffer.clear()

    def _handle_line(self, line: bytes) -> None:
        try:
            text = line.decode("ascii").strip()
        except UnicodeDecodeError:
            _LOGGER.debug("Ignoring a non-ASCII serial line")
            return
        if not text:
            return
        if text.startswith("#"):
            self._handle_console_line(text)
            return
        if not _FRAME_RE.match(text):
            _LOGGER.debug("Ignoring a non-frame serial line: %s", text)
            return
        envelope: Envelope = {"ts": datetime.now(UTC).isoformat(), "msg": text}
        try:
            self._frames.put_nowait(envelope)
        except asyncio.QueueFull:
            _LOGGER.warning("Dropping a serial frame because the queue is full")

    def _handle_console_line(self, text: str) -> None:
        match = _BANNER_RE.match(text)
        if match is None or not match.group(1).lower().startswith("ramses"):
            return
        version = match.group(2)
        _LOGGER.info("Gateway firmware version is %s", version)
        for handler in tuple(self._version_handlers):
            handler(version)

    def _handle_closed(self, exc: Exception | None) -> None:
        if self._closing:
            return
        _LOGGER.warning("The USB gateway disconnected: %s", exc or "unknown reason")
        self._set_connection(ConnectionState.DISCONNECTED)

    def _set_connection(self, state: ConnectionState) -> None:
        if state == self._connection_state:
            return
        self._connection_state = state
        for handler in tuple(self._connection_handlers):
            handler(state)
