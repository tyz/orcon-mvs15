import logging

from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)


class OrconMVS15DataUpdateCoordinator(DataUpdateCoordinator[Any]):
    config_entry: ConfigEntry

    def __init__(self, hass: HomeAssistant, config_entry: ConfigEntry) -> None:
        super().__init__(
            hass, _LOGGER, name=DOMAIN, config_entry=config_entry, always_update=False
        )

    async def _async_update_data(self) -> dict:
        """Will be called once, polling will be disabled as soon as the first
        Ramses II informational or response payload has been received and
        async_set_updated_data gets called"""
        return {}
