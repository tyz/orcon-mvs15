import logging
import asyncio
import json
from homeassistant.components import mqtt
from homeassistant.core import callback

_LOGGER = logging.getLogger(__name__)


class MQTTException(Exception):
    pass


class MQTT:
    def __init__(self, hass, base_topic, gateway_id=None):
        self.hass = hass
        self.base_topic = base_topic
        self.gateway_id = gateway_id
        self.online_topic = f"{base_topic}/+"
        self._mqtt_unsubs = []
        self._online_event = asyncio.Event()

    async def init(self):
        """Initialise class (needs asyncio so can't be done in __init__)"""
        if not self.gateway_id:
            """Auto-detect gateway if not known yet"""
            self._mqtt_unsubs.append(await mqtt.async_subscribe(self.hass, self.online_topic, self._handle_online_message))
            _LOGGER.debug(f"Subscribed to {self.online_topic}")
            await self._online_event.wait()  # wait on _handle_online_message
        else:
            _LOGGER.info(f"Using previously auto-detected gateway {self.gateway_id}")
        self.sub_topic = f"{self.base_topic}/{self.gateway_id}/rx"
        self.pub_topic = f"{self.base_topic}/{self.gateway_id}/tx"
        self.version_topic = f"{self.base_topic}/{self.gateway_id}/info/version"

    async def setup(self, handle_message, handle_version_message):
        """Setup message handlers"""
        self._mqtt_unsubs.append(await mqtt.async_subscribe(self.hass, self.sub_topic, handle_message))
        _LOGGER.debug(f"Subscribed to {self.sub_topic}")
        self._mqtt_unsubs.append(await mqtt.async_subscribe(self.hass, self.version_topic, handle_version_message))
        _LOGGER.debug(f"Subscribed to {self.version_topic}")

    @callback
    async def _handle_online_message(self, msg):
        """Message handler for online_topic"""
        self.gateway_id = msg.topic.split("/")[-1]
        _LOGGER.info(f"Auto-detected gateway is {self.gateway_id}")
        await self.remove()  # unsubscribe
        self._online_event.set()

    async def remove(self):
        """Cleanup when unloading/deconfiguring this integration"""
        for unsub in self._mqtt_unsubs:
            unsub()
        self._mqtt_unsubs = []

    async def publish(self, ramses_packet):
        """Transmit a Ramses packet"""
        payload = ramses_packet.payload()
        try:
            _LOGGER.debug(f"Send payload to {self.pub_topic} [{ramses_packet.packet_id}]: {payload}")
            await mqtt.async_publish(self.hass, self.pub_topic, json.dumps(payload))
        except Exception as e:
            raise MQTTException(f"Failed to publish payload {payload} to {self.pub_topic}: {e}")
