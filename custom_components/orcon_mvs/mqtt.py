import logging
import asyncio
import json
from homeassistant.components import mqtt

_LOGGER = logging.getLogger(__name__)


class MQTTException(Exception):
    pass


class MQTT:
    def __init__(self, hass, base_topic, handle_message, handle_version_message, gateway_id=None):
        self.hass = hass
        self.gateway_id = gateway_id
        self.base_topic = base_topic
        self.online_topic = f"{base_topic}/+"
        self.handle_message = handle_message
        self.handle_version_message = handle_version_message
        self._mqtt_unsubs = []
        self._online_event = asyncio.Event()

    async def setup(self):
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
        self._mqtt_unsubs.append(await mqtt.async_subscribe(self.hass, self.sub_topic, self.handle_message))
        _LOGGER.debug(f"Subscribed to {self.sub_topic}")
        self._mqtt_unsubs.append(await mqtt.async_subscribe(self.hass, self.version_topic, self.handle_version_message))
        _LOGGER.debug(f"Subscribed to {self.version_topic}")
        _LOGGER.debug("MQTT setup finished")

    async def _handle_online_message(self, msg):
        self.gateway_id = msg.topic.split("/")[-1]
        _LOGGER.info(f"Auto-detected gateway is {self.gateway_id}")
        await self.remove()  # unsubscribe
        self._online_event.set()

    async def remove(self):
        for unsub in self._mqtt_unsubs:
            unsub()
        self._mqtt_unsubs = []

    async def publish(self, ramses_packet):
        payload = ramses_packet.payload()
        try:
            _LOGGER.debug(f"Send payload to {self.pub_topic} [{ramses_packet.packet_id}]: {payload}")
            await mqtt.async_publish(self.hass, self.pub_topic, json.dumps(payload))
        except Exception as e:
            raise MQTTException(f"Failed to publish payload {payload} to {self.pub_topic}: {e}")
