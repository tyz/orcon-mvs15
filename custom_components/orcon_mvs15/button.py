"""Reboot the RAMSES ESP gateway."""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.components.button.const import ButtonDeviceClass
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .controller import OrconMVS15Controller
from .coordinator import OrconMVS15DataUpdateCoordinator
from .device import attached_device_info, gateway_device_info
from .discover_entity import DiscoverEntity
from .models import OrconMVS15Config, OrconMVS15ConfigEntry
from .ramses.protocol import RamsesID

# One command at a time; the firmware console is line based.
PARALLEL_UPDATES = 1


async def async_setup_entry(
    hass: HomeAssistant,
    entry: OrconMVS15ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Add the gateway reboot button and, for a fake remote, the pair button."""
    runtime = entry.runtime_data
    async_add_entities(
        [
            GatewayRebootButton(
                config=runtime.config,
                coordinator=runtime.gateway_coordinator,
                controller=runtime.controller,
            )
        ],
        True,
    )
    if runtime.config.fake_remote:
        pair_remote = DiscoverEntity(
            hass=hass,
            async_add_entities=async_add_entities,
            config=runtime.config,
            coordinator=runtime.fan_coordinator,
            controller=runtime.controller,
            discovery=runtime.discovery,
            device_kind="fan",
            name="Orcon MVS-15 fan",
            discovery_key="fan",
            entities=[PairRemoteButton],
        )
        runtime.cleanup.append(pair_remote.cleanup)


class GatewayRebootButton(
    CoordinatorEntity[OrconMVS15DataUpdateCoordinator], ButtonEntity
):
    """Reboot the stick so it reconnects to WiFi and the MQTT broker."""

    _attr_has_entity_name = True
    _attr_translation_key = "reboot"
    _attr_device_class = ButtonDeviceClass.RESTART
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(
        self,
        config: OrconMVS15Config,
        coordinator: OrconMVS15DataUpdateCoordinator,
        controller: OrconMVS15Controller,
    ) -> None:
        super().__init__(coordinator)
        self.controller = controller
        self._attr_unique_id = f"orcon_mvs15_gateway_reboot_{config.gateway_id}"
        self._attr_device_info = gateway_device_info(config.gateway_id)

    async def async_press(self) -> None:
        """Send the firmware reset command."""
        await self.controller.async_reboot_gateway()


class PairRemoteButton(CoordinatorEntity, ButtonEntity):
    """Start the 1FC9 pairing handshake for the generated fake remote."""

    _attr_has_entity_name = True
    _attr_translation_key = "pair_remote"
    _attr_entity_category = EntityCategory.CONFIG

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
        self.controller = controller
        self._attr_unique_id = f"orcon_mvs15_pair_remote_{ramses_id}"
        self._attr_device_info = attached_device_info(ramses_id)

    async def async_press(self) -> None:
        """Run the pairing handshake while the fan is in pairing mode."""
        await self.controller.async_pair_remote()
