import logging

from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)


class OrconMVS15PullDataUpdateCoordinator(DataUpdateCoordinator[Any]):
    config_entry: ConfigEntry

    def __init__(
        self,
        hass: HomeAssistant,
        config_entry: ConfigEntry,
        update_interval,
        callback_func: Any,
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            config_entry=config_entry,
            update_interval=update_interval,
        )
        self.callback_func = callback_func

    async def _async_update_data(self) -> dict:
        """Data will be updated as soon as the Ramses II reply has been received"""
        await self.callback_func()
        return {"_dummy": None}


class OrconMVS15PushDataUpdateCoordinator(DataUpdateCoordinator[Any]):
    config_entry: ConfigEntry

    def __init__(self, hass: HomeAssistant, config_entry: ConfigEntry) -> None:
        super().__init__(hass, _LOGGER, name=DOMAIN, config_entry=config_entry)

    async def _async_update_data(self) -> dict:
        """Raises NotImplementedError if this doesn't exist"""
        return {}
