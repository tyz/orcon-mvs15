from __future__ import annotations

import os
import logging
import asyncio
import json

from collections.abc import Callable
from typing import TextIO
from datetime import datetime

from homeassistant.components import mqtt as mqtt_client
from homeassistant.components.mqtt import ReceiveMessage
from homeassistant.core import HomeAssistant, Event
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers.event import async_call_later
from homeassistant.helpers.device_registry import async_get as get_dev_reg

from .ramses_packet import RamsesPacket, RamsesID
from .ramses_packet_queue import RamsesPacketQueue
from .mqtt import MQTT
from .const import DOMAIN
from .codes import *  # noqa: F403

# flake8: noqa: F405

_LOGGER = logging.getLogger(__name__)


class RamsesESPException(Exception):
    pass


class RamsesESP:
    def __init__(
        self,
        hass: HomeAssistant,
        mqtt: MQTT,
        remote_id: RamsesID,
        fan_id: RamsesID,
        co2_id: RamsesID,
        gateway_id: RamsesID,
    ) -> None:
        self.hass = hass
        self.mqtt = mqtt
        self.remote_id = remote_id
        self.fan_id = fan_id
        self.co2_id = co2_id
        self.gateway_id = gateway_id
        self._handlers: dict = {}
        self._send_queue = RamsesPacketQueue()
        self._log_f: TextIO | None = None
        if self.co2_id:
            _LOGGER.info(f"Using previously discovered CO2 sensor ({self.co2_id})")
        else:
            _LOGGER.info(
                "CO2 sensor has not yet been discovered, waiting for vent_demand announcement to the fan"
            )

    async def setup(self, event: Event | None = None) -> None:
        if not await mqtt_client.async_wait_for_mqtt_client(self.hass):
            raise ConfigEntryNotReady("MQTT integration is not available")
        await self.mqtt.setup(
            self.handle_ramses_mqtt_message, self.handle_ramses_mqtt_version_message
        )
        if event:  # only on Home-Assistant restart
            """sleep for a bit, mqtt (or the stick) is not ready yet for some reason"""
            await asyncio.sleep(2)
        await self.init_fan()
        if self.co2_id:
            await self.init_co2()

    async def init_fan(self) -> None:
        """Fetch current fan state + device info on startup"""
        await self.publish(Code10e0.get(src_id=self.gateway_id, dst_id=self.fan_id))
        await self.publish(Code12a0.get(src_id=self.gateway_id, dst_id=self.fan_id))
        await self.publish(Code31d9.get(src_id=self.gateway_id, dst_id=self.fan_id))

    async def init_co2(self) -> None:
        """Fetch current CO2 sensor state + device info on startup or discovery"""
        await self.publish(Code10e0.get(src_id=self.gateway_id, dst_id=self.co2_id))
        await self.publish(Code1298.get(src_id=self.gateway_id, dst_id=self.co2_id))
        await self.publish(Code31e0.get(src_id=self.gateway_id, dst_id=self.co2_id))

    async def req_humidity(self, now: datetime | None = None) -> None:
        """12A0 is not announced so we need to fetch it ourselves
        Will be called by async_track_time_interval, if the 12A0 call from self.setup responds"""
        await self.publish(Code12a0.get(src_id=self.gateway_id, dst_id=self.fan_id))

    async def publish(self, packet: RamsesPacket) -> None:
        await self.mqtt.publish(packet)
        if not packet.expected_response:
            return
        packet.expected_response.cancel_retry_handler = async_call_later(
            # Try again if expected_response wasn't received within packet.expected_response.timeout seconds
            self.hass,
            packet.expected_response.timeout,
            lambda now, pkt=packet: self._schedule_retry(pkt),
        )
        self._send_queue.add(packet)

    async def handle_ramses_mqtt_message(self, msg: ReceiveMessage) -> None:
        """Decode JSON, parse the MQTT payload and log it to file"""
        try:
            envelope = json.loads(msg.payload)
            await self._handle_ramses_packet(envelope)
            await self.packet_log(envelope)
        except Exception:
            _LOGGER.error(
                f"Failed to process Ramses-ESP MQTT message {msg.payload}",
                exc_info=True,
            )

    async def handle_ramses_mqtt_version_message(self, msg: ReceiveMessage) -> None:
        """Update Ramses-ESP device"""
        dev_reg = get_dev_reg(self.hass)
        if (entry := dev_reg.async_get_device({(DOMAIN, self.gateway_id)})) is None:
            return
        dev_info = {
            "device_id": entry.id,
            "sw_version": msg.payload,
        }
        dev_reg.async_update_device(**dev_info)
        _LOGGER.info(f"Updated device info: {dev_info}")

    async def set_preset_mode(self, mode: str) -> None:
        try:
            packet = Code22f1.set(value=mode, src_id=self.remote_id, dst_id=self.fan_id)
        except Exception as e:
            _LOGGER.error(f"Error setting fan preset mode '{mode}': {e}")
            return
        _LOGGER.info(f"Setting fan preset mode to {mode}")
        await self.publish(packet)

    def add_handler(self, code: str, func: Callable) -> None:
        _LOGGER.debug(f"Adding handler for code {code}")
        self._handlers[code] = func

    def remove_handler(self, code: str) -> None:
        _LOGGER.debug(f"Remove handler for code {code}")
        del self._handlers[code]

    def _schedule_retry(self, packet: RamsesPacket) -> None:
        self.hass.loop.call_soon_threadsafe(
            lambda: self.hass.async_create_task(self._retry_pending_request(packet))
        )

    async def _retry_pending_request(self, packet: RamsesPacket) -> None:
        """Outgoing request timed out, retry it"""
        assert packet.expected_response is not None
        packet.expected_response.max_retries -= 1
        if packet.expected_response.max_retries < 0:
            _LOGGER.warning(f"Request timed out: {packet}")
            self._send_queue.remove(packet)
            return
        _LOGGER.debug(f"Retry {packet}")
        await self.publish(packet)

    async def _handle_ramses_packet(self, envelope: dict) -> None:
        try:
            packet = RamsesPacket(envelope=envelope)
        except Exception:
            _LOGGER.error(f"Error parsing MQTT message {envelope}", exc_info=True)
            return
        if (code_class := globals().get(f"Code{packet.code.lower()}")) is None:
            _LOGGER.warning(
                f"Class Code{packet.code.lower()} not imported, or does not exist"
            )
            code_class = Code
        payload = code_class(packet=packet)
        if packet.src_id not in {
            self.fan_id,
            self.co2_id,
            self.gateway_id,
            self.remote_id,
        }:
            if (
                not self.co2_id
                and packet.type == "I"
                and packet.code == "31E0"
                and packet.length == 8
                and packet.dst_id == self.fan_id
            ):
                """Fan received a vent demand payload, that's our CO2 sensor, handler func will handle it"""
                self.co2_id = packet.src_id
                _LOGGER.debug(f"Discovered CO2 sensor ({self.co2_id})")
            else:
                return
        if packet.type == "RQ":
            """Don't call handler function on something we send ourselves (TODO: needed w/ timed fan with 22f3)"""
            return
        if (q_packet := self._send_queue.get(packet)) is not None:
            self._send_queue.remove(q_packet)
        if packet.code in self._handlers:
            self._handlers[packet.code](payload)

    async def packet_log(
        self,
        envelope: dict,
        path: str = "/config/packet.log",
        max_size: int = 10_000_000,
    ) -> None:
        """Log raw packets to disk, rolling over at 10 MB, offloaded to executor."""

        def _sync_log() -> None:
            if self._log_f is None:
                try:
                    self._log_f = open(path, "a")
                except Exception as e:
                    _LOGGER.error("Error opening %s: %s", path, e)
                    return

            print(f"{envelope['ts']} {envelope['msg']}", file=self._log_f)
            self._log_f.flush()

            if os.path.getsize(path) > max_size:
                try:
                    self._log_f.close()
                except Exception:
                    pass
                for i in range(10, 0, -1):  # keep up to 10 old log files
                    src = f"{path}{'' if i == 1 else f'.{i - 1}'}"
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
