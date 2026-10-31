from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .const import DOMAIN
from .ramses_packet import RamsesPacketDatetime

_LOGGER = logging.getLogger(__name__)

type CoordinatorData = dict[str, str | int | bool | RamsesPacketDatetime | None]


class OrconMVS15DataUpdateCoordinator(DataUpdateCoordinator[CoordinatorData]):
    config_entry: ConfigEntry

    def __init__(self, hass: HomeAssistant, config_entry: ConfigEntry) -> None:
        super().__init__(
            hass, _LOGGER, name=DOMAIN, config_entry=config_entry, always_update=False
        )

    async def _async_update_data(self) -> CoordinatorData:
        """We use it for push only"""
        if not self.data:
            return {}
        return {**self.data}
