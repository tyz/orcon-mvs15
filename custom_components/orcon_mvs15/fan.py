import logging
from homeassistant.components.fan import FanEntity, FanEntityFeature
from homeassistant.components.persistent_notification import create, dismiss
from homeassistant.helpers.device_registry import async_get as get_dev_reg
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.const import EVENT_HOMEASSISTANT_STARTED
from homeassistant.core import CoreState
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
# * Add USB support for Ramses ESP (https://developers.home-assistant.io/docs/creating_integration_manifest?_highlight=mqtt#usb)
# * Start home-assistant timer on timed fan modes (22F3)
# * MQTT via_device for RAMSES_ESP
# * Auto discovery
#   - use async_setup_platform?
#   - turn off/on fan, fan_id == msg 042F
#   - bind as remote with random remote_id (1FC9)
#   - auto-detect CO2: remote_id is a type I, code 1298 to fan_id
#   - auto-detect humidity: create sensor after first succesfull pull
# * Add logo to https://brands.home-assistant.io/
# * Create RemoteEntity for fan

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass, entry, async_add_entities):
    async_add_entities([OrconFan(hass, entry)])


class OrconFan(FanEntity):
    _attr_preset_modes = Code22f1.presets()
    _attr_supported_features = FanEntityFeature.PRESET_MODE
    _attr_translation_key = "fan_states"  # see icons.json

    def __init__(self, hass, config_entry):
        self.hass = hass
        self.pull_coordinator = config_entry.runtime_data.pull_coordinator
        self.push_coordinator = config_entry.runtime_data.push_coordinator
        self._config_entry = config_entry
        self._mqtt_topic = config_entry.data.get(CONF_MQTT_TOPIC)
        self._gateway_id = config_entry.data.get(CONF_GATEWAY_ID)  # auto-detected
        self._remote_id = config_entry.data.get(CONF_REMOTE_ID)
        self._fan_id = config_entry.data.get(CONF_FAN_ID)
        self._co2_id = config_entry.data.get(CONF_CO2_ID)
        self._co2 = None
        self._notification_id = None
        self._ramses_esp = config_entry.runtime_data.ramses_esp
        self._attr_name = "Orcon MVS-15 fan"
        self._attr_unique_id = f"orcon_mvs15_{self._fan_id}"
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
        pull_data = self.pull_coordinator.data
        push_data = self.push_coordinator.data
        return {
            "co2": push_data.get("co2"),
            "vent_demand": push_data.get("vent_demand"),
            "relative_humidity": pull_data.get("relative_humidity"),
            "has_fault": push_data.get("has_fault"),
        }

    async def async_added_to_hass(self):
        if self.hass.state == CoreState.running:
            _LOGGER.info("Orcon MVS-15 integration has been setup")
            self.hass.async_create_task(self.setup())
        else:
            _LOGGER.info("Orcon MVS-15 integration has been loaded after restart")
            self.hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STARTED, self.setup)

    async def setup(self, event=None):
        self._ramses_esp.add_callback("10E0", self._device_info_callback)
        self._ramses_esp.add_callback("1298", self._co2_callback)
        self._ramses_esp.add_callback("12A0", self._relative_humidity_callback)
        self._ramses_esp.add_callback("31D9", self._fan_state_callback)
        self._ramses_esp.add_callback("31E0", self._vent_demand_callback)
        await self._ramses_esp.setup(event)

    async def async_set_preset_mode(self, preset_mode: str):
        await self._ramses_esp.set_preset_mode(preset_mode)

    async def async_will_remove_from_hass(self):
        await self._ramses_esp.remove()
        self._report_fault(clear=True)

    def _report_fault(self, clear=False):
        if clear:
            if self._notification_id:
                dismiss(self.hass, self._notification_id)
                self._notification_id = None
                _LOGGER.info("Fan fault notification cleared")
            return
        if self._notification_id:
            return  # already reported
        _LOGGER.warning("Fan reported a fault, notifying")
        self._notification_id = f"FAN_FAULT-{self._fan_id}"
        create(
            self.hass,
            "Orcon MVS-15 ventilator reported a fault",
            title="Orcon MVS-15 error",
            notification_id=self._notification_id,
        )

    def _fan_state_callback(self, status):
        """Update fan preset mode"""
        self._attr_preset_mode = status["fan_mode"]
        new_data = {**self.push_coordinator.data, "has_fault": status["has_fault"]}
        self.push_coordinator.async_set_updated_data(new_data)
        self.async_write_ha_state()
        _LOGGER.info(f"Current fan mode: {self._attr_preset_mode}, has_fault: {status['has_fault']}")
        if status["has_fault"]:
            self._report_fault()
        else:
            self._report_fault(clear=True)

    def _co2_callback(self, status):
        """Update CO2 sensor + attribute"""
        new_data = {**self.push_coordinator.data, "co2": status["level"]}
        self.push_coordinator.async_set_updated_data(new_data)
        self.async_write_ha_state()
        _LOGGER.info(f"Current CO2 level: {status['level']} ppm")

    def _vent_demand_callback(self, status):
        """Update Vent demand attribute"""
        new_data = {**self.push_coordinator.data, "vent_demand": status["percentage"]}
        self.push_coordinator.async_set_updated_data(new_data)
        self.async_write_ha_state()
        _LOGGER.info(f"Vent demand: {status['percentage']}%, unknown: {status['unknown']}")

    def _relative_humidity_callback(self, status):
        """Update relative humidity attribute"""
        new_data = {**self.pull_coordinator.data, "relative_humidity": status["level"]}
        self.pull_coordinator.async_set_updated_data(new_data)
        self.async_write_ha_state()
        _LOGGER.info(f"Current humidity level: {status['level']}%")

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
