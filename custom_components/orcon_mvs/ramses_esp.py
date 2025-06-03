import os
import logging
import asyncio
import json
from homeassistant.helpers.event import async_call_later
from .ramses_packet import RamsesPacket
from .ramses_packet_queue import RamsesPacketQueue
from .mqtt import MQTT
from .codes import (  # noqa: F401
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
    def __init__(self, hass, mqtt_base_topic, remote_id, fan_id, co2_id, gateway_id, callbacks):
        self.hass = hass
        self.mqtt = MQTT(
            hass, mqtt_base_topic, self.handle_ramses_message, self.handle_ramses_version_message, gateway_id=gateway_id
        )
        self.remote_id = remote_id
        self.fan_id = fan_id
        self.co2_id = co2_id
        self.gateway_id = gateway_id
        self.callbacks = callbacks
        self._send_queue = RamsesPacketQueue()

    async def setup(self, event=None):
        await self.mqtt.setup()
        if event:  # only on Home-Assistant restart
            await asyncio.sleep(2)  # FIXME: wait on mqtt ready state instead?
        self.gateway_id = self.mqtt.gateway_id
        if not self.gateway_id:
            """Auto-detected"""
            self.gateway_id = self.mqtt.gateway_id
        """Update fan/co2/humidty/device state"""
        await self.publish(Code31d9.get(src_id=self.gateway_id, dst_id=self.fan_id))
        await self.publish(Code12a0.get(src_id=self.gateway_id, dst_id=self.fan_id))
        await self.publish(Code1298.get(src_id=self.gateway_id, dst_id=self.co2_id))
        await self.publish(Code31e0.get(src_id=self.gateway_id, dst_id=self.co2_id))
        await self.publish(Code10e0.get(src_id=self.gateway_id, dst_id=self.fan_id))
        await self.publish(Code10e0.get(src_id=self.gateway_id, dst_id=self.co2_id))

    async def remove(self):
        await self._send_queue.empty()
        await self.mqtt.remove()

    async def req_humidity(self, now):
        """Is not being announced by the fan, so we have to fetch it ourselves"""
        await self.publish(Code12a0.get(src_id=self.gateway_id, dst_id=self.fan_id))

    async def publish(self, packet):
        await self.mqtt.publish(packet)
        if not packet.expected_response:
            return
        # Try again if expected_response wasn't received within packet.expected_response.timeout seconds
        packet.expected_response.cancel_retry_handler = async_call_later(
            self.hass,
            packet.expected_response.timeout,
            lambda now, pkt=packet: self._schedule_retry(pkt),
        )
        await self._send_queue.add(packet)

    async def handle_ramses_message(self, msg):
        """Decode JSON, parse the payload and log it to file"""
        try:
            payload = json.loads(msg.payload)
            await self._handle_ramses_packet(payload)
            await self.packet_log(payload)
        except Exception:
            _LOGGER.error(f"Failed to process Ramses payload {msg}", exc_info=True)

    async def handle_ramses_version_message(self, msg):
        """Could create the Rames-ESP device?"""
        pass

    async def set_preset_mode(self, mode):
        try:
            packet = Code22f1.set(preset=mode, src_id=self.remote_id, dst_id=self.fan_id)
        except Exception as e:
            _LOGGER.error(f"Error setting fan preset mode '{mode}': {e}")
            return
        _LOGGER.info(f"Setting fan preset mode to {mode}")
        await self.publish(packet)

    def _schedule_retry(self, packet):
        self.hass.loop.call_soon_threadsafe(lambda: self.hass.async_create_task(self._retry_pending_request(packet)))

    async def _retry_pending_request(self, packet):
        """Outgoing request timed out, retry it"""
        packet.expected_response.max_retries -= 1
        if packet.expected_response.max_retries < 0:
            _LOGGER.warning(f"Request timed out: {packet}")
            await self._send_queue.remove(packet)
            return
        _LOGGER.debug(f"Retry {packet}")
        await self.publish(packet)

    async def _handle_ramses_packet(self, packet):
        try:
            packet = RamsesPacket(packet)
        except Exception:
            _LOGGER.error(f"Error parsing MQTT message {packet}", exc_info=True)
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
        if (q_packet := await self._send_queue.match(packet)) is not None:
            await self._send_queue.remove(q_packet)
        if packet.code in self.callbacks:
            self.callbacks[packet.code](payload.values)

    async def packet_log(self, payload, path="/config/packet.log", max_size=10_000_000):
        """Log raw packets to disk, rolling over at 10 MB, offloaded to executor."""

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
                for i in range(10, 0, -1):  # keep up to 10 old log files
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
