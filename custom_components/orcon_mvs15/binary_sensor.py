from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorEntity,
    BinarySensorDeviceClass,
)
from homeassistant.core import callback, HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .device import attached_device_info
from .discover_entity import DiscoverEntity
from .coordinator import OrconMVS15DataUpdateCoordinator
from .models import OrconMVS15Config, OrconMVS15ConfigEntry
from .ramses_esp import RamsesESP
from .ramses_packet import RamsesID


async def async_setup_entry(
    hass: HomeAssistant,
    entry: OrconMVS15ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    fan_sensor = DiscoverEntity(
        hass=hass,
        async_add_entities=async_add_entities,
        config=entry.runtime_data.config,
        coordinator=entry.runtime_data.fan_coordinator,
        ramses_esp=entry.runtime_data.ramses_esp,
        ramses_id=entry.runtime_data.config.fan_id,
        name="Orcon MVS-15 fan",
        discovery_key="fan",
        entities=[FaultBinarySensor],
    )
    entry.runtime_data.cleanup.append(fan_sensor.cleanup)


class FaultBinarySensor(CoordinatorEntity, BinarySensorEntity):
    _attr_has_entity_name = True
    _attr_translation_key = "fault"
    _attr_device_class = BinarySensorDeviceClass.PROBLEM

    def __init__(
        self,
        hass: HomeAssistant,
        ramses_id: RamsesID,
        config: OrconMVS15Config,
        coordinator: OrconMVS15DataUpdateCoordinator,
        ramses_esp: RamsesESP,
        discovery_key: str,
    ) -> None:
        super().__init__(coordinator)
        self.discovery_key = discovery_key
        self._attr_unique_id = f"orcon_mvs15_{self.discovery_key}_fault_{ramses_id}"
        self._attr_device_info = attached_device_info(ramses_id)

    @property
    def available(self) -> bool:
        """The sensor has no state until 31D9 has been received."""
        key = f"{self.discovery_key}_fault"
        return super().available and key in self.coordinator.data

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        key = f"{self.discovery_key}_fault"
        self._attr_is_on = bool(self.coordinator.data.get(key))
        self.async_write_ha_state()
