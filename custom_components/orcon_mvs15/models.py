from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable
from types import MappingProxyType

from homeassistant.config_entries import ConfigEntry

from .controller import OrconMVS15Controller
from .coordinator import OrconMVS15DataUpdateCoordinator
from .discovery import DiscoveryManager
from .ramses.protocol import RamsesID
from .ramses.session import RamsesSession
from .const import (
    CONF_GATEWAY_ID,
    CONF_REMOTE_ID,
    CONF_FAN_ID,
    CONF_CO2_ID,
    CONF_MQTT_TOPIC,
    CONF_TRANSPORT,
    CONF_USB_PORT,
    DEFAULT_MQTT_TOPIC,
    DEFAULT_TRANSPORT,
)


@dataclass
class OrconMVS15Config:
    gateway_id: RamsesID = RamsesID()
    remote_id: RamsesID = RamsesID()
    fan_id: RamsesID = RamsesID()
    co2_id: RamsesID = RamsesID()
    mqtt_topic: str = DEFAULT_MQTT_TOPIC
    transport: str = DEFAULT_TRANSPORT
    usb_port: str = ""

    @classmethod
    def from_data(cls, data: MappingProxyType[str, str]) -> OrconMVS15Config:
        return cls(
            gateway_id=RamsesID(data.get(CONF_GATEWAY_ID)),
            remote_id=RamsesID(data.get(CONF_REMOTE_ID)),
            fan_id=RamsesID(data.get(CONF_FAN_ID)),
            co2_id=RamsesID(data.get(CONF_CO2_ID)),
            mqtt_topic=data.get(CONF_MQTT_TOPIC, DEFAULT_MQTT_TOPIC),
            transport=data.get(CONF_TRANSPORT, DEFAULT_TRANSPORT),
            usb_port=data.get(CONF_USB_PORT, ""),
        )


@dataclass
class OrconMVS15RuntimeData:
    config: OrconMVS15Config
    fan_coordinator: OrconMVS15DataUpdateCoordinator
    co2_coordinator: OrconMVS15DataUpdateCoordinator
    session: RamsesSession
    controller: OrconMVS15Controller
    discovery: DiscoveryManager
    cleanup: list[Callable[[], None]] = field(default_factory=list)


type OrconMVS15ConfigEntry = ConfigEntry[OrconMVS15RuntimeData]
