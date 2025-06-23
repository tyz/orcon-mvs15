from __future__ import annotations

import logging

from datetime import timedelta

from homeassistant.components.fan import FanEntity, FanEntityFeature
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EVENT_HOMEASSISTANT_STARTED
from homeassistant.core import CoreState, Event, HomeAssistant
from homeassistant.helpers.device_registry import async_get as get_dev_reg
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.event import async_track_time_interval

from .ramses_packet import RamsesPacketDatetime
from .codes import Code, Code22f1
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
# * Create devices in __init__._setup_coordinator, sensors and such only set identifiers
# * Auto discovery
#   - Discover fan_id: turn off/on the fan unit, fan_id == src_id of 1st 042F packet
#   - Bind as remote with random remote_id (1FC9)
#   - or: Discover existing remote by 22F1/22F3 packets to use that remote_id
#   - [DONE] Discover CO2: remote_id is a type I, code 31E0 to fan_id
#   - Discover humidity: create sensor only after first successful pull
# * Add logo to https://brands.home-assistant.io/
# * Req 10e0, 31e0 and 1298 after CO2 sensors have been created

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> bool:
    async_add_entities([OrconFan(hass, entry)])
    return True


class OrconFan(FanEntity):
    _attr_preset_modes = Code22f1.presets()
    _attr_supported_features = FanEntityFeature.PRESET_MODE
    _attr_translation_key = "fan_states"  # see icons.json
    _attr_name = "Orcon MVS-15 fan"
    _attr_preset_mode = "Auto"

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.hass = hass
        self._entry = entry
        self._fan_coordinator = entry.runtime_data.fan_coordinator
        self._co2_coordinator = entry.runtime_data.co2_coordinator
        self._mqtt_topic = entry.data[CONF_MQTT_TOPIC]
        self._gateway_id = entry.data[CONF_GATEWAY_ID]
        self._remote_id = entry.data[CONF_REMOTE_ID]
        self._fan_id = entry.data[CONF_FAN_ID]
        self._co2_id = entry.data.get(CONF_CO2_ID)
        self._co2 = None
        self._ramses_esp = entry.runtime_data.ramses_esp
        self._req_humidity_unsub = None
        entry.runtime_data.cleanup.append(self.cleanup)
        self._attr_unique_id = f"orcon_mvs15_{self._fan_id}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, self._fan_id)},
            manufacturer="Orcon",
            model="MVS-15",
            name=f"{self.name} ({self._fan_id})",
            via_device=(DOMAIN, self._gateway_id),
        )
        self._attr_extra_state_attributes: dict[
            str, str | int | bool | RamsesPacketDatetime | None
        ] = {
            "co2": None,
            "vent_demand": None,
            "relative_humidity": None,
            "fan_fault": None,
        }

    async def async_added_to_hass(self) -> None:
        if self.hass.state == CoreState.running:
            _LOGGER.info("Orcon MVS-15 integration has been setup")
            self.hass.async_create_task(self.setup())
        else:
            _LOGGER.info("Orcon MVS-15 integration has been loaded after restart")
            self.hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STARTED, self.setup)

    async def async_set_preset_mode(self, preset_mode: str) -> None:
        await self._ramses_esp.set_preset_mode(preset_mode)

    def cleanup(self) -> None:
        if hasattr(self, "_req_humidity_unsub") and self._req_humidity_unsub:
            self._req_humidity_unsub()
            self._req_humidity_unsub = None
            _LOGGER.debug("Removing the interval call for the humidity sensor")

    async def setup(self, event: Event | None = None) -> None:
        self._ramses_esp.add_handler("10E0", self._device_info_handler)
        self._ramses_esp.add_handler("1298", self._co2_handler)
        self._ramses_esp.add_handler("12A0", self._relative_humidity_handler)
        self._ramses_esp.add_handler("31D9", self._fan_state_handler)
        self._ramses_esp.add_handler("31E0", self._vent_demand_handler)
        await self._ramses_esp.setup(event)

    def _fan_state_handler(self, payload: Code) -> None:
        """Update fan mode and fault state"""
        self._attr_preset_mode = str(payload.values["fan_mode"])
        self.async_write_ha_state()
        self._attr_extra_state_attributes["fan_fault"] = bool(
            payload.values["has_fault"]
        )
        self.async_write_ha_state()
        new_data = {
            **self._fan_coordinator.data,
            "fan_mode": payload.values["fan_mode"],
            "fan_fault": payload.values["has_fault"],
            "fan_signal_strength": payload.values["signal_strength"],
        }
        self._fan_coordinator.async_set_updated_data(new_data)
        _LOGGER.info(
            f"Current fan mode: {payload.values['fan_mode']}, "
            f"has_fault: {payload.values['has_fault']}, "
            f"Signal strength: {payload.values['signal_strength']} dBm"
        )

    def _co2_handler(self, payload: Code) -> None:
        """Update CO2 sensor + attribute"""
        self._attr_extra_state_attributes["co2"] = payload.values["level"]
        self.async_write_ha_state()
        new_data = {
            **self._co2_coordinator.data,
            "co2": payload.values["level"],
            "co2_signal_strength": payload.values["signal_strength"],
        }
        self._co2_coordinator.async_set_updated_data(new_data)
        _LOGGER.info(
            f"Current CO2 level: {payload.values['level']} ppm, Signal strength: {payload.values['signal_strength']} dBm"
        )

    def _vent_demand_handler(self, payload: Code) -> None:
        """Update Vent demand attribute"""
        if not self._co2_id:  # discovered CO2 sensor
            self._co2_id = payload.packet.src_id
        self._attr_extra_state_attributes["vent_demand"] = payload.values["percentage"]
        self.async_write_ha_state()
        new_data = {
            **self._co2_coordinator.data,
            "vent_demand": payload.values["percentage"],
            "co2_signal_strength": payload.values["signal_strength"],
            "discovered_co2_id": self._co2_id,
        }
        self._co2_coordinator.async_set_updated_data(new_data)
        _LOGGER.info(
            f"Vent demand: {payload.values['percentage']}%, "
            f"unknown: {payload.values['unknown']}, "
            f"Signal strength: {payload.values['signal_strength']} dBm"
        )

    def _relative_humidity_handler(self, payload: Code) -> None:
        """Update relative humidity attribute"""
        self._attr_extra_state_attributes["relative_humidity"] = payload.values["level"]
        self.async_write_ha_state()
        new_data = {
            **self._fan_coordinator.data,
            "relative_humidity": payload.values["level"],
            "fan_signal_strength": payload.values["signal_strength"],
        }
        self._fan_coordinator.async_set_updated_data(new_data)
        _LOGGER.info(
            f"Current humidity level: {payload.values['level']}%, Signal strength: {payload.values['signal_strength']} dBm"
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

    def _device_info_handler(self, payload: Code) -> None:
        """Update device info"""
        if payload.values["manufacturer_sub_id"] != "C8":
            _LOGGER.warning("This doesn't look like an Orcon device: {payload.values}")
            return
        if payload.values["product_id"] not in ["26", "51"]:
            _LOGGER.warning(f"Unknown product_id {payload.values['product_id']}")
            return
        dev_reg = get_dev_reg(self.hass)
        if (
            entry := dev_reg.async_get_device({(DOMAIN, payload.packet.src_id)})
        ) is None:
            return
        dev_info = {
            "device_id": entry.id,
            "sw_version": int(str(payload.values["software_ver_id"]), 16),
            "model_id": payload.values["description"],
        }
        dev_reg.async_update_device(**dev_info)
        _LOGGER.info(
            f"Updated device info: {dev_info}, Signal strength: {payload.values['signal_strength']} dBm"
        )
