from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import async_get as get_dev_reg
from homeassistant.helpers.event import async_track_time_interval

from datetime import timedelta
from typing import Callable

from .codes import Code
from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)


class HandlerException(Exception):
    pass


class DataHandlers:
    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.hass = hass
        self.co2_coordinator = entry.runtime_data.co2_coordinator
        self.fan_coordinator = entry.runtime_data.fan_coordinator
        self.ramses_esp = entry.runtime_data.ramses_esp
        self._req_humidity_unsub: Callable | None = None
        self._cleanup = entry.runtime_data.cleanup
        self.pointers: dict[str, Callable[[Code], None]] = {
            "042F": self._powerup_handler,
            "10E0": self._device_info_handler,
            "1298": self._co2_handler,
            "12A0": self._relative_humidity_handler,
            "31D9": self._fan_state_handler,
            "31E0": self._vent_demand_handler,
        }

    def cleanup(self) -> None:
        if hasattr(self, "_req_humidity_unsub") and self._req_humidity_unsub:
            self._req_humidity_unsub()
            self._req_humidity_unsub = None
            _LOGGER.debug("Removed the interval call for the humidity sensor")

    def _powerup_handler(self, payload: Code) -> None:
        """Fan powerup payload, we use it for fan discovery"""
        _LOGGER.info(
            "Fan startup payload received, "
            f"signal strength: {payload.values['signal_strength']} dBm"
        )
        new_data = {
            **self.fan_coordinator.data,
            "discovered_fan_id": payload.packet.ann_id,
            "fan_signal_strength": payload.values["signal_strength"],
        }
        self.fan_coordinator.async_set_updated_data(new_data)

    def _fan_state_handler(self, payload: Code) -> None:
        """Update fan mode and fault state"""
        _LOGGER.info(
            f"Current fan mode: {payload.values['fan_mode']}, "
            f"has_fault: {payload.values['has_fault']}, "
            f"signal strength: {payload.values['signal_strength']} dBm"
        )
        new_data = {
            **self.fan_coordinator.data,
            "fan_mode": payload.values["fan_mode"],
            "fan_fault": payload.values["has_fault"],
            "fan_signal_strength": payload.values["signal_strength"],
            "discovered_fan_id": payload.packet.src_id,
        }
        self.fan_coordinator.async_set_updated_data(new_data)

    def _relative_humidity_handler(self, payload: Code) -> None:
        """Update relative humidity attribute"""
        _LOGGER.info(
            f"Current humidity level: {payload.values['level']}%, "
            f"signal strength: {payload.values['signal_strength']} dBm"
        )
        new_data = {
            **self.fan_coordinator.data,
            "relative_humidity": payload.values["level"],
            "fan_signal_strength": payload.values["signal_strength"],
            "discovered_humidity_id": payload.packet.src_id,
            "discovered_fan_id": payload.packet.src_id,
        }
        self.fan_coordinator.async_set_updated_data(new_data)
        if not self._req_humidity_unsub:
            poll_interval = 5
            self._req_humidity_unsub = async_track_time_interval(
                self.hass,
                self.ramses_esp.req_humidity,
                timedelta(minutes=poll_interval),
            )
            self._cleanup.append(self.cleanup)
            _LOGGER.info(
                f"Humidity sensor detected, fetching value every {poll_interval} minutes"
            )

    def _co2_handler(self, payload: Code) -> None:
        """Update CO2 sensor + attribute"""
        _LOGGER.info(
            f"Current CO2 level: {payload.values['level']} ppm, "
            f"signal strength: {payload.values['signal_strength']} dBm"
        )
        new_data = {
            **self.co2_coordinator.data,
            "co2": payload.values["level"],
            "co2_signal_strength": payload.values["signal_strength"],
        }
        self.co2_coordinator.async_set_updated_data(new_data)

    def _vent_demand_handler(self, payload: Code) -> None:
        """Update Vent demand attribute"""
        _LOGGER.info(
            f"Vent demand: {payload.values['percentage']}%, "
            f"unknown: {payload.values['unknown']}, "
            f"signal strength: {payload.values['signal_strength']} dBm"
        )
        new_data = {
            **self.co2_coordinator.data,
            "vent_demand": payload.values["percentage"],
            "co2_signal_strength": payload.values["signal_strength"],
            "discovered_co2_id": payload.packet.src_id,
        }
        self.co2_coordinator.async_set_updated_data(new_data)

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
        _LOGGER.info(
            f"Updating device info: {dev_info}, "
            f"signal strength: {payload.values['signal_strength']} dBm"
        )
        dev_reg.async_update_device(**dev_info)
