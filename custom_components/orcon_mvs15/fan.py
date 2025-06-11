import logging
import asyncio

from datetime import timedelta

from homeassistant.components.fan import FanEntity, FanEntityFeature
from homeassistant.helpers.device_registry import async_get as get_dev_reg
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.event import async_track_time_interval
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
# * pytest
# * LICENSE
# * Add USB support for Ramses ESP (https://developers.home-assistant.io/docs/creating_integration_manifest?_highlight=mqtt#usb)
# * Start home-assistant timer on timed fan modes (22F3)
# * MQTT via_device for RAMSES_ESP
# * Auto discovery
#   - Discover fan_id: turn off/on the fan unit, fan_id == src_id of 1st 042F message
#   - Bind as remote with random remote_id (1FC9)
#   - or: Discover existing remote by 22F1/22F3 messages to use that remote_id
#   - [DONE] Discover CO2: remote_id is a type I, code 31E0 to fan_id
#   - Discover humidity: create sensor only after first successful pull
# * Add logo to https://brands.home-assistant.io/
# * Req 10e0, 31e0 and 1298 after CO2 sensors have been created

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass, entry, async_add_entities):
    async_add_entities([OrconFan(hass, entry)])
    return True


class OrconFan(FanEntity):
    _attr_preset_modes = Code22f1.presets()
    _attr_supported_features = FanEntityFeature.PRESET_MODE
    _attr_translation_key = "fan_states"  # see icons.json
    _attr_name = "Orcon MVS-15 fan"
    _attr_preset_mode = "Auto"

    def __init__(self, hass, entry):
        self.hass = hass
        self._entry = entry
        self._fan_coordinator = entry.runtime_data.fan_coordinator
        self._co2_coordinator = entry.runtime_data.co2_coordinator
        self._mqtt_topic = entry.data.get(CONF_MQTT_TOPIC)
        self._gateway_id = entry.data.get(CONF_GATEWAY_ID)
        self._remote_id = entry.data.get(CONF_REMOTE_ID)
        self._fan_id = entry.data.get(CONF_FAN_ID)
        self._co2_id = entry.data.get(CONF_CO2_ID)
        self._co2 = None
        self._ramses_esp = entry.runtime_data.ramses_esp
        self._req_humidity_unsub = None
        self._attr_unique_id = f"orcon_mvs15_{self._fan_id}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, self._fan_id)},
            manufacturer="Orcon",
            model="MVS-15",
            name=f"{self.name} ({self._fan_id})",
            via_device=(DOMAIN, self._gateway_id),
        )

    @property
    def extra_state_attributes(self):
        fan_data = self._fan_coordinator.data
        co2_data = self._co2_coordinator.data
        return {
            "co2": co2_data.get("co2"),
            "vent_demand": co2_data.get("vent_demand"),
            "relative_humidity": fan_data.get("relative_humidity"),
            "fan_fault": fan_data.get("fan_fault"),
        }

    @property
    def preset_mode(self):
        return self._fan_coordinator.data.get("fan_mode")

    async def async_added_to_hass(self):
        if self.hass.state == CoreState.running:
            _LOGGER.info("Orcon MVS-15 integration has been setup")
            self.hass.async_create_task(self.setup())
        else:
            _LOGGER.info("Orcon MVS-15 integration has been loaded after restart")
            self.hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STARTED, self.setup)

    async def async_set_preset_mode(self, preset_mode: str):
        await self._ramses_esp.set_preset_mode(preset_mode)

    async def async_will_remove_from_hass(self):
        if self._req_humidity_unsub:
            self._req_humidity_unsub()
        await self._ramses_esp.remove()

    async def setup(self, event=None):
        self._ramses_esp.add_handler("10E0", self._device_info_handler)
        self._ramses_esp.add_handler("1298", self._co2_handler)
        self._ramses_esp.add_handler("12A0", self._relative_humidity_handler)
        self._ramses_esp.add_handler("31D9", self._fan_state_handler)
        self._ramses_esp.add_handler("31E0", self._vent_demand_handler)
        await self._ramses_esp.setup(event)

    async def _add_co2_sensor(self, payload):
        """Add the CO2 sensor to the config, create the sensors and device, and update the sensors with the current state"""
        new_data = {**self._co2_coordinator.data, "discovered_co2_id": self._co2_id}
        self._co2_coordinator.async_set_updated_data(new_data)
        await asyncio.sleep(1)  # wait for sensors to get created
        await self._ramses_esp.init_co2()

    def _fan_state_handler(self, payload):
        """Update fan mode and fault state"""
        new_data = {
            **self._fan_coordinator.data,
            "fan_mode": payload.values["fan_mode"],
            "fan_fault": payload.values["has_fault"],
            "fan_rssi": payload.values["rssi"],
        }
        self._fan_coordinator.async_set_updated_data(new_data)
        _LOGGER.info(
            f"Current fan mode: {payload.values['fan_mode']}, "
            f"has_fault: {payload.values['has_fault']}, "
            f"RSSI: {payload.values['rssi']} dBm"
        )

    def _co2_handler(self, payload):
        """Update CO2 sensor + attribute"""
        new_data = {
            **self._co2_coordinator.data,
            "co2": payload.values["level"],
            "co2_rssi": payload.values["rssi"],
        }
        self._co2_coordinator.async_set_updated_data(new_data)
        _LOGGER.info(
            f"Current CO2 level: {payload.values['level']} ppm, RSSI: {payload.values['rssi']} dBm"
        )

    def _vent_demand_handler(self, payload):
        """Update Vent demand attribute"""
        if not self._co2_id:
            """Discovered CO2 sensor, setup sensors + device"""
            _LOGGER.debug(
                f"Adding discovered CO2 sensor {payload.packet.src_id} to config"
            )
            self._co2_id = payload.packet.src_id
            new_cfg = {**self._entry.data, CONF_CO2_ID: self._co2_id}
            self.hass.config_entries.async_update_entry(self._entry, data=new_cfg)
        new_data = {
            **self._co2_coordinator.data,
            "vent_demand": payload.values["percentage"],
            "co2_rssi": payload.values["rssi"],
            "discovery_co2_id": self._co2_id,
        }
        self._co2_coordinator.async_set_updated_data(new_data)
        _LOGGER.info(
            f"Vent demand: {payload.values['percentage']}%, "
            f"unknown: {payload.values['unknown']}, "
            f"RSSI: {payload.values['rssi']} dBm"
        )

    def _relative_humidity_handler(self, payload):
        """Update relative humidity attribute"""
        new_data = {
            **self._fan_coordinator.data,
            "relative_humidity": payload.values["level"],
            "fan_rssi": payload.values["rssi"],
        }
        self._fan_coordinator.async_set_updated_data(new_data)
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

    def _device_info_handler(self, payload):
        """Update device info"""
        if payload.values["manufacturer_sub_id"] != "C8":
            _LOGGER.warning("This doesn't look like an Orcon device: {payload.values}")
            return
        if payload.values["product_id"] not in ["26", "51"]:
            _LOGGER.warning(f"Unknown product_id {payload.values['product_id']}")
            return
        dev_reg = get_dev_reg(self.hass)
        entry = dev_reg.async_get_device({(DOMAIN, payload.packet.src_id)})
        dev_info = {
            "device_id": entry.id,
            "sw_version": int(payload.values["software_ver_id"], 16),
            "model_id": payload.values["description"],
        }
        dev_reg.async_update_device(**dev_info)
        _LOGGER.info(
            f"Updated device info: {dev_info}, RSSI: {payload.values['rssi']} dBm"
        )
