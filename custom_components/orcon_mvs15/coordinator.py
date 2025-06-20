from __future__ import annotations

import logging

from dataclasses import dataclass, field
from typing import Callable, List

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .const import DOMAIN
from .ramses_esp import RamsesESP

_LOGGER = logging.getLogger(__name__)


@dataclass
class OrconMVS15RuntimeData:
    fan_coordinator: OrconMVS15DataUpdateCoordinator | None = None
    co2_coordinator: OrconMVS15DataUpdateCoordinator | None = None
    rem_coordinator: OrconMVS15DataUpdateCoordinator | None = None
    ramses_esp: RamsesESP | None = None
    cleanup: List[Callable[[], None]] = field(default_factory=list)


class OrconMVS15DataUpdateCoordinator(DataUpdateCoordinator[dict[str, str | int]]):
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
