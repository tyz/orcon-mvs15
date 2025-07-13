from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, List
from types import MappingProxyType

from .coordinator import OrconMVS15DataUpdateCoordinator
from .ramses_packet import RamsesID
from .ramses_esp import RamsesESP
from .const import (
    CONF_GATEWAY_ID,
    CONF_REMOTE_ID,
    CONF_FAN_ID,
    CONF_CO2_ID,
    CONF_MQTT_TOPIC,
)


@dataclass
class OrconMVS15RuntimeData:
    config: OrconMVS15Config | None = None
    fan_coordinator: OrconMVS15DataUpdateCoordinator | None = None
    co2_coordinator: OrconMVS15DataUpdateCoordinator | None = None
    rem_coordinator: OrconMVS15DataUpdateCoordinator | None = None
    ramses_esp: RamsesESP | None = None
    cleanup: List[Callable[[], None]] = field(default_factory=list)


@dataclass
class OrconMVS15Config:
    gateway_id: RamsesID = RamsesID()
    remote_id: RamsesID = RamsesID()
    fan_id: RamsesID = RamsesID()
    co2_id: RamsesID = RamsesID()
    mqtt_topic: str = "RAMSES/GATEWAY"

    @classmethod
    def from_data(cls, data: MappingProxyType[str, str]) -> OrconMVS15Config:
        return cls(
            gateway_id=RamsesID(data.get(CONF_GATEWAY_ID)),
            remote_id=RamsesID(data.get(CONF_REMOTE_ID)),
            fan_id=RamsesID(data.get(CONF_FAN_ID)),
            co2_id=RamsesID(data.get(CONF_CO2_ID)),
            mqtt_topic=data[CONF_MQTT_TOPIC],
        )
