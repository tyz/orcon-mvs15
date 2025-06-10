import logging

from datetime import timedelta

from homeassistant.components.fan import FanEntity, FanEntityFeature
from homeassistant.components.persistent_notification import create, dismiss
from homeassistant.helpers.device_registry import async_get as get_dev_reg
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.helpers import entity_platform
from homeassistant.const import EVENT_HOMEASSISTANT_STARTED
from homeassistant.core import CoreState

from .codes import Code22f1
from .sensor import Co2Sensor
from .const import (
    DOMAIN,
    CONF_GATEWAY_ID,
    CONF_REMOTE_ID,
    CONF_FAN_ID,
    CONF_CO2_ID,
    CONF_MQTT_TOPIC,
)

# TODO:
# * pytest
# * LICENSE
# * Add USB support for Ramses ESP (https://developers.home-assistant.io/docs/creating_integration_manifest?_highlight=mqtt#usb)
# * Start home-assistant timer on timed fan modes (22F3)
# * MQTT via_device for RAMSES_ESP
# * Auto discovery
#   - use async_setup_platform?
#   - turn off/on the fan unit, fan_id == src_id of 1st msg 042F
#   - bind as remote with random remote_id (1FC9)
#   - [DONE] Discover CO2: remote_id is a type I, code 31E0 to fan_id
#   - Discover humidity: create sensor after first successful pull
# * Add logo to https://brands.home-assistant.io/
# * Req 10e0, 31e0 and 1298 when CO2 discovered

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass, entry, async_add_entities):
    platform = entity_platform.async_get_current_platform()
    async_add_entities([OrconFan(hass, entry, platform)])
    return True


class OrconFan(FanEntity):
    _attr_preset_modes = Code22f1.presets()
    _attr_supported_features = FanEntityFeature.PRESET_MODE
    _attr_translation_key = "fan_states"  # see icons.json

    def __init__(self, hass, entry, platform):
        self.hass = hass
        self._entry = entry
        self._platform = platform
        self.coordinator = entry.runtime_data.coordinator
        self._mqtt_topic = entry.data.get(CONF_MQTT_TOPIC)
        self._gateway_id = entry.data.get(CONF_GATEWAY_ID)
        self._remote_id = entry.data.get(CONF_REMOTE_ID)
        self._fan_id = entry.data.get(CONF_FAN_ID)
        self._co2_id = entry.data.get(CONF_CO2_ID)
        self._co2 = None
        self._notification_id = None
        self._ramses_esp = entry.runtime_data.ramses_esp
        self._req_humidity_unsub = None
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
        data = self.coordinator.data
        return {
            "co2": data.get("co2"),
            "vent_demand": data.get("vent_demand"),
            "relative_humidity": data.get("relative_humidity"),
            "has_fault": data.get("has_fault"),
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
        self._req_humidity_unsub()
        await self._ramses_esp.remove()
        self._report_fault(clear=True)

    async def _add_co2_sensor(self, co2_id):
        self._co2_id = co2_id
        """Store CONF_CO2_ID in config"""
        new_data = {**self._entry.data, CONF_CO2_ID: self._co2_id}
        self.hass.config_entries.async_update_entry(self._entry, data=new_data)
        """Create sensor"""
        co2_sensor = Co2Sensor(self._co2_id, self._fan_id, self.coordinator)
        await self._platform.async_add_entities([co2_sensor])
        _LOGGER.info(
            f"Discovered CO2 sensor {self._co2_id} created and stored in config"
        )

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

    def _fan_state_callback(self, payload):
        """Update fan preset mode"""
        self._attr_preset_mode = payload.values["fan_mode"]
        new_data = {
            **self.coordinator.data,
            "has_fault": payload.values["has_fault"],
            "fan_rssi": payload.values["rssi"],
        }
        self.coordinator.async_set_updated_data(new_data)
        self.async_write_ha_state()
        _LOGGER.info(
            f"Current fan mode: {self._attr_preset_mode}, "
            f"has_fault: {payload.values['has_fault']}, "
            f"RSSI: {payload.values['rssi']} dBm"
        )
        if payload.values["has_fault"]:
            self._report_fault()
        else:
            self._report_fault(clear=True)

    def _co2_callback(self, payload):
        """Update CO2 sensor + attribute"""
        new_data = {
            **self.coordinator.data,
            "co2": payload.values["level"],
            "co2_rssi": payload.values["rssi"],
        }
        self.coordinator.async_set_updated_data(new_data)
        self.async_write_ha_state()
        _LOGGER.info(
            f"Current CO2 level: {payload.values['level']} ppm, RSSI: {payload.values['rssi']} dBm"
        )

    def _vent_demand_callback(self, payload):
        """Update Vent demand attribute"""
        if not self._co2_id:
            self.hass.async_create_task(self._add_co2_sensor(payload.packet.src_id))
        new_data = {
            **self.coordinator.data,
            "vent_demand": payload.values["percentage"],
            "co2_rssi": payload.values["rssi"],
        }
        self.coordinator.async_set_updated_data(new_data)
        self.async_write_ha_state()
        _LOGGER.info(
            f"Vent demand: {payload.values['percentage']}%, "
            f"unknown: {payload.values['unknown']}, "
            f"RSSI: {payload.values['rssi']} dBm"
        )

    def _relative_humidity_callback(self, payload):
        """Update relative humidity attribute"""
        new_data = {
            **self.coordinator.data,
            "relative_humidity": payload.values["level"],
            "fan_rssi": payload.values["rssi"],
        }
        self.coordinator.async_set_updated_data(new_data)
        self.async_write_ha_state()
        _LOGGER.info(
            f"Current humidity level: {payload.values['level']}%, RSSI: {payload.values['rssi']} dBm"
        )
        if not self._req_humidity_unsub:
            poll_interval = 5
            self._req_humidity_unsub = async_track_time_interval(
                self.hass,
                self._ramses_esp.req_humidity,
                timedelta(minutes=poll_interval),
            )
            _LOGGER.info(
                f"Humidity sensor detected, fetching value every {poll_interval} minutes"
            )

    def _device_info_callback(self, payload):
        """Update device info"""
        dev_reg = get_dev_reg(self.hass)
        if payload.values["manufacturer_sub_id"] != "C8":
            _LOGGER.warning("This doesn't look like an Orcon device: {payload.values}")
            return
        if payload.values["product_id"] == "26":
            entry = dev_reg.async_get_device({(DOMAIN, self._fan_id)})
        elif payload.values["product_id"] == "51":
            entry = dev_reg.async_get_device({(DOMAIN, self._co2_id)})
        else:
            _LOGGER.warning(f"Unknown product_id {payload.values['product_id']}")
            return
        dev_info = {
            "device_id": entry.id,
            "sw_version": int(payload.values["software_ver_id"], 16),
            "model_id": payload.values["description"],
        }
        dev_reg.async_update_device(**dev_info)
        _LOGGER.info(
            f"Updated device info: {dev_info}, RSSI: {payload.values['rssi']} dBm"
        )
