from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)


class OrconMVS15DataUpdateCoordinator(DataUpdateCoordinator[dict[str, str | int]]):
    config_entry: ConfigEntry

    def __init__(self, hass: HomeAssistant, config_entry: ConfigEntry) -> None:
        super().__init__(
            hass, _LOGGER, name=DOMAIN, config_entry=config_entry, always_update=False
        )

    async def _async_update_data(self) -> dict:
        """We use it for push only"""
        if not self.data:
            return {}
        return {**self.data}
