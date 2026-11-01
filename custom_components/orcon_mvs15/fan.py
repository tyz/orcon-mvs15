from __future__ import annotations

import logging


from homeassistant.components.fan import FanEntity
from homeassistant.components.fan.const import FanEntityFeature
from homeassistant.core import callback, CoreState, HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .device import attached_device_info
from .models import OrconMVS15Config, OrconMVS15ConfigEntry
from .ramses_packet import RamsesPacketDatetime, RamsesID
from .ramses_esp import RamsesESP
from .coordinator import OrconMVS15DataUpdateCoordinator
from .discover_entity import DiscoverEntity
from .codes import Code22f1

_LOGGER = logging.getLogger(__name__)

# Fan commands are queued by the session, so entity calls do not collide.
PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: OrconMVS15ConfigEntry,
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
    _attr_has_entity_name = True
    _attr_preset_modes = Code22f1.presets()
    _attr_supported_features = FanEntityFeature.PRESET_MODE
    _attr_translation_key = "fan_states"  # see icons.json
    _attr_preset_mode = "auto"

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
        self.hass = hass
        self.fan_id = ramses_id
        self.ramses_esp = ramses_esp
        self.discovery_key = discovery_key
        self.gateway_id = config.gateway_id
        self._attr_unique_id = f"orcon_mvs15_{self.fan_id}"
        self._attr_device_info = attached_device_info(self.fan_id)
        self._attr_extra_state_attributes: dict[
            str, str | int | bool | RamsesPacketDatetime | None
        ] = {
            "fan_fault": None,
        }

    async def async_set_preset_mode(self, preset_mode: str) -> None:
        await self.ramses_esp.set_preset_mode(preset_mode)

    @property
    def available(self) -> bool:
        """The fan has no state until 31D9 has been received."""
        return super().available and "fan_mode" in self.coordinator.data

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
