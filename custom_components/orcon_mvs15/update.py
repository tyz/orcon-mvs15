"""Firmware updates for the RAMSES ESP gateway."""

from __future__ import annotations

from homeassistant.components.update import (
    UpdateDeviceClass,
    UpdateEntity,
    UpdateEntityFeature,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import TRANSPORT_MQTT
from .controller import OrconMVS15Controller
from .coordinator import OrconMVS15DataUpdateCoordinator
from .device import gateway_device_info
from .models import OrconMVS15Config, OrconMVS15ConfigEntry

# Only one update can run at a time; the controller waits for the reboot.
PARALLEL_UPDATES = 1


async def async_setup_entry(
    hass: HomeAssistant,
    entry: OrconMVS15ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Add the gateway firmware entity."""
    runtime = entry.runtime_data
    async_add_entities(
        [
            GatewayFirmwareUpdate(
                config=runtime.config,
                coordinator=runtime.gateway_coordinator,
                controller=runtime.controller,
            )
        ],
        True,
    )


class GatewayFirmwareUpdate(
    CoordinatorEntity[OrconMVS15DataUpdateCoordinator], UpdateEntity
):
    """The firmware running on the Ramses ESP gateway.

    The stick downloads and flashes the image itself; installation is not
    offered over USB yet.
    """

    _attr_has_entity_name = True
    _attr_translation_key = "firmware"
    _attr_device_class = UpdateDeviceClass.FIRMWARE

    def __init__(
        self,
        config: OrconMVS15Config,
        coordinator: OrconMVS15DataUpdateCoordinator,
        controller: OrconMVS15Controller,
    ) -> None:
        super().__init__(coordinator)
        self.controller = controller
        self._attr_unique_id = f"orcon_mvs15_gateway_firmware_{config.gateway_id}"
        self._attr_device_info = gateway_device_info(config.gateway_id)
        if config.transport == TRANSPORT_MQTT:
            self._attr_supported_features = (
                UpdateEntityFeature.INSTALL | UpdateEntityFeature.SPECIFIC_VERSION
            )

    @property
    def installed_version(self) -> str | None:
        """Return the firmware version the gateway is running."""
        version = self.coordinator.data.get("firmware_version")
        return version if isinstance(version, str) else None

    @property
    def latest_version(self) -> str | None:
        """Return the newest firmware version the gateway found."""
        version = self.coordinator.data.get("latest_firmware_version")
        return version if isinstance(version, str) else None

    async def async_install(
        self, version: str | None, backup: bool, **kwargs: object
    ) -> None:
        """Ask the gateway to install the latest or a specific firmware."""
        await self.controller.async_install_firmware(version)
