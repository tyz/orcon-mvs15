import logging
import asyncio
import json
from datetime import datetime as dt
from .ramses_packet import RamsesPacket

_LOGGER = logging.getLogger(__name__)


class RamsesESPException(Exception):
    pass


class RamsesESP:
    COMMAND_TEMPLATES = {
        "Auto": " I --- {remote_id} {fan_id} --:------ 22F1 003 000404",
        "Low": " I --- {remote_id} {fan_id} --:------ 22F1 003 000104",
        "Medium": " I --- {remote_id} {fan_id} --:------ 22F1 003 000204",
        "High": " I --- {remote_id} {fan_id} --:------ 22F1 003 000304",
        "High (15m)": " I --- {remote_id} {fan_id} --:------ 22F3 007 00020F03040000",
        "High (30m)": " I --- {remote_id} {fan_id} --:------ 22F3 007 00021E03040000",
        "High (60m)": " I --- {remote_id} {fan_id} --:------ 22F3 007 00023C03040000",
        "Away": " I --- {remote_id} {fan_id} --:------ 22F1 003 000004",
    }

    REQ_STATUS_TEMPLATE = " RQ --- {gateway_id} {fan_id} --:------ 31D9 001 00"

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

    def _create_payload(self, cmd):
        return {"msg": cmd}

    async def setup(self, event):
        await asyncio.sleep(2)  # FIXME: wait on mqtt ready state instead?
        cmd = self._create_payload(self.REQ_STATUS_TEMPLATE.format(gateway_id=self.gateway_id, fan_id=self.fan_id))
        await self.mqtt.publish(cmd)

    async def handle_mqtt_message(self, msg):
        try:
            self._handle_ramses_packet(json.loads(msg.payload))
        except Exception:
            _LOGGER.error("[MQTT] Failed to process payload {msg}", exc_info=True)

    async def set_preset_mode(self, mode):
        command = self.COMMAND_TEMPLATES.get(mode)
        if not command:
            _LOGGER.error(f"Unknown preset_mode: {mode}")
            return
        cmd = self._create_payload(command.format(remote_id=self.remote_id, fan_id=self.fan_id))
        await self.mqtt.publish(cmd)

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
            _LOGGER.warning(f"[RAMSES] No handler for code: {packet.code}")
            return
        try:
            handler(packet.data)
        except Exception:
            _LOGGER.error(f"[RAMSES] Error in handler for code {packet.code}", exc_info=True)

    def _hex_to_date(self, value):
        """from ramses_rf"""
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
                f"[RAMES] Fan state: {status}, "
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
            _LOGGER.error(f"[RAMSES] Unknown fan_mode {fan_mode}")

    def _handle_code_1298(self, data):
        """co2 sensor"""
        if self.co2_callback:
            self.co2_callback(int(data, 16))

    def _handle_code_10e0(self, data):
        """device info"""
        description, _, _ = data[36:].partition("00")
        _LOGGER.debug(
            "[RAMSES] "
            + str(
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
