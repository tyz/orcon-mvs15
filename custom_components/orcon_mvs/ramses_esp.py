import os
import logging
import asyncio
import json
from datetime import timedelta
from homeassistant.helpers.event import async_track_time_interval, async_call_later
from homeassistant.helpers.device_registry import async_get as get_dev_reg
from .ramses_packet import RamsesPacket
from .const import DOMAIN
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
    def __init__(self, hass, mqtt, gateway_id, remote_id, fan_id, co2_id, callbacks):
        self.hass = hass
        self.mqtt = mqtt
        self.gateway_id = gateway_id
        self.remote_id = remote_id
        self.fan_id = fan_id
        self.co2_id = co2_id
        self.callbacks = callbacks
        self._send_queue_lock = asyncio.Lock()
        self._send_queue = []
        self._retry_timeout = 2

    async def setup(self, event=None):
        """Fetch fan, CO2 and vent demand state on startup"""
        if event:  # only on Home-Assistant restart
            await asyncio.sleep(2)  # FIXME: wait on mqtt ready state instead?
        await self.publish(Code31d9.get(src_id=self.gateway_id, dst_id=self.fan_id))
        await self.publish(Code12a0.get(src_id=self.gateway_id, dst_id=self.fan_id))
        await self.publish(Code1298.get(src_id=self.gateway_id, dst_id=self.co2_id))
        await self.publish(Code31e0.get(src_id=self.gateway_id, dst_id=self.co2_id))
        await self.publish(Code10e0.get(src_id=self.gateway_id, dst_id=self.fan_id))
        await self.publish(Code10e0.get(src_id=self.gateway_id, dst_id=self.co2_id))
        self._req_humidity_unsub = async_track_time_interval(self.hass, self._req_humidity, timedelta(minutes=5))

    async def remove(self):
        if hasattr(self, "_req_humidity_unsub") and callable(self._req_humidity_unsub):
            self._req_humidity_unsub()
        async with self._send_queue_lock:
            if not self._send_queue:
                return
            for q_packet in self._send_queue:
                q_packet.expected_response.cancel_retry_handler()

    async def _req_humidity(self, now):
        await self.publish(Code12a0.get(src_id=self.gateway_id, dst_id=self.fan_id))

    async def publish(self, packet):
        await self.mqtt.publish(packet)
        if not packet.expected_response:
            return
        packet.expected_response.cancel_retry_handler = async_call_later(
            # Try again if expected_response wasn't received
            self.hass,
            self._retry_timeout,
            lambda now, pkt=packet: self._schedule_retry(pkt),
        )
        self._send_queue.append(packet)

    async def handle_ramses_message(self, msg):
        try:
            payload = json.loads(msg.payload)
            await self._handle_ramses_packet(payload)
            await self.packet_log(payload)
        except Exception:
            _LOGGER.error("Failed to process MQTT payload {msg}", exc_info=True)

    async def handle_ramses_version_message(self, msg):
        dev_reg = get_dev_reg(self.hass)
        entry = dev_reg.async_get_device({(DOMAIN, self.gateway_id)})
        dev_info = {
            "device_id": entry.id,
            "sw_version": msg.payload,
        }
        dev_reg.async_update_device(**dev_info)
        _LOGGER.info(f"Updated device info: {dev_info}")

    async def set_preset_mode(self, mode):
        try:
            sfm = Code22f1.set(preset=mode, src_id=self.remote_id, dst_id=self.fan_id)
        except Exception:
            _LOGGER.error(f"Error setting fan preset mode: {mode}")
            return
        _LOGGER.info(f"Setting fan preset mode to {mode}")
        await self.publish(sfm)

    def _schedule_retry(self, packet):
        self.hass.loop.call_soon_threadsafe(lambda: self.hass.async_create_task(self._retry_pending_request(packet)))

    async def _retry_pending_request(self, packet):
        """Outgoing request timed out, retry it"""
        async with self._send_queue_lock:
            if not self._send_queue:
                _LOGGER.error("_send_queue empty in _retry_pending_request??")
                return
            self._send_queue = [x for x in self._send_queue if x.expected_response != packet]
        packet.expected_response.max_retries -= 1
        if packet.expected_response.max_retries < 0:
            _LOGGER.debug(f"Removing from queue: Timed out {packet}")
            return
        _LOGGER.debug(f"Retry {packet}")
        await self.publish(packet)  # will add packet back to _send_queue

    async def _ack_request(self, packet):
        """Check if an incoming packet is an expected response to a request"""
        async with self._send_queue_lock:
            if not self._send_queue:
                return
            new_queue = []
            for q_packet in self._send_queue:
                if q_packet.expected_response == packet:
                    _LOGGER.debug(f"Removing from queue: Got expected response for {packet}")
                    q_packet.expected_response.cancel_retry_handler()
                else:
                    new_queue.append(q_packet)
            self._send_queue = new_queue

    async def _handle_ramses_packet(self, packet):
        try:
            packet = RamsesPacket(packet)
        except Exception:
            _LOGGER.error(f"Error parsing MQTT message {packet}", exc_info=True)
            return
        if packet.src_id not in {self.fan_id, self.co2_id, self.gateway_id}:
            return
        await self._ack_request(packet)
        if (code_class := globals().get(f"Code{packet.code.lower()}")) is None:
            _LOGGER.warning(f"Class Code{packet.code.lower()} not imported, or does not exist")
            code_class = Code
        payload = code_class(packet=packet)
        if packet.type == "RQ":
            """Don't call callback function on something we send ourselves (TODO: timed fan with 22f3)"""
            return
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
