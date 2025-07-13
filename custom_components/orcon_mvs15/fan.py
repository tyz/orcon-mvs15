from __future__ import annotations

import logging


from homeassistant.components.fan import FanEntity, FanEntityFeature
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import callback, CoreState, HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .models import OrconMVS15Config
from .ramses_packet import RamsesPacketDatetime, RamsesID
from .ramses_esp import RamsesESP
from .coordinator import OrconMVS15DataUpdateCoordinator
from .discover_entity import DiscoverEntity
from .codes import Code22f1
from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> bool:
    fan = DiscoverEntity(
        hass=hass,
        async_add_entities=async_add_entities,
        config=entry.runtime_data.config,
        coordinator=entry.runtime_data.fan_coordinator,
        ramses_esp=entry.runtime_data.ramses_esp,
        ramses_id=entry.runtime_data.config.fan_id,
        name="Orcon MVS-15 fan",
        discovery_key="fan",
        entities=[OrconFan],
    )
    entry.runtime_data.cleanup.append(fan.cleanup)

    return True


class OrconFan(CoordinatorEntity, FanEntity):
    _attr_preset_modes = Code22f1.presets()
    _attr_supported_features = FanEntityFeature.PRESET_MODE
    _attr_translation_key = "fan_states"  # see icons.json
    _attr_preset_mode = "Auto"

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
        self.hass = hass
        self.fan_id = ramses_id
        self.ramses_esp = ramses_esp
        self.discovery_key = discovery_key
        self.gateway_id = config.gateway_id
        self._attr_name = name
        self._attr_unique_id = f"orcon_mvs15_{self.fan_id}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, self.fan_id)},
            manufacturer="Orcon",
            model="MVS-15",
            name=f"{self.name} ({self.fan_id})",
            via_device=(DOMAIN, self.gateway_id),
        )
        self._attr_extra_state_attributes: dict[
            str, str | int | bool | RamsesPacketDatetime | None
        ] = {
            "fan_fault": None,
        }

    async def async_set_preset_mode(self, preset_mode: str) -> None:
        await self.ramses_esp.set_preset_mode(preset_mode)

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        if self.hass.state == CoreState.running:
            await self.ramses_esp.init_fan(discovered_fan_id=self.fan_id)

    @callback
    def _handle_coordinator_update(self) -> None:
        """handle updated data from the coordinator."""
        if "fan_mode" in self.coordinator.data:
            self._attr_preset_mode = self.coordinator.data["fan_mode"]
        if "fan_fault" in self.coordinator.data:
            self._attr_extra_state_attributes["fan_fault"] = self.coordinator.data[
                "fan_fault"
            ]
        if "fan_mode" in self.coordinator.data or "fan_fault" in self.coordinator.data:
            self.async_write_ha_state()
