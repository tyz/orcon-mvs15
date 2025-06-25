from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, List

from .coordinator import OrconMVS15DataUpdateCoordinator
from .ramses_esp import RamsesESP


@dataclass
class OrconMVS15RuntimeData:
    fan_coordinator: OrconMVS15DataUpdateCoordinator | None = None
    co2_coordinator: OrconMVS15DataUpdateCoordinator | None = None
    rem_coordinator: OrconMVS15DataUpdateCoordinator | None = None
    ramses_esp: RamsesESP | None = None
    cleanup: List[Callable[[], None]] = field(default_factory=list)
