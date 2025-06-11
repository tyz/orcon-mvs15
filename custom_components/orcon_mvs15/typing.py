from dataclasses import dataclass
from typing import Any
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .ramses_esp import RamsesESP


@dataclass
class OrconMVS15RuntimeData:
    coordinator: DataUpdateCoordinator[Any] = None
    ramses_esp: RamsesESP = None


# type OrconMVS15ConfigEntry = ConfigEntry[OrconMVS15RuntimeData]  # noqa: E999
