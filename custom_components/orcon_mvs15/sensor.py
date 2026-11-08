from __future__ import annotations

import logging

from homeassistant.components.sensor import (
    SensorEntity,
    SensorDeviceClass,
    SensorStateClass,
)
from homeassistant.const import (
    EntityCategory,
    UnitOfRatio,
    PERCENTAGE,
    SIGNAL_STRENGTH_DECIBELS_MILLIWATT,
)
from homeassistant.core import callback, HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .controller import OrconMVS15Controller
from .coordinator import OrconMVS15DataUpdateCoordinator
from .device import attached_device_info
from .models import OrconMVS15Config, OrconMVS15ConfigEntry
from .discover_entity import DiscoverEntity
from .ramses.protocol import RamsesPacketDatetime, RamsesID

_LOGGER = logging.getLogger(__name__)

# Sensors only read pushed data, so there is nothing to serialise.
PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: OrconMVS15ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    fanss_sensor = DiscoverEntity(
        hass=hass,
        async_add_entities=async_add_entities,
        config=entry.runtime_data.config,
        coordinator=entry.runtime_data.fan_coordinator,
        controller=entry.runtime_data.controller,
        discovery=entry.runtime_data.discovery,
        device_kind="fan",
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
        controller=entry.runtime_data.controller,
        discovery=entry.runtime_data.discovery,
        device_kind="fan",
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
        controller=entry.runtime_data.controller,
        discovery=entry.runtime_data.discovery,
        device_kind="co2",
        name="Orcon MVS-15 CO2",
        discovery_key="co2",
        entities=[Co2Sensor, SignalStrengthSensor],
    )
    entry.runtime_data.cleanup.append(co2_sensor.cleanup)


class Co2Sensor(CoordinatorEntity, SensorEntity):
    _attr_has_entity_name = True
    _attr_translation_key = "co2"
    _attr_native_unit_of_measurement = UnitOfRatio.PARTS_PER_MILLION
    _attr_device_class = SensorDeviceClass.CO2
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(
        self,
        hass: HomeAssistant,
        ramses_id: RamsesID,
        config: OrconMVS15Config,
        coordinator: OrconMVS15DataUpdateCoordinator,
        controller: OrconMVS15Controller,
        discovery_key: str,
    ) -> None:
        super().__init__(coordinator)
        self.co2_id = ramses_id
        self.discovery_key = discovery_key
        self._state = None
        self._attr_unique_id = f"orcon_mvs15_co2_{self.co2_id}"
        self._attr_device_info = attached_device_info(self.co2_id)
        self._attr_extra_state_attributes: dict[
            str, str | int | bool | RamsesPacketDatetime | None
        ] = {
            "vent_demand": None,
        }

    @property
    def available(self) -> bool:
        """The sensor has no state until 1298 has been received."""
        return super().available and "co2" in self.coordinator.data

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        data = self.coordinator.data
        if "co2" in data:
            co2 = data["co2"]
            self._attr_native_value = None if co2 is None else int(co2)
        if "vent_demand" in data:
            # 31E0 encodes "no demand" as FE/FF, which decodes to None.
            vent_demand = data["vent_demand"]
            self._attr_extra_state_attributes["vent_demand"] = (
                None if vent_demand is None else int(vent_demand)
            )
        if "co2" in data or "vent_demand" in data:
            self.async_write_ha_state()


class HumiditySensor(CoordinatorEntity, SensorEntity):
    _attr_has_entity_name = True
    _attr_translation_key = "humidity"
    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_device_class = SensorDeviceClass.HUMIDITY
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(
        self,
        hass: HomeAssistant,
        ramses_id: RamsesID,
        config: OrconMVS15Config,
        coordinator: OrconMVS15DataUpdateCoordinator,
        controller: OrconMVS15Controller,
        discovery_key: str,
    ) -> None:
        super().__init__(coordinator)
        self.discovery_key = discovery_key
        self._attr_unique_id = f"orcon_mvs15_humidity_{ramses_id}"
        self._attr_device_info = attached_device_info(ramses_id)

    @property
    def available(self) -> bool:
        """The sensor has no state until 12A0 has been received."""
        return (
            super().available
            and self.coordinator.data.get("relative_humidity") is not None
        )

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        key = "relative_humidity"
        if key in self.coordinator.data:
            value = self.coordinator.data[key]
            self._attr_native_value = None if value is None else int(value)
            self.async_write_ha_state()


class SignalStrengthSensor(CoordinatorEntity, SensorEntity):
    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_entity_registry_enabled_default = False
    _attr_translation_key = "signal_strength"
    _attr_native_unit_of_measurement = SIGNAL_STRENGTH_DECIBELS_MILLIWATT
    _attr_device_class = SensorDeviceClass.SIGNAL_STRENGTH
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(
        self,
        hass: HomeAssistant,
        ramses_id: RamsesID,
        config: OrconMVS15Config,
        coordinator: OrconMVS15DataUpdateCoordinator,
        controller: OrconMVS15Controller,
        discovery_key: str,
    ) -> None:
        super().__init__(coordinator)
        self.discovery_key = discovery_key
        self._attr_unique_id = f"orcon_mvs15_{discovery_key}_dbm_{ramses_id}"
        self._attr_device_info = attached_device_info(ramses_id)

    @property
    def available(self) -> bool:
        """The sensor has no state until a packet carried a signal strength."""
        key = f"{self.discovery_key}_signal_strength"
        return super().available and key in self.coordinator.data

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        key = f"{self.discovery_key}_signal_strength"
        if key in self.coordinator.data:
            self._attr_native_value = int(self.coordinator.data[key])
            self.async_write_ha_state()
