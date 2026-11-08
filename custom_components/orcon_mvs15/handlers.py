from __future__ import annotations

import logging
import math

from collections.abc import Callable
from datetime import datetime, timedelta

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.event import async_call_later, async_track_time_interval
from homeassistant.util import dt as dt_util

from .coordinator import OrconMVS15DataUpdateCoordinator
from .ramses.protocol import Code
from .device import update_device_info

_LOGGER = logging.getLogger(__name__)

FAN_TIMER_UPDATE_INTERVAL = timedelta(minutes=1)


class HandlerException(Exception):
    pass


class DataHandlers:
    def __init__(
        self,
        hass: HomeAssistant,
        fan_coordinator: OrconMVS15DataUpdateCoordinator,
        co2_coordinator: OrconMVS15DataUpdateCoordinator,
        *,
        entry_id: str,
    ) -> None:
        self.hass = hass
        self.entry_id = entry_id
        self.co2_coordinator = co2_coordinator
        self.fan_coordinator = fan_coordinator
        self._fan_timer_end: datetime | None = None
        self._fan_timer_unsub: Callable[[], None] | None = None
        self._fan_timer_tick_unsub: Callable[[], None] | None = None
        self.pointers: dict[str, Callable[[Code], None]] = {
            "10E0": self._device_info_handler,
            "1298": self._co2_handler,
            "12A0": self._relative_humidity_handler,
            "22F1": self._fan_command_handler,
            "22F3": self._fan_command_handler,
            "31D9": self._fan_state_handler,
            "31E0": self._vent_demand_handler,
        }

    def _fan_command_handler(self, payload: Code) -> None:
        """Start or clear the countdown for a fan command."""
        if payload.packet.length == 1:
            return  # A request carries no mode and must not touch the timer.
        minutes = payload.values.get("timer_minutes")
        self._set_fan_timer(minutes if isinstance(minutes, int) else None)

    def _set_fan_timer(self, minutes: int | None) -> None:
        """Replace the running countdown with one for minutes, or clear it."""
        self._cancel_fan_timer()
        if minutes is None:
            self._fan_timer_end = None
            self._publish_fan_timer(None, None)
            return
        self._fan_timer_end = dt_util.utcnow() + timedelta(minutes=minutes)
        self._fan_timer_unsub = async_call_later(
            self.hass, timedelta(minutes=minutes), self._fan_timer_expired
        )
        self._fan_timer_tick_unsub = async_track_time_interval(
            self.hass, self._fan_timer_tick, FAN_TIMER_UPDATE_INTERVAL
        )
        self._publish_fan_timer(self._fan_timer_end, minutes)

    def _cancel_fan_timer(self) -> None:
        if self._fan_timer_unsub is not None:
            self._fan_timer_unsub()
            self._fan_timer_unsub = None
        if self._fan_timer_tick_unsub is not None:
            self._fan_timer_tick_unsub()
            self._fan_timer_tick_unsub = None

    def cleanup(self) -> None:
        """Stop the countdown when the entry unloads."""
        self._cancel_fan_timer()
        self._fan_timer_end = None

    @callback
    def _fan_timer_tick(self, now: datetime) -> None:
        """Publish the remaining whole minutes while the timer runs."""
        if self._fan_timer_end is None:
            return
        remaining = max(0, math.ceil((self._fan_timer_end - now).total_seconds() / 60))
        if self.fan_coordinator.data.get("fan_timer_remaining") != remaining:
            self._publish_fan_timer(self._fan_timer_end, remaining)

    @callback
    def _fan_timer_expired(self, _now: datetime) -> None:
        self._cancel_fan_timer()
        self._fan_timer_end = None
        self._publish_fan_timer(None, None)

    def _publish_fan_timer(self, end: datetime | None, remaining: int | None) -> None:
        self.fan_coordinator.async_set_updated_data(
            {
                **self.fan_coordinator.data,
                "fan_timer_end": end.isoformat() if end is not None else None,
                "fan_timer_remaining": remaining,
            }
        )

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
        if payload.packet.length == 1:
            return  # A request carries no level; keep the last measurement.
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
        if payload.packet.length == 1:
            return  # A request carries no device info fields.
        if payload.values["manufacturer_sub_id"] != "C8":
            _LOGGER.warning(f"This doesn't look like an Orcon device: {payload.values}")
            return
        # 26 is the fan (VMC-15RP01), 51 the wired CO₂ room sensor
        # (VMS-15CM17) and 5F the newer fan (VMC-15RPS34). MVx-15 is the sold
        # name, VMx-15 the internal Orcon name. Product 27 belongs to another
        # Orcon system and is not a fan.
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
            self.entry_id,
            ramses_id,
            software_ver_id,
            description,
        ):
            _LOGGER.info(
                f"Updated device info for {ramses_id}, "
                f"signal strength: {payload.values['signal_strength']} dBm"
            )
