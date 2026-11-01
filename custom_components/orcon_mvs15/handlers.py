from __future__ import annotations

import logging

from homeassistant.core import HomeAssistant

from typing import Callable

from .codes import Code
from .device import update_device_info
from .models import OrconMVS15ConfigEntry

_LOGGER = logging.getLogger(__name__)


class HandlerException(Exception):
    pass


class DataHandlers:
    def __init__(self, hass: HomeAssistant, entry: OrconMVS15ConfigEntry) -> None:
        self.hass = hass
        self.config_entry = entry
        self.co2_coordinator = entry.runtime_data.co2_coordinator
        self.fan_coordinator = entry.runtime_data.fan_coordinator
        self.pointers: dict[str, Callable[[Code], None]] = {
            "042F": self._powerup_handler,
            "10E0": self._device_info_handler,
            "1298": self._co2_handler,
            "12A0": self._relative_humidity_handler,
            "31D9": self._fan_state_handler,
            "31E0": self._vent_demand_handler,
        }

    def _powerup_handler(self, payload: Code) -> None:
        """Fan powerup payload, we use it for fan discovery.

        Not every unit fills in ``ann_id``. When it is empty, fall back to the
        sender so a broadcast that only names a source still discovers the fan.
        """
        fan_id = payload.packet.ann_id or payload.packet.src_id
        _LOGGER.info(
            "Fan startup payload received, "
            f"signal strength: {payload.values['signal_strength']} dBm"
        )
        new_data = {
            **self.fan_coordinator.data,
            "discovered_fan_id": fan_id,
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
            _LOGGER.warning(f"This doesn't look like an Orcon device: {payload.values}")
            return
        # 26 and 51 are the MVS-15; 5F is the VMC-15RPS34, which sends the same
        # packets but reports a different product ID.
        if payload.values["product_id"] not in ["26", "51", "5F"]:
            _LOGGER.warning(f"Unknown product_id {payload.values['product_id']}")
            return
        ramses_id = payload.packet.src_id
        software_ver_id = payload.values["software_ver_id"]
        description = payload.values["description"]
        if not isinstance(software_ver_id, str) or not isinstance(description, str):
            _LOGGER.debug("Ignoring incomplete device info: %s", payload.values)
            return
        if update_device_info(
            self.hass,
            self.config_entry.entry_id,
            ramses_id,
            software_ver_id,
            description,
        ):
            _LOGGER.info(
                f"Updated device info for {ramses_id}, "
                f"signal strength: {payload.values['signal_strength']} dBm"
            )
