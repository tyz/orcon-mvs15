import logging
import json
from homeassistant.components import mqtt

_LOGGER = logging.getLogger(__name__)


class MQTTException(Exception):
    pass


class MQTT:
    def __init__(self, hass, base_topic, handle_message=None, handle_version_message=None):
        self.hass = hass
        self.sub_topic = f"{base_topic}/rx"
        self.pub_topic = f"{base_topic}/tx"
        self.version_topic = f"{base_topic}/info/version"
        self.handle_message = handle_message
        self.handle_version_message = handle_version_message
        self._mqtt_unsubs = []

    async def setup(self):
        if self.handle_message:
            self._mqtt_unsubs.append(await mqtt.async_subscribe(self.hass, self.sub_topic, self.handle_message))
            _LOGGER.debug(f"Subscribed to {self.sub_topic}")
        if self.handle_version_message:
            self._mqtt_unsubs.append(await mqtt.async_subscribe(self.hass, self.version_topic, self.handle_version_message))
            _LOGGER.debug(f"Subscribed to {self.version_topic}")

    async def remove(self):
        for unsub in self._mqtt_unsubs:
            unsub()

    async def publish(self, ramses_packet):
        payload = ramses_packet.payload()
        try:
            _LOGGER.debug(f"Send payload to {self.pub_topic}: {payload}")
            await mqtt.async_publish(self.hass, self.pub_topic, json.dumps(payload))
        except Exception as e:
            raise MQTTException(f"Failed to publish payload {payload} to {self.pub_topic}: {e}")
