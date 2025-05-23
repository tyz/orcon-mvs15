import logging
import asyncio
import json
from datetime import timedelta
from homeassistant.helpers.event import async_track_time_interval
from .ramses_packet import RamsesPacket
from .payloads import Code, Code10e0, Code1298, Code12a0, Code22f1, Code31d9, Code31e0  # noqa: F401

_LOGGER = logging.getLogger(__name__)


class RamsesESPException(Exception):
    pass


class RamsesESP:
    def __init__(self, hass, mqtt, gateway_id, remote_id, fan_id, co2_id, callbacks):
        self.hass = hass
        self.mqtt = mqtt
        self.gateway_id = gateway_id
        self.remote_id = remote_id
        self.fan_id = fan_id
        self.co2_id = co2_id
        self.callbacks = callbacks

    async def setup(self, event):
        """Fetch fan, CO2 and vent demand state on startup"""
        await asyncio.sleep(2)  # FIXME: wait on mqtt ready state instead?
        await self.mqtt.publish(Code31d9.get(src_id=self.gateway_id, dst_id=self.fan_id))
        await self.mqtt.publish(Code12a0.get(src_id=self.gateway_id, dst_id=self.fan_id))
        await self.mqtt.publish(Code1298.get(src_id=self.gateway_id, dst_id=self.co2_id))
        await self.mqtt.publish(Code31e0.get(src_id=self.gateway_id, dst_id=self.co2_id))
        self._req_humidity_interval = async_track_time_interval(self.hass, self._req_humidity, timedelta(minutes=5))

    async def _req_humidity(self, now):
        await self.mqtt.publish(Code12a0.get(src_id=self.gateway_id, dst_id=self.fan_id))

    async def handle_mqtt_message(self, msg):
        try:
            self._handle_ramses_packet(json.loads(msg.payload))
        except Exception:
            _LOGGER.error("Failed to process MQTT payload {msg}", exc_info=True)

    async def set_preset_mode(self, mode):
        try:
            sfm = Code22f1.set(preset=mode, src_id=self.remote_id, dst_id=self.fan_id)
        except Exception:
            _LOGGER.error(f"Error setting fan preset mode: {mode}")
            return
        _LOGGER.info(f"Setting fan preset mode to {mode}")
        await self.mqtt.publish(sfm)

    def _handle_ramses_packet(self, mqtt_msg):
        try:
            packet = RamsesPacket(mqtt_msg)
        except Exception:
            _LOGGER.error(f"Error parsing MQTT message {mqtt_msg}", exc_info=True)
            return
        if packet.src_id not in {self.fan_id, self.co2_id, self.gateway_id}:
            return
        if (code_class := globals().get(f"Code{packet.code.lower()}")) is None:
            code_class = Code
        payload = code_class(packet=packet)
        _LOGGER.debug(payload)
        if packet.type == "RQ":
            """Don't call handler on something we send ourselves"""
            return
        if packet.code in self.callbacks:
            self.callbacks[packet.code](payload.values)
