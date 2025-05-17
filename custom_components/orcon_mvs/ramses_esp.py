import logging
import asyncio
import json
from .ramses_packet import (
    RamsesPacket,
    RamsesPacket_SetFanMode,
    RamsesPacket_ReqFanState,
    RamsesPacket_ReqCO2State,
    RamsesPacket_ReqVentDemandState,
)

_LOGGER = logging.getLogger(__name__)


class RamsesESPException(Exception):
    pass


class RamsesESP:
    STATUS_MAP = {
        "00": "Away",
        "01": "Low",
        "02": "Medium",
        "03": "High",
        "04": "Auto",
    }

    def __init__(self, mqtt, gateway_id, remote_id, fan_id, co2_id, callbacks):
        self.gateway_id = gateway_id
        self.remote_id = remote_id
        self.fan_id = fan_id
        self.co2_id = co2_id
        self.mqtt = mqtt
        self.callbacks = callbacks

    async def setup(self, event):
        """Fetch fan, CO2 and vent demand state on startup"""
        await asyncio.sleep(1)  # FIXME: wait on mqtt ready state instead?
        await self.mqtt.publish(RamsesPacket_ReqFanState(src_id=self.gateway_id, dst_id=self.fan_id))
        await self.mqtt.publish(RamsesPacket_ReqCO2State(src_id=self.gateway_id, dst_id=self.co2_id))
        await self.mqtt.publish(RamsesPacket_ReqVentDemandState(src_id=self.gateway_id, dst_id=self.co2_id))

    async def handle_mqtt_message(self, msg):
        try:
            self._handle_ramses_packet(json.loads(msg.payload))
        except Exception:
            _LOGGER.error("Failed to process payload {msg}", exc_info=True)

    async def set_preset_mode(self, mode):
        try:
            sfm = RamsesPacket_SetFanMode(preset=mode, src_id=self.remote_id, dst_id=self.fan_id)
        except Exception:
            _LOGGER.error(f"Error setting fan preset mode: {mode}")
            return
        _LOGGER.info(f"Setting fan preset mode to {mode}")
        await self.mqtt.publish(sfm)

    def _handle_ramses_packet(self, payload):
        try:
            packet = RamsesPacket(payload)
        except Exception:
            _LOGGER.error(f"Error parsing packet {payload}", exc_info=True)
            return
        if packet.src_id not in {self.fan_id, self.co2_id, self.gateway_id}:
            return
        if packet.type == "RQ":
            """Don't call handler on something we send ourselves"""
            return
        handler = getattr(self, f"_handle_code_{packet.code.lower()}", None)
        if not callable(handler):
            _LOGGER.warning(f"No handler for code: {packet.code}")
            return
        try:
            handler(packet.data)
        except Exception:
            _LOGGER.error(f"Error in handler for code {packet.code}", exc_info=True)

    def _handle_code_31d9(self, data):
        """Ventilation status"""
        fan_mode = data[4:6]
        if status := self.STATUS_MAP.get(fan_mode):
            if "31D9" in self.callbacks:
                self.callbacks["31D9"](status)
        else:
            _LOGGER.error(f"Unknown fan_mode {fan_mode}")

    def _handle_code_1298(self, data):
        """CO2 sensor"""
        if "1298" in self.callbacks:
            value = int(data, 16)
            self.callbacks["1298"](value)

    def _handle_code_10e0(self, data):
        """Device info"""
        if "10E0" in self.callbacks:
            self.callbacks["10E0"](data)

    def _handle_code_31e0(self, data):
        """ventilator demand, by co2 sensor"""
        if "31E0" in self.callbacks:
            value = int(int(data[4:6], 16) / 2)
            self.callbacks["31E0"](value)
