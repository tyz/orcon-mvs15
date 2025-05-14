import logging
from homeassistant.components.fan import FanEntity, FanEntityFeature
from homeassistant.const import EVENT_HOMEASSISTANT_STARTED
from .mqtt import MQTT
from .ramses_esp import RamsesESP
from .const import (
    DOMAIN,
    CONF_GATEWAY_ID,
    CONF_REMOTE_ID,
    CONF_FAN_ID,
    CONF_CO2_ID,
    CONF_MQTT_TOPIC,
)

# TODO:
# * Move ramses packet handling + checks to its own class
# * Add USB support for Ramses ESP

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass, entry, async_add_entities):
    config = hass.data[DOMAIN][entry.entry_id]
    gateway_id = config.get(CONF_GATEWAY_ID)
    remote_id = config.get(CONF_REMOTE_ID)
    fan_id = config.get(CONF_FAN_ID)
    co2_id = config.get(CONF_CO2_ID)
    mqtt_topic = config.get(CONF_MQTT_TOPIC)
    async_add_entities([OrconFan(hass, gateway_id, remote_id, fan_id, co2_id, mqtt_topic)])


class OrconFan(FanEntity):
    _attr_preset_modes = list(RamsesESP.COMMAND_TEMPLATES.keys())
    _attr_supported_features = FanEntityFeature.PRESET_MODE

    def __init__(self, hass, gateway_id, remote_id, fan_id, co2_id, mqtt_topic):
        self.hass = hass
        self._attr_name = "Orcon MVS Ventilation"
        self._attr_unique_id = f"orcon_mvs_{fan_id}"
        self._gateway_id = gateway_id
        self._remote_id = remote_id
        self._fan_id = fan_id
        self._co2_id = co2_id
        self._mqtt_topic = mqtt_topic
        self._attr_preset_mode = RamsesESP.STATUS_MAP.get("04")
        self._co2 = None
        self._vent_demand = None

    @property
    def extra_state_attributes(self):
        return {
            "co2": self._co2,
            "vent_demand": self._vent_demand,
        }

    async def async_added_to_hass(self):
        sub_topic = f"{self._mqtt_topic}/{self._gateway_id}/rx"
        pub_topic = f"{self._mqtt_topic}/{self._gateway_id}/tx"
        self._mqtt = MQTT(self.hass, sub_topic, pub_topic)
        self.ramses_esp = RamsesESP(
            mqtt=self._mqtt,
            gateway_id=self._gateway_id,
            remote_id=self._remote_id,
            fan_id=self._fan_id,
            co2_id=self._co2_id,
            fan_mode_callback=self.fan_mode_callback,
            co2_callback=self.co2_callback,
            vent_demand_callback=self.vent_demand_callback,
        )
        self._mqtt.handle_message = self.ramses_esp.handle_mqtt_message
        await self._mqtt.setup()
        self.hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STARTED, self.ramses_esp.setup)

    async def async_set_preset_mode(self, preset_mode: str):
        await self.ramses_esp.set_preset_mode(preset_mode)

    def fan_mode_callback(self, status):
        self._attr_preset_mode = status
        self.async_write_ha_state()
        _LOGGER.info(f"Fan mode: {status}")

    def co2_callback(self, status):
        if sensor := self.hass.data[DOMAIN].get("co2_sensor"):
            sensor.update_state(status)
            self._co2 = status
            self.async_write_ha_state()
            _LOGGER.info(f"CO2: {status}")

    def vent_demand_callback(self, status):
        self._vent_demand = status
        self.async_write_ha_state()
        _LOGGER.info(f"Vent demand: {status}")
