from __future__ import annotations

import logging

from collections.abc import Callable

from homeassistant.components.sensor import (
    SensorEntity,
    SensorDeviceClass,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    CONCENTRATION_PARTS_PER_MILLION,
    PERCENTAGE,
    SIGNAL_STRENGTH_DECIBELS_MILLIWATT,
)
from homeassistant.core import callback, CoreState, HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .models import OrconMVS15Config
from .coordinator import OrconMVS15DataUpdateCoordinator
from .discover_entity import DiscoverEntity
from .ramses_packet import RamsesPacketDatetime, RamsesID
from .ramses_esp import RamsesESP

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: Callable
) -> None:
    fanss_sensor = DiscoverEntity(
        hass=hass,
        async_add_entities=async_add_entities,
        config=entry.runtime_data.config,
        coordinator=entry.runtime_data.fan_coordinator,
        ramses_esp=entry.runtime_data.ramses_esp,
        ramses_id=entry.runtime_data.config.fan_id,
        name="Orcon MVS-15 fan",
        discovery_key="fan",
        entities=[SignalStrengthSensor],
    )
    entry.runtime_data.cleanup.append(fanss_sensor.cleanup)

    hum_sensor = DiscoverEntity(
        hass=hass,
        async_add_entities=async_add_entities,
        config=entry.runtime_data.config,
        coordinator=entry.runtime_data.fan_coordinator,
        ramses_esp=entry.runtime_data.ramses_esp,
        ramses_id=entry.runtime_data.config.fan_id,
        name="Orcon MVS-15 fan",
        discovery_key="humidity",
        entities=[HumiditySensor],
    )
    entry.runtime_data.cleanup.append(hum_sensor.cleanup)

    co2_sensor = DiscoverEntity(
        hass=hass,
        async_add_entities=async_add_entities,
        config=entry.runtime_data.config,
        coordinator=entry.runtime_data.co2_coordinator,
        ramses_esp=entry.runtime_data.ramses_esp,
        ramses_id=entry.runtime_data.config.co2_id,
        name="Orcon MVS-15 CO2",
        discovery_key="co2",
        entities=[Co2Sensor, SignalStrengthSensor],
    )
    entry.runtime_data.cleanup.append(co2_sensor.cleanup)


class Co2Sensor(CoordinatorEntity, SensorEntity):
    _attr_native_unit_of_measurement = CONCENTRATION_PARTS_PER_MILLION
    _attr_device_class = SensorDeviceClass.CO2
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(
        self,
        hass: HomeAssistant,
        ramses_id: RamsesID,
        config: OrconMVS15Config,
        coordinator: OrconMVS15DataUpdateCoordinator,
        ramses_esp: RamsesESP,
        name: str,
        discovery_key: str,
    ) -> None:
        super().__init__(coordinator)
        self.co2_id = ramses_id
        self.ramses_esp = ramses_esp
        self.discovery_key = discovery_key
        self._state = None
        self._attr_name = name
        self._attr_unique_id = f"orcon_mvs15_co2_{self.co2_id}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, self.co2_id)},
            manufacturer="Orcon",
            model="MVS-15RH CO2B",
            name=f"Orcon CO2 remote 15RF ({self.co2_id})",
            via_device=(DOMAIN, config.gateway_id),
        )
        self._attr_extra_state_attributes: dict[
            str, str | int | bool | RamsesPacketDatetime | None
        ] = {
            "vent_demand": None,
        }

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        if (
            self.hass.state == CoreState.running
        ):  # only when HA is already running (ie after discovery)
            await self.ramses_esp.init_co2(discovered_co2_id=self.co2_id)

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        if "co2" in self.coordinator.data:
            self._attr_native_value = int(self.coordinator.data["co2"])
        if "vent_demand" in self.coordinator.data:
            self._attr_extra_state_attributes["vent_demand"] = int(
                self.coordinator.data["vent_demand"]
            )
        if "co2" in self.coordinator.data or "vent_demand" in self.coordinator.data:
            self.async_write_ha_state()


class HumiditySensor(CoordinatorEntity, SensorEntity):
    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_device_class = SensorDeviceClass.HUMIDITY
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(
        self,
        hass: HomeAssistant,
        ramses_id: RamsesID,
        config: ConfigEntry,
        coordinator: OrconMVS15DataUpdateCoordinator,
        ramses_esp: RamsesESP,
        name: str,
        discovery_key: str,
    ) -> None:
        super().__init__(coordinator)
        self.discovery_key = discovery_key
        self._attr_name = f"{name} relative humidity"
        self._attr_unique_id = f"orcon_mvs15_humidity_{ramses_id}"
        self._attr_device_info = DeviceInfo(identifiers={(DOMAIN, ramses_id)})

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        key = "relative_humidity"
        if key in self.coordinator.data:
            self._attr_native_value = int(self.coordinator.data[key])
            self.async_write_ha_state()


class SignalStrengthSensor(CoordinatorEntity, SensorEntity):
    _attr_native_unit_of_measurement = SIGNAL_STRENGTH_DECIBELS_MILLIWATT
    _attr_device_class = SensorDeviceClass.SIGNAL_STRENGTH
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(
        self,
        hass: HomeAssistant,
        ramses_id: str,
        config: ConfigEntry,
        coordinator: OrconMVS15DataUpdateCoordinator,
        ramses_esp: RamsesESP,
        name: str,
        discovery_key: str,
    ) -> None:
        super().__init__(coordinator)
        self.discovery_key = discovery_key
        self._attr_name = f"{name} signal strength"
        self._attr_unique_id = f"orcon_mvs15_{discovery_key}_dbm_{ramses_id}"
        self._attr_device_info = DeviceInfo(identifiers={(DOMAIN, ramses_id)})

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        key = f"{self.discovery_key}_signal_strength"
        if key in self.coordinator.data:
            self._attr_native_value = int(self.coordinator.data[key])
            self.async_write_ha_state()
