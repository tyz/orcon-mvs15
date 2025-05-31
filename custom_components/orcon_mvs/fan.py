import logging
from homeassistant.components.fan import FanEntity, FanEntityFeature
from homeassistant.components.persistent_notification import create, dismiss
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.device_registry import async_get as get_dev_reg
from homeassistant.const import EVENT_HOMEASSISTANT_STARTED
from homeassistant.core import CoreState
from .mqtt import MQTT
from .ramses_esp import RamsesESP
from .codes import Code22f1
from .const import (
    DOMAIN,
    CONF_GATEWAY_ID,
    CONF_REMOTE_ID,
    CONF_FAN_ID,
    CONF_CO2_ID,
    CONF_MQTT_TOPIC,
)

# TODO:
# * LICENSE
# * ramses_esp._send_queue should be a dict with a unique key per packet
# * Add USB support for Ramses ESP (https://developers.home-assistant.io/docs/creating_integration_manifest?_highlight=mqtt#usb)
# * Start home-assistant timer on timed fan modes (22F3)
# * MQTT via_device for RAMSES_ESP
# * Add logo to https://brands.home-assistant.io/

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
    _attr_preset_modes = Code22f1.presets()
    _attr_supported_features = FanEntityFeature.PRESET_MODE
    _attr_translation_key = "fan_states"  # see icons.json

    def __init__(self, hass, gateway_id, remote_id, fan_id, co2_id, mqtt_topic):
        self.hass = hass
        self._gateway_id = gateway_id
        self._remote_id = remote_id
        self._fan_id = fan_id
        self._co2_id = co2_id
        self._mqtt_topic = mqtt_topic
        self._co2 = None
        self._vent_demand = None
        self._relative_humidity = None
        self._fault_notified = False
        self._attr_name = "Orcon MVS-15 fan"
        self._attr_unique_id = f"orcon_mvs_{fan_id}"
        self._attr_preset_mode = "Auto"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, self._fan_id)},
            manufacturer="Orcon",
            model="MVS-15",
            name=f"{self.name} ({self._fan_id})",
            via_device=(DOMAIN, self._gateway_id),
        )

    @property
    def extra_state_attributes(self):
        return {
            "co2": self._co2,
            "vent_demand": self._vent_demand,
            "relative_humidity": self._relative_humidity,
        }

    async def async_added_to_hass(self):
        self.mqtt = MQTT(self.hass, f"{self._mqtt_topic}/{self._gateway_id}")
        self.ramses_esp = RamsesESP(
            hass=self.hass,
            mqtt=self.mqtt,
            gateway_id=self._gateway_id,
            remote_id=self._remote_id,
            fan_id=self._fan_id,
            co2_id=self._co2_id,
            callbacks={
                "10E0": self._device_info_callback,
                "1298": self._co2_callback,
                "12A0": self._relative_humidity_callback,
                "31D9": self._fan_state_callback,
                "31E0": self._vent_demand_callback,
            },
        )
        self.mqtt.handle_message = self.ramses_esp.handle_ramses_message
        self.mqtt.handle_version_message = self.ramses_esp.handle_ramses_version_message
        await self.mqtt.setup()

        if self.hass.state == CoreState.running:
            _LOGGER.debug("Orcon MVS-15 integration has been setup")
            self.hass.async_create_task(self.ramses_esp.setup())
        else:
            _LOGGER.debug("Orcon MVS-15 integration has been loaded after restart")
            self.hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STARTED, self.ramses_esp.setup)

    async def async_set_preset_mode(self, preset_mode: str):
        await self.ramses_esp.set_preset_mode(preset_mode)

    async def async_will_remove_from_hass(self):
        await self.mqtt.remove()
        await self.ramses_esp.remove()

    def _fan_state_callback(self, status):
        """Update fan state"""
        self._attr_preset_mode = status["fan_mode"]
        self.async_write_ha_state()
        _LOGGER.info(f"Fan mode: {self._attr_preset_mode}")
        if status["has_fault"]:
            if not self._fault_notified:
                _LOGGER.warning("Fan reported a fault")
                create(
                    self.hass,
                    "Orcon MVS-15 ventilator reported a fault",
                    title="Orcon MVS-15 error",
                    notification_id="FAN_FAULT",
                )
                self._fault_notified = True
        else:
            if self._fault_notified:
                _LOGGER.info("Fan fault cleared")
                dismiss(self.hass, "FAN_FAULT")
                self._fault_notified = False

    def _co2_callback(self, status):
        """Update CO2 sensor + attribute"""
        self._co2 = status["level"]
        if sensor := self.hass.data[DOMAIN].get("co2_sensor"):
            sensor.update_state(self._co2)
        self.async_write_ha_state()
        _LOGGER.info(f"CO2: {status['level']} ppm")

    def _vent_demand_callback(self, status):
        """Update Vent demand attribute"""
        self._vent_demand = status["percentage"]
        self.async_write_ha_state()
        _LOGGER.info(f"Vent demand: {self._vent_demand}%, unknown: {status['unknown']}")

    def _relative_humidity_callback(self, status):
        """Update relative humidity attribute"""
        self._relative_humidity = status["level"]
        if sensor := self.hass.data[DOMAIN].get("humidity_sensor"):
            sensor.update_state(self._relative_humidity)
        self.async_write_ha_state()
        _LOGGER.info(f"Relative humidty: {self._relative_humidity}%")

    def _device_info_callback(self, status):
        """Update device info"""
        dev_reg = get_dev_reg(self.hass)
        if status["manufacturer_sub_id"] != "C8":
            _LOGGER.warning("This doesn't look like an Orcon device: {status}")
            return
        if status["product_id"] == "26":
            entry = dev_reg.async_get_device({(DOMAIN, self._fan_id)})
        elif status["product_id"] == "51":
            entry = dev_reg.async_get_device({(DOMAIN, self._co2_id)})
        else:
            _LOGGER.warning(f"Unknown product_id {status['product_id']}")
            return
        dev_info = {
            "device_id": entry.id,
            "sw_version": int(status["software_ver_id"], 16),
            "model_id": status["description"],
        }
        dev_reg.async_update_device(**dev_info)
        _LOGGER.info(f"Updated device info: {dev_info}")
