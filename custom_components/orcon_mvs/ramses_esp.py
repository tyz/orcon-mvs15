import logging
import asyncio
import json
from datetime import datetime as dt
from .ramses_packet import RamsesPacket, RamsesPacket_SetFanMode, RamsesPacket_ReqFanState

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

    def __init__(self, mqtt, gateway_id, remote_id, fan_id, co2_id, fan_mode_callback, co2_callback, vent_demand_callback):
        self.gateway_id = gateway_id
        self.remote_id = remote_id
        self.fan_id = fan_id
        self.co2_id = co2_id
        self.mqtt = mqtt
        self.fan_mode_callback = fan_mode_callback
        self.co2_callback = co2_callback
        self.vent_demand_callback = vent_demand_callback

    async def setup(self, event):
        await asyncio.sleep(1)  # FIXME: wait on mqtt ready state instead?
        rfs = RamsesPacket_ReqFanState(src_id=self.gateway_id, dst_id=self.fan_id)
        await self.mqtt.publish(rfs)

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

    def _hex_to_date(self, value):
        """From ramses_rf"""
        if value == "FFFFFFFF":
            return None
        return dt(
            year=int(value[4:8], 16),
            month=int(value[2:4], 16),
            day=int(value[:2], 16) & 0b11111,  # 1st 3 bits: DayOfWeek
        ).strftime("%Y-%m-%d")

    def _handle_code_31d9(self, data):
        """Ventilation status"""
        fan_mode = data[4:6]
        bitmap = int(data[2:4], 16)
        if status := self.STATUS_MAP.get(fan_mode):
            if self.fan_mode_callback:
                self.fan_mode_callback(status)
            _LOGGER.debug(
                f"Fan state: {status}, "
                + str(
                    {
                        "passive": bool(bitmap & 0x02),
                        "damper_only": bool(bitmap & 0x04),
                        "filter_dirty": bool(bitmap & 0x20),
                        "frost_cycle": bool(bitmap & 0x40),
                        "has_fault": bool(bitmap & 0x80),
                    }
                )
            )
        else:
            _LOGGER.error(f"Unknown fan_mode {fan_mode}")

    def _handle_code_1298(self, data):
        """CO2 sensor"""
        if self.co2_callback:
            self.co2_callback(int(data, 16))

    def _handle_code_10e0(self, data):
        """Device info"""
        description, _, _ = data[36:].partition("00")
        _LOGGER.debug(
            str(
                {
                    "sz_oem_code": data[14:16],  # 00/FF is CH/DHW, 01/6x is HVAC
                    "manufacturer_group": data[2:6],  # 0001-HVAC, 0002-CH/DHW
                    "manufacturer_sub_id": data[6:8],
                    "product_id": data[8:10],  # if CH/DHW: matches device_type (sometimes)
                    "date_1": self._hex_to_date(data[28:36]),
                    "date_2": self._hex_to_date(data[20:28]),
                    "software_ver_id": data[10:12],
                    "list_ver_id": data[12:14],  # if FF/01 is CH/DHW, then 01/FF
                    "additional_ver_a": data[16:18],
                    "additional_ver_b": data[18:20],
                    "signature": data[2:20],
                    "description": bytearray.fromhex(description).decode(),
                }
            )
        )

    def _handle_code_31e0(self, data):
        """ventilator demand, by co2 sensor"""
        vent_demand = int(int(data[4:6], 16) / 2)
        if self.vent_demand_callback:
            self.vent_demand_callback(vent_demand)
