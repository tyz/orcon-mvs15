import logging
import json
from homeassistant.components import mqtt

_LOGGER = logging.getLogger(__name__)


class MQTTException(Exception):
    pass


class MQTT:
    def __init__(self, hass, sub_topic, pub_topic, handle_message=None):
        self.hass = hass
        self.sub_topic = sub_topic
        self.pub_topic = pub_topic
        self.handle_message = handle_message

    async def setup(self):
        await mqtt.async_subscribe(self.hass, self.sub_topic, self.handle_message)
        _LOGGER.debug(f"[MQTT] Subscribed to {self.sub_topic}")

    async def publish(self, payload):
        try:
            _LOGGER.debug(f"[MQTT] Send payload to {self.pub_topic}: {payload}")
            await mqtt.async_publish(self.hass, self.pub_topic, json.dumps(payload))
        except Exception as e:
            raise MQTTException(f"Failed to publish payload {payload} to {self.pub_topic}: {e}")
