from __future__ import annotations

import logging
import asyncio
import json

from collections.abc import Callable
from homeassistant.components import mqtt
from homeassistant.components.mqtt import ReceiveMessage
from homeassistant.core import callback, HomeAssistant

from .ramses_packet import RamsesPacket, RamsesID

_LOGGER = logging.getLogger(__name__)


class MQTTException(Exception):
    pass


class MQTT:
    def __init__(
        self,
        hass: HomeAssistant,
        base_topic: str,
        gateway_id: RamsesID = RamsesID(),
        discovery_timeout: float = 10.0,
        connection_callback: Callable[[bool], None] | None = None,
    ) -> None:
        self.hass = hass
        self.base_topic = base_topic
        self.gateway_id = gateway_id
        self.discovery_timeout = discovery_timeout
        self.connection_callback = connection_callback
        self.online_topic = f"{base_topic}/+"
        self._mqtt_unsubs: list = []
        self._online_event = asyncio.Event()
        self._connected = False

    async def init(self) -> None:
        if not self.gateway_id:
            unsub = await self._subscribe(
                self.online_topic, self._handle_online_message
            )
            try:
                async with asyncio.timeout(self.discovery_timeout):
                    await self._online_event.wait()
            except TimeoutError as err:
                raise MQTTException(
                    f"No gateway message on {self.online_topic} within "
                    f"{self.discovery_timeout} seconds"
                ) from err
            finally:
                self._unsubscribe(unsub)
            _LOGGER.info(f"Discovered gateway is {self.gateway_id}")
        else:
            _LOGGER.info(f"Using previously discovered gateway {self.gateway_id}")
        self.sub_topic = f"{self.base_topic}/{self.gateway_id}/rx"
        self.pub_topic = f"{self.base_topic}/{self.gateway_id}/tx"
        self.version_topic = f"{self.base_topic}/{self.gateway_id}/info/version"

    async def setup(
        self, handle_message: Callable, handle_version_message: Callable
    ) -> None:
        """Setup message handlers"""
        await self._subscribe(self.sub_topic, handle_message)
        await self._subscribe(self.version_topic, handle_version_message)
        unsub = mqtt.async_subscribe_connection_status(
            self.hass, self._handle_connection_status
        )
        self._mqtt_unsubs.append(unsub)
        self._connected = mqtt.is_connected(self.hass)

    @callback
    def _handle_connection_status(self, connected: bool) -> None:
        """Log each MQTT connection transition once and forward it."""
        if connected == self._connected:
            return
        self._connected = connected
        if connected:
            _LOGGER.info("MQTT connection restored")
        else:
            _LOGGER.info("MQTT connection lost; the fan is unavailable")
        if self.connection_callback is not None:
            self.connection_callback(connected)

    async def _subscribe(self, topic: str, handler: Callable) -> Callable[[], None]:
        _LOGGER.debug(f"Subscribed to {topic}")
        unsub = await mqtt.async_subscribe(self.hass, topic, handler)
        self._mqtt_unsubs.append(unsub)
        return unsub

    def _unsubscribe(self, unsub: Callable[[], None]) -> None:
        if unsub in self._mqtt_unsubs:
            self._mqtt_unsubs.remove(unsub)
        unsub()

    @callback
    async def _handle_online_message(self, msg: ReceiveMessage) -> None:
        """Message handler for online_topic"""
        _LOGGER.debug(f"Received MQTT message in {self.online_topic}: {msg}")
        if self.gateway_id:
            _LOGGER.debug(f"Ignoring new MQTT message in {self.online_topic}")
            return
        self.gateway_id = RamsesID(msg.topic.split("/")[-1])
        self._online_event.set()

    def cleanup(self) -> None:
        """Cleanup when unloading/deconfiguring this integration"""
        while self._mqtt_unsubs:
            self._mqtt_unsubs.pop()()
        _LOGGER.debug("Unsubscribed from all MQTT topics")

    async def publish(self, ramses_packet: RamsesPacket) -> None:
        """Transmit a Ramses_ESP envelope"""
        envelope = ramses_packet.ramses_esp_envelope()
        try:
            _LOGGER.debug(
                f"Send envelope to {self.pub_topic} [{ramses_packet.packet_id}]: {envelope}"
            )
            await mqtt.async_publish(self.hass, self.pub_topic, json.dumps(envelope))
        except Exception as e:
            raise MQTTException(
                f"Failed to publish payload {envelope} to {self.pub_topic}: {e}"
            )
