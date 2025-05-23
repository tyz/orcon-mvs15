import os
import logging
import asyncio
import json
from datetime import timedelta
from homeassistant.helpers.event import async_track_time_interval
from .ramses_packet import RamsesPacket
from .payloads import (  # noqa: F401
    Code,
    Code042f,
    Code1060,
    Code10e0,
    Code10e1,
    Code1298,
    Code12a0,
    Code1fc9,
    Code22f1,
    Code22f3,
    Code31d9,
    Code31e0,
)

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
            payload = json.loads(msg.payload)
            self._handle_ramses_packet(payload)
            await self.packet_log(payload)
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
            _LOGGER.warning(f"Class Code{packet.code.lower()} not imported, or does not exist")
            code_class = Code
        payload = code_class(packet=packet)
        if packet.type == "RQ":
            """Don't call callback function on something we send ourselves (TODO: timed fan with 22f3)"""
            return
        if packet.code in self.callbacks:
            self.callbacks[packet.code](payload.values)

    async def packet_log(self, payload, path="/config/packet.log", max_size=1_000_000):
        """Log raw packets to disk, rolling over at 1 MB, offloaded to executor."""

        def _sync_log():
            if not hasattr(self, "_log_f") or self._log_f is None:
                try:
                    self._log_f = open(path, "a")
                except Exception as e:
                    _LOGGER.error("Error opening %s: %s", path, e)
                    return

            print(f"{payload['ts']} {payload['msg']}", file=self._log_f)
            self._log_f.flush()

            if os.path.getsize(path) > max_size:
                try:
                    self._log_f.close()
                except Exception:
                    pass
                for i in range(5, 0, -1):
                    src = f"{path}{'' if i==1 else f'.{i-1}'}"
                    dst = f"{path}.{i}"
                    try:
                        os.replace(src, dst)
                    except FileNotFoundError:
                        continue
                try:
                    self._log_f = open(path, "a")
                except Exception as e:
                    _LOGGER.error("Error reopening %s: %s", path, e)

        await self.hass.async_add_executor_job(_sync_log)
