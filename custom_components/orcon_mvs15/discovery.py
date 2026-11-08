"""Remember discovered RAMSES devices and tell the waiting entities."""

from __future__ import annotations

import logging

from collections.abc import Callable
from typing import TYPE_CHECKING

from homeassistant.core import HomeAssistant

from .const import CONF_CO2_ID, CONF_FAN_ID
from .ramses.protocol import RamsesID

if TYPE_CHECKING:
    from .models import OrconMVS15ConfigEntry

_LOGGER = logging.getLogger(__name__)

CONFIG_KEYS = {"fan": CONF_FAN_ID, "co2": CONF_CO2_ID}

type DiscoveryListener = Callable[[RamsesID], None]
type DeviceFactory = Callable[[str, RamsesID], None]


class DiscoveryManager:
    """The ids learned at runtime, shared by the controller and the entities."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: OrconMVS15ConfigEntry,
        ids: dict[str, RamsesID],
        create_device: DeviceFactory | None = None,
    ) -> None:
        self.hass = hass
        self.entry = entry
        self._ids = {kind: ids.get(kind, RamsesID()) for kind in CONFIG_KEYS}
        self._create_device = create_device
        self._listeners: dict[str, list[DiscoveryListener]] = {
            kind: [] for kind in CONFIG_KEYS
        }

    def get(self, kind: str) -> RamsesID:
        """Return the known id for a device kind, or an empty id."""
        return self._ids.get(kind, RamsesID())

    def discover(self, kind: str, ramses_id: RamsesID) -> bool:
        """Store a newly discovered id and return whether it was learned."""
        if not ramses_id or self._ids.get(kind):
            return False
        self._ids[kind] = ramses_id
        config_key = CONFIG_KEYS[kind]
        if not self.entry.data.get(config_key):
            _LOGGER.debug("Storing discovered %s (%s) in config", config_key, ramses_id)
            self.hass.config_entries.async_update_entry(
                self.entry, data={**self.entry.data, config_key: ramses_id}
            )
        if self._create_device is not None:
            self._create_device(kind, ramses_id)
        for listener in tuple(self._listeners[kind]):
            listener(ramses_id)
        return True

    def subscribe(self, kind: str, listener: DiscoveryListener) -> Callable[[], None]:
        """Call a listener when a device kind is discovered."""
        listeners = self._listeners[kind]
        listeners.append(listener)

        def _unsubscribe() -> None:
            if listener in listeners:
                listeners.remove(listener)

        return _unsubscribe
