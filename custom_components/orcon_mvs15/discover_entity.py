from __future__ import annotations

import logging

from types import MappingProxyType
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import OrconMVS15DataUpdateCoordinator
from .ramses_packet import RamsesID
from .ramses_esp import RamsesESP

_LOGGER = logging.getLogger(__name__)


class DiscoverEntity:
    """Create entities if the Ramses id is known, otherwise create them on device discovery"""

    def __init__(
        self,
        hass: HomeAssistant,
        async_add_entities: AddConfigEntryEntitiesCallback,
        config: MappingProxyType[str, Any],
        coordinator: OrconMVS15DataUpdateCoordinator,
        ramses_esp: RamsesESP,
        ramses_id: RamsesID,
        name: str,
        discovery_key: str,
        entities: list,
    ) -> None:
        self.hass = hass
        self.async_add_entities = async_add_entities
        self.config = config
        self.ramses_esp = ramses_esp
        self.ramses_id = ramses_id
        self.name = name
        self.entities = entities
        self.coordinator = coordinator
        self.discovery_key = discovery_key
        self.full_discovery_key = f"discovered_{discovery_key}_id"
        self.entity_names_csv = ",".join([x.__name__ for x in entities])
        if ramses_id:
            self._add_entities()
            return
        _LOGGER.debug(
            f"Setting up discovery on key '{self.full_discovery_key}' for '{name}' entities: {self.entity_names_csv}"
        )
        self._unsub = self.coordinator.async_add_listener(self._add_discovered_entities)

    def _add_entities(self) -> None:
        _LOGGER.debug(
            f"Creating '{self.name}' ({self.ramses_id}) entities: {self.entity_names_csv}"
        )
        new_entities = [
            x(
                hass=self.hass,
                ramses_id=self.ramses_id,
                config=self.config,
                coordinator=self.coordinator,
                ramses_esp=self.ramses_esp,
                name=self.name,
                discovery_key=self.discovery_key,
            )
            for x in self.entities
        ]
        self.async_add_entities(new_entities, True)

    def _add_discovered_entities(self) -> None:
        if self.ramses_id:
            return
        self.ramses_id = self.coordinator.data.get(self.full_discovery_key)
        if not self.ramses_id:
            return
        self.cleanup()  # got the data, unsubscribe from DataCoordinator
        _LOGGER.debug(
            f"Discovered '{self.name}' ({self.ramses_id}) entities: '{self.entity_names_csv}'"
        )
        self._add_entities()

    def cleanup(self) -> None:
        if hasattr(self, "_unsub") and self._unsub:
            self._unsub()
            self._unsub = None
            _LOGGER.debug(
                f"Removed listener for '{self.full_discovery_key}' after creating {self.entity_names_csv}"
            )
