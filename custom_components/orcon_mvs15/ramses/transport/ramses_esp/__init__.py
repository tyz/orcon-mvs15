"""RAMSES ESP transport: gateway discovery, topics and the JSON envelope."""

from __future__ import annotations

import asyncio
import json
import logging

from collections.abc import Callable

from ...protocol.frame import RamsesID, RamsesPacket
from ..base import (
    ConnectionState,
    Envelope,
    PacketHandler,
    TransportError,
    VersionHandler,
)
from .backend import MqttBackend

_LOGGER = logging.getLogger(__name__)

type ConnectionCallback = Callable[[bool], None]


class RamsesEspTransport:
    """Talk to a Ramses ESP stick over MQTT.

    The transport owns the topic layout and the receive envelope. The host
    only supplies the MQTT operations, so the same transport works with Home
    Assistant, a test double or an offline tool.
    """

    def __init__(
        self,
        backend: MqttBackend,
        base_topic: str,
        gateway_id: RamsesID = RamsesID(),
        discovery_timeout: float = 10.0,
        connection_callback: ConnectionCallback | None = None,
    ) -> None:
        self._backend = backend
        self._base_topic = base_topic
        self._gateway_id = gateway_id
        self._discovery_timeout = discovery_timeout
        self._connection_callback = connection_callback
        self._packet_handler: PacketHandler | None = None
        self._version_handler: VersionHandler | None = None
        self._unsubs: list[Callable[[], None]] = []
        self._discovery_event = asyncio.Event()
        self._connection_state = ConnectionState.DISCONNECTED
        self.online_topic = f"{base_topic}/+"
        self.sub_topic = ""
        self.pub_topic = ""
        self.version_topic = ""

    @property
    def gateway_id(self) -> RamsesID:
        return self._gateway_id

    @property
    def connection_state(self) -> ConnectionState:
        return self._connection_state

    async def init(self) -> None:
        """Discover the gateway when it was not configured, then set topics."""
        if not self._gateway_id:
            unsub = await self._backend.subscribe(
                self.online_topic, self._handle_online_message
            )
            try:
                async with asyncio.timeout(self._discovery_timeout):
                    await self._discovery_event.wait()
            except TimeoutError as err:
                raise TransportError(
                    f"No gateway message on {self.online_topic} within "
                    f"{self._discovery_timeout} seconds"
                ) from err
            finally:
                unsub()
            _LOGGER.info(f"Discovered gateway is {self._gateway_id}")
        else:
            _LOGGER.info(f"Using previously discovered gateway {self._gateway_id}")
        self.sub_topic = f"{self._base_topic}/{self._gateway_id}/rx"
        self.pub_topic = f"{self._base_topic}/{self._gateway_id}/tx"
        self.version_topic = f"{self._base_topic}/{self._gateway_id}/info/version"

    async def start(
        self, handle_packet: PacketHandler, handle_version: VersionHandler
    ) -> None:
        await self._backend.start()
        self._packet_handler = handle_packet
        self._version_handler = handle_version
        self._unsubs.append(
            await self._backend.subscribe(self.sub_topic, self._handle_packet_message)
        )
        self._unsubs.append(
            await self._backend.subscribe(
                self.version_topic, self._handle_version_message
            )
        )
        self._unsubs.append(
            self._backend.subscribe_connection(self._handle_connection_status)
        )
        # The current connection state is read, not announced: nothing changed
        # at startup and the session should not treat it as a transition.
        self._connection_state = (
            ConnectionState.CONNECTED
            if self._backend.is_connected()
            else ConnectionState.DISCONNECTED
        )

    async def stop(self) -> None:
        while self._unsubs:
            self._unsubs.pop()()
        await self._backend.stop()
        self._connection_state = ConnectionState.DISCONNECTED
        _LOGGER.debug("Unsubscribed from all MQTT topics")

    async def send(self, packet: RamsesPacket) -> None:
        """Publish one packet as a Ramses ESP JSON envelope."""
        envelope = packet.ramses_esp_envelope()
        try:
            _LOGGER.debug(
                f"Send envelope to {self.pub_topic} [{packet.packet_id}]: {envelope}"
            )
            await self._backend.publish(self.pub_topic, json.dumps(envelope))
        except TransportError:
            raise
        except Exception as err:
            raise TransportError(
                f"Failed to publish payload {envelope} to {self.pub_topic}: {err}"
            ) from err

    async def _handle_packet_message(
        self, topic: str, payload: str | bytes | bytearray
    ) -> None:
        try:
            envelope: Envelope = json.loads(payload)
        except TypeError, ValueError:
            _LOGGER.error(
                f"Failed to process Ramses-ESP MQTT message {payload!r}",
                exc_info=True,
            )
            return
        if self._packet_handler is not None:
            await self._packet_handler(envelope)

    async def _handle_version_message(
        self, topic: str, payload: str | bytes | bytearray
    ) -> None:
        version = (
            payload.decode() if isinstance(payload, (bytes, bytearray)) else payload
        )
        if self._version_handler is not None:
            self._version_handler(version)

    async def _handle_online_message(
        self, topic: str, payload: str | bytes | bytearray
    ) -> None:
        if self._gateway_id:
            _LOGGER.debug(f"Ignoring new MQTT message in {self.online_topic}")
            return
        self._gateway_id = RamsesID(topic.split("/")[-1])
        self._discovery_event.set()

    def _handle_connection_status(self, connected: bool) -> None:
        state = ConnectionState.CONNECTED if connected else ConnectionState.DISCONNECTED
        if state == self._connection_state:
            return
        self._connection_state = state
        if connected:
            _LOGGER.info("MQTT connection restored")
        else:
            _LOGGER.info("MQTT connection lost; the fan is unavailable")
        if self._connection_callback is not None:
            self._connection_callback(connected)
