from __future__ import annotations

import logging

from typing import Any
from types import MappingProxyType

from homeassistant.components.fan import FanEntity, FanEntityFeature
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EVENT_HOMEASSISTANT_STARTED
from homeassistant.core import callback, CoreState, HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .ramses_packet import RamsesPacketDatetime, RamsesID
from .ramses_esp import RamsesESP
from .coordinator import OrconMVS15DataUpdateCoordinator
from .discover_entity import DiscoverEntity
from .codes import Code22f1
from .const import (
    DOMAIN,
    CONF_GATEWAY_ID,
    CONF_FAN_ID,
)

# TODO:
# * pytest
# * LICENSE
# * Add USB support for Ramses ESP (https://developers.home-assistant.io/docs/creating_integration_manifest?_highlight=mqtt#usb)
# * Start home-assistant timer on timed fan modes (22F3)
# * MQTT via_device for RAMSES_ESP
# * Use a custom Python type for the config data
# * Create devices in __init__._setup_coordinator, sensors and such only set identifiers
# * Auto discovery
#   - Discover fan_id: turn off/on the fan unit, fan_id == src_id of 1st 042F packet
#   - Bind as remote with random remote_id (1FC9)
#   - or: Discover existing remote by 22F1/22F3 packets to use that remote_id
#   - [DONE] Discover CO2: remote_id is a type I, code 31E0 to fan_id
#   - [DONE] Discover humidity: create sensor only after first successful pull
# * Add logo to https://brands.home-assistant.io/
# * Req 10e0, 31e0 and 1298 after CO2 sensors have been created/discovered

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> bool:
    fan = DiscoverEntity(
        hass=hass,
        async_add_entities=async_add_entities,
        config=entry.data,
        coordinator=entry.runtime_data.fan_coordinator,
        ramses_esp=entry.runtime_data.ramses_esp,
        ramses_id=entry.data[CONF_FAN_ID],
        label="fan",
        entities=[OrconFan],
    )
    entry.runtime_data.cleanup.append(fan.cleanup)

    return True


class OrconFan(CoordinatorEntity, FanEntity):
    _attr_preset_modes = Code22f1.presets()
    _attr_supported_features = FanEntityFeature.PRESET_MODE
    _attr_translation_key = "fan_states"  # see icons.json
    _attr_name = "Orcon MVS-15 fan"
    _attr_preset_mode = "Auto"

    def __init__(
        self,
        hass: HomeAssistant,
        ramses_id: RamsesID,
        config: MappingProxyType[str, Any],
        coordinator: OrconMVS15DataUpdateCoordinator,
        ramses_esp: RamsesESP,
        label: str,
    ) -> None:
        super().__init__(coordinator)
        self.hass = hass
        self._gateway_id = config[CONF_GATEWAY_ID]
        self._fan_id = config[CONF_FAN_ID]
        self._ramses_esp = ramses_esp
        self._attr_unique_id = f"orcon_mvs15_{self._fan_id}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, self._fan_id)},
            manufacturer="Orcon",
            model="MVS-15",
            name=f"{self.name} ({self._fan_id})",
            via_device=(DOMAIN, self._gateway_id),
        )
        self._attr_extra_state_attributes: dict[
            str, str | int | bool | RamsesPacketDatetime | None
        ] = {
            "fan_fault": None,
        }

    async def async_added_to_hass(self) -> None:
        """Called when an entity has their entity_id and hass object assigned"""
        await super().async_added_to_hass()
        if self.hass.state == CoreState.running:
            _LOGGER.info("Orcon MVS-15 integration has been setup")
            self.hass.async_create_task(self._ramses_esp.setup())
        else:
            _LOGGER.info("Orcon MVS-15 integration has been loaded after restart")
            self.hass.bus.async_listen_once(
                EVENT_HOMEASSISTANT_STARTED, self._ramses_esp.setup
            )

    async def async_set_preset_mode(self, preset_mode: str) -> None:
        await self._ramses_esp.set_preset_mode(preset_mode)

    @callback
    def _handle_coordinator_update(self) -> None:
        """handle updated data from the coordinator."""
        if not self.coordinator.data:
            return
        if "fan_mode" in self.coordinator.data:
            self._attr_preset_mode = self.coordinator.data["fan_mode"]
        if "fan_fault" in self.coordinator.data:
            self._attr_extra_state_attributes["fan_fault"] = self.coordinator.data[
                "fan_fault"
            ]
        if "fan_mode" in self.coordinator.data or "fan_fault" in self.coordinator.data:
            self.async_write_ha_state()
