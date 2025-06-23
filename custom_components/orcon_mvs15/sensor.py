from __future__ import annotations

from collections.abc import Callable
from types import MappingProxyType
from typing import Any

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
from homeassistant.core import callback, HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, CONF_FAN_ID, CONF_GATEWAY_ID, CONF_CO2_ID
from .coordinator import OrconMVS15DataUpdateCoordinator
from .orcon_sensor import OrconSensor


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: Callable
) -> None:
    fan_sensor = OrconSensor(
        hass=hass,
        async_add_entities=async_add_entities,
        config=entry.data,
        coordinator=entry.runtime_data.fan_coordinator,
        ramses_id=entry.data[CONF_FAN_ID],
        label="fan",
        entities=[HumiditySensor, SignalStrengthSensor],
    )
    entry.runtime_data.cleanup.append(fan_sensor.cleanup)

    co2_sensor = OrconSensor(
        hass=hass,
        async_add_entities=async_add_entities,
        config=entry.data,
        coordinator=entry.runtime_data.co2_coordinator,
        ramses_id=entry.data.get(CONF_CO2_ID),
        label="CO2",
        entities=[Co2Sensor, SignalStrengthSensor],
    )
    entry.runtime_data.cleanup.append(co2_sensor.cleanup)


class Co2Sensor(CoordinatorEntity, SensorEntity):
    _attr_name = "Orcon MVS-15 CO2"
    _attr_native_unit_of_measurement = CONCENTRATION_PARTS_PER_MILLION
    _attr_device_class = SensorDeviceClass.CO2
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(
        self,
        co2_id: str,
        config: MappingProxyType[str, Any],
        coordinator: OrconMVS15DataUpdateCoordinator,
        label: str,
    ) -> None:
        super().__init__(coordinator)
        self.coordinator = coordinator
        gateway_id = config[CONF_GATEWAY_ID]
        self._state = None
        self._attr_unique_id = f"orcon_mvs15_co2_{co2_id}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, co2_id)},
            manufacturer="Orcon",
            model="MVS-15RH CO2B",
            name=f"Orcon CO2 remote 15RF ({co2_id})",
            via_device=(DOMAIN, gateway_id),
        )

    @callback
    def _handle_coordinator_update(self) -> None:
        """handle updated data from the coordinator."""
        key = "co2"
        if self.coordinator.data and key in self.coordinator.data:
            self._attr_native_value = int(self.coordinator.data[key])
            self.async_write_ha_state()


class HumiditySensor(CoordinatorEntity, SensorEntity):
    _attr_name = "Orcon MVS-15 Relative Humidity"
    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_device_class = SensorDeviceClass.HUMIDITY
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(
        self,
        fan_id: str,
        config: MappingProxyType[str, Any],
        coordinator: OrconMVS15DataUpdateCoordinator,
        label: str,
    ) -> None:
        super().__init__(coordinator)
        self.coordinator = coordinator
        self._attr_unique_id = f"orcon_mvs15_humidity_{fan_id}"
        self._attr_device_info = DeviceInfo(identifiers={(DOMAIN, fan_id)})

    @callback
    def _handle_coordinator_update(self) -> None:
        """handle updated data from the coordinator."""
        key = "relative_humidity"
        if self.coordinator.data and key in self.coordinator.data:
            self._attr_native_value = int(self.coordinator.data[key])
            self.async_write_ha_state()


class SignalStrengthSensor(CoordinatorEntity, SensorEntity):
    _attr_native_unit_of_measurement = SIGNAL_STRENGTH_DECIBELS_MILLIWATT
    _attr_device_class = SensorDeviceClass.SIGNAL_STRENGTH
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(
        self,
        ramses_id: str,
        config: ConfigEntry,
        coordinator: OrconMVS15DataUpdateCoordinator,
        label: str,
    ) -> None:
        super().__init__(coordinator)
        self.coordinator = coordinator
        self.label = label
        self._attr_name = f"Orcon MVS-15 {label} signal strength"
        self._attr_unique_id = f"orcon_mvs15_dbm_{ramses_id}"
        self._attr_device_info = DeviceInfo(identifiers={(DOMAIN, ramses_id)})

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        key = f"{self.label.lower()}_signal_strength"
        if self.coordinator.data and key in self.coordinator.data:
            self._attr_native_value = int(self.coordinator.data[key])
            self.async_write_ha_state()
