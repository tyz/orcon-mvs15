import logging
from datetime import timedelta
from homeassistant.components.fan import FanEntity, FanEntityFeature
from homeassistant.components.persistent_notification import create, dismiss
from homeassistant.helpers.device_registry import async_get as get_dev_reg
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.const import EVENT_HOMEASSISTANT_STARTED
from homeassistant.core import CoreState
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
# * Rewrite to use DataUpdateCoordinator
# * Add USB support for Ramses ESP (https://developers.home-assistant.io/docs/creating_integration_manifest?_highlight=mqtt#usb)
# * Start home-assistant timer on timed fan modes (22F3)
# * MQTT via_device for RAMSES_ESP
# * Add ramses-esp as device/via_device again
# * Auto discovery
#   - use async_setup_platform?
#   - turn off/on fan, fan_id == msg 042F
#   - bind as remote with random remote_id (1FC9)
#   - auto-detect CO2: remote_id is a type I, code 1298 to fan_id
#   - auto-detect humidity: create sensor after first succesfull poll
# * Add logo to https://brands.home-assistant.io/
# * Add ramses-esp as device/via_device again

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass, entry, async_add_entities):
    async_add_entities([OrconFan(hass, entry)])


class OrconFan(FanEntity):
    _attr_preset_modes = Code22f1.presets()
    _attr_supported_features = FanEntityFeature.PRESET_MODE
    _attr_translation_key = "fan_states"  # see icons.json

    def __init__(self, hass, config_entry):
        self.hass = hass
        self._config_entry = config_entry
        self._mqtt_topic = config_entry.data.get(CONF_MQTT_TOPIC)
        self._gateway_id = config_entry.data.get(CONF_GATEWAY_ID)  # auto-detected
        self._remote_id = config_entry.data.get(CONF_REMOTE_ID)
        self._fan_id = config_entry.data.get(CONF_FAN_ID)
        self._co2_id = config_entry.data.get(CONF_CO2_ID)
        self._co2 = None
        self._vent_demand = None
        self._relative_humidity = None
        self._fault_notified = False
        self._req_humidity_unsub = None
        self._attr_name = "Orcon MVS-15 fan"
        self._attr_unique_id = f"orcon_mvs_{self._fan_id}"
        self._attr_preset_mode = "Auto"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, self._fan_id)},
            manufacturer="Orcon",
            model="MVS-15",
            name=f"{self.name} ({self._fan_id})",
        )

    @property
    def extra_state_attributes(self):
        return {
            "co2": self._co2,
            "vent_demand": self._vent_demand,
            "relative_humidity": self._relative_humidity,
        }

    async def async_added_to_hass(self):
        self.ramses_esp = RamsesESP(
            hass=self.hass,
            mqtt_base_topic=self._mqtt_topic,
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

        if self.hass.state == CoreState.running:
            _LOGGER.info("Orcon MVS-15 integration has been setup")
            self.hass.async_create_task(self.setup())
        else:
            _LOGGER.info("Orcon MVS-15 integration has been loaded after restart")
            self.hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STARTED, self.setup)

    async def setup(self, event=None):
        await self.ramses_esp.setup(event)
        if not self._gateway_id:
            _LOGGER.debug(f"Storing auto-detected gateway {self.ramses_esp.gateway_id} in config")
            new_data = {**self._config_entry.data, CONF_GATEWAY_ID: self.ramses_esp.gateway_id}
            self.hass.config_entries.async_update_entry(self._config_entry, data=new_data)

    async def async_set_preset_mode(self, preset_mode: str):
        await self.ramses_esp.set_preset_mode(preset_mode)

    async def async_will_remove_from_hass(self):
        if callable(self._req_humidity_unsub):
            self._req_humidity_unsub()
        await self.ramses_esp.remove()

    def _fan_state_callback(self, status):
        """Update fan state"""
        self._attr_preset_mode = status["fan_mode"]
        self.async_write_ha_state()
        _LOGGER.info(f"Current fan mode: {self._attr_preset_mode}")
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
        _LOGGER.info(f"Current CO2 level: {status['level']} ppm")

    def _vent_demand_callback(self, status):
        """Update Vent demand attribute"""
        self._vent_demand = status["percentage"]
        self.async_write_ha_state()
        _LOGGER.info(f"Vent demand: {self._vent_demand}%, unknown: {status['unknown']}")

    def _relative_humidity_callback(self, status):
        """Update relative humidity attribute"""
        poll_interval = 5
        self._relative_humidity = status["level"]
        if sensor := self.hass.data[DOMAIN].get("humidity_sensor"):
            sensor.update_state(self._relative_humidity)
        self.async_write_ha_state()
        _LOGGER.info(f"Current humidity level: {self._relative_humidity}%")
        if not self._req_humidity_unsub:
            self._req_humidity_unsub = async_track_time_interval(
                self.hass, self.ramses_esp.req_humidity, timedelta(minutes=poll_interval)
            )
            _LOGGER.info(f"Humidity sensor detected, fetching value every {poll_interval} minutes")

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
