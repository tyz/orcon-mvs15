from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorEntity,
    BinarySensorDeviceClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, CONF_FAN_ID
from .orcon_sensor import OrconSensor
from .coordinator import OrconMVS15DataUpdateCoordinator


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    fan_sensor = OrconSensor(
        hass=hass,
        async_add_entities=async_add_entities,
        config=entry.data,
        coordinator=entry.runtime_data.fan_coordinator,
        ramses_id=entry.data[CONF_FAN_ID],
        label="fan",
        entities=[FaultBinarySensor],
    )
    entry.runtime_data.cleanup.append(fan_sensor.cleanup)


class FaultBinarySensor(CoordinatorEntity, BinarySensorEntity):
    _attr_device_class = BinarySensorDeviceClass.PROBLEM

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
        self._attr_name = f"Orcon MVS-15 {label} fault"
        self._attr_unique_id = f"orcon_mvs15_{label}_fault_{ramses_id}"
        self._attr_device_info = DeviceInfo(identifiers={(DOMAIN, ramses_id)})

    @property
    def is_on(self) -> bool | None:
        return bool(self.coordinator.data.get(f"{self.label.lower()}_fault"))
