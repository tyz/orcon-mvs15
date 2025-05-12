import json
import logging
from datetime import date, datetime as dt
from homeassistant.components.fan import FanEntity, FanEntityFeature
from homeassistant.components import mqtt

from .const import (
    DOMAIN,
    CONF_GATEWAY_ID,
    CONF_REMOTE_ID,
    CONF_FAN_ID,
    CONF_CO2_ID,
    CONF_MQTT_TOPIC,
    DEFAULT_TOPIC,
)

_LOGGER = logging.getLogger(__name__)

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

STATUS_MAP = {
    "00": "Away",
    "01": "Low",
    "02": "Medium",
    "03": "High",
    "04": "Auto",
}


class OrconFan(FanEntity):
    _attr_preset_modes = list(COMMAND_TEMPLATES.keys())
    _attr_supported_features = FanEntityFeature.PRESET_MODE | FanEntityFeature.TURN_ON | FanEntityFeature.TURN_OFF

    def __init__(self, hass, gateway_id, remote_id, fan_id, co2_id, mqtt_topic):
        self.hass = hass
        self._attr_name = "Orcon MVS Ventilation"
        self._attr_unique_id = f"orcon_mvs_{fan_id}"
        self._gateway_id = gateway_id
        self._remote_id = remote_id
        self._fan_id = fan_id
        self._co2_id = co2_id
        self._mqtt_topic = mqtt_topic
        self._attr_preset_mode = STATUS_MAP.get("04")
        self._co2 = None

    @property
    def extra_state_attributes(self):
        return {
            "co2": self._co2,
            "fan_id": self._fan_id,
            "gateway_id": self._gateway_id,
            "remote_id": self._remote_id,
        }

    async def async_added_to_hass(self):
        await mqtt.async_subscribe(self.hass, f"{DEFAULT_TOPIC}/+/rx", self._handle_mqtt_message)

    async def _publish_mqtt_message(self, cmd):
        topic = f"{DEFAULT_TOPIC}/{self._gateway_id}/tx"
        payload = json.dumps({"msg": cmd})
        try:
            _LOGGER.debug("[MQTT] Send payload: %s", payload)
            await mqtt.async_publish(self.hass, topic, payload)
        except Exception:
            _LOGGER.error(f"[MQTT] Failed to process payload {payload}", exc_info=True)

    async def _handle_mqtt_message(self, msg):
        try:
            payload = json.loads(msg.payload)
            _LOGGER.debug("[MQTT] Received payload: %s", payload)
            self._handle_ramses_packet(payload)
        except Exception:
            _LOGGER.error("[MQTT] Failed to process payload", exc_info=True)

    def _handle_ramses_packet(self, payload):
        msg = payload.get("msg", "")
        ts = payload.get("ts", "")
        parts = msg.split()
        if len(parts) < 8:
            _LOGGER.warning("[RAMSES] Malformed packet: %s", msg)
            return
        src = parts[3]
        code = parts[6]
        data_fields = parts[7:]
        _LOGGER.debug("[RAMSES] ts=%s src=%s code=%s data=%s", ts, src, code, data_fields)
        if src not in {self._fan_id, self._co2_id, self._gateway_id}:
            _LOGGER.debug("[RAMSES] Ignored src: %s", src)
            return
        handler = getattr(self, f"_handle_code_{code.lower()}", None)
        if callable(handler):
            try:
                handler(data_fields)
            except Exception:
                _LOGGER.error("[RAMSES] Error in handler for code %s", code, exc_info=True)
        else:
            _LOGGER.warning("[RAMSES] No handler for code: %s", code)

    def _hex_to_date(self, value):
        if value == "FFFFFFFF":
            return None
        return dt(
            year=int(value[4:8], 16),
            month=int(value[2:4], 16),
            day=int(value[:2], 16) & 0b11111,  # 1st 3 bits: DayOfWeek
        ).strftime("%Y-%m-%d")

    def _handle_code_31d9(self, fields):
        """Ventilation status"""
        if len(fields) < 2:
            _LOGGER.warning("[RAMSES] Unexpected fields for 31D9: %s", fields)
            return
        fan_mode = fields[1][4:6]
        bitmap = int(fields[1][2:4], 16)
        if (status := STATUS_MAP.get(fan_mode)):
            self._attr_preset_mode = status
            _LOGGER.info(f"[RAMSES] Fan status: {status}")
            _LOGGER.debug("Fan state: " + str({
                "passive": bool(bitmap & 0x02),
                "damper_only": bool(bitmap & 0x04),
                "filter_dirty": bool(bitmap & 0x20),
                "frost_cycle": bool(bitmap & 0x40),
                "has_fault": bool(bitmap & 0x80),
            }))
        else:
            _LOGGER.warning(f"[RAMSES] Unknown fan_mode {fan_mode}")
        self.async_write_ha_state()

    def _handle_code_1298(self, fields):
        if len(fields) < 2:
            _LOGGER.warning("[RAMSES] Unexpected fields for 1298: %s", fields)
            return
        self._co2 = int(fields[1], 16)
        _LOGGER.debug("[RAMSES] CO2 level: %d ppm", self._co2)
        self.async_write_ha_state()
        sensor = self.hass.data[DOMAIN].get("co2_sensor")
        if sensor:
            sensor.update_state(self._co2)

    def _handle_code_10e0(self, fields):
        """device info"""
        description, _, _ = fields[1][36:].partition("00")
        result = {
            "sz_oem_code": fields[1][14:16],  # 00/FF is CH/DHW, 01/6x is HVAC
            "manufacturer_group": fields[1][2:6],  # 0001-HVAC, 0002-CH/DHW
            "manufacturer_sub_id": fields[1][6:8],
            "product_id": fields[1][8:10],  # if CH/DHW: matches device_type (sometimes)
            "date_1": self._hex_to_date(fields[1][28:36]),
            "date_2": self._hex_to_date(fields[1][20:28]),
            "software_ver_id": fields[1][10:12],
            "list_ver_id": fields[1][12:14],  # if FF/01 is CH/DHW, then 01/FF
            "additional_ver_a": fields[1][16:18],
            "additional_ver_b": fields[1][18:20],
            "signature": fields[1][2:20],
            "description": bytearray.fromhex(description).decode(),
        }

    def _handle_code_31e0(self, fields):
        """ventilator demand, by co2 sensor"""
        pass

    async def async_set_preset_mode(self, preset_mode: str):
        command = COMMAND_TEMPLATES.get(preset_mode)
        if not command:
            _LOGGER.error("Unknown preset_mode: %s", preset_mode)
            return
        cmd = command.format(remote_id=self._remote_id, fan_id=self._fan_id)
        await self._publish_mqtt_message(cmd)


async def async_setup_entry(hass, entry, async_add_entities):
    config = hass.data[DOMAIN][entry.entry_id]
    gateway_id = config.get(CONF_GATEWAY_ID)
    remote_id = config.get(CONF_REMOTE_ID)
    fan_id = config.get(CONF_FAN_ID)
    co2_id = config.get(CONF_CO2_ID)
    mqtt_topic = config.get(CONF_MQTT_TOPIC)
    async_add_entities([OrconFan(hass, gateway_id, remote_id, fan_id, co2_id, mqtt_topic)])
