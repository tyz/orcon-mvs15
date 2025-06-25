from __future__ import annotations

from types import MappingProxyType
from typing import Any

from homeassistant.components.binary_sensor import (
    BinarySensorEntity,
    BinarySensorDeviceClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import callback, HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, CONF_FAN_ID
from .discover_entity import DiscoverEntity
from .coordinator import OrconMVS15DataUpdateCoordinator
from .ramses_esp import RamsesESP


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    fan_sensor = DiscoverEntity(
        hass=hass,
        async_add_entities=async_add_entities,
        config=entry.data,
        coordinator=entry.runtime_data.fan_coordinator,
        ramses_esp=entry.runtime_data.ramses_esp,
        ramses_id=entry.data[CONF_FAN_ID],
        label="fan",
        entities=[FaultBinarySensor],
    )
    entry.runtime_data.cleanup.append(fan_sensor.cleanup)


class FaultBinarySensor(CoordinatorEntity, BinarySensorEntity):
    _attr_device_class = BinarySensorDeviceClass.PROBLEM

    def __init__(
        self,
        hass: HomeAssistant,
        ramses_id: str,
        config: MappingProxyType[str, Any],
        coordinator: OrconMVS15DataUpdateCoordinator,
        ramses_esp: RamsesESP,
        label: str,
    ) -> None:
        super().__init__(coordinator)
        self.label = label
        self._attr_name = f"Orcon MVS-15 {label} fault"
        self._attr_unique_id = f"orcon_mvs15_{label}_fault_{ramses_id}"
        self._attr_device_info = DeviceInfo(identifiers={(DOMAIN, ramses_id)})

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        self._attr_is_on = bool(
            self.coordinator.data.get(f"{self.label.lower()}_fault")
        )
        self.async_write_ha_state()
