from __future__ import annotations

import logging

from types import MappingProxyType
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import OrconMVS15DataUpdateCoordinator

_LOGGER = logging.getLogger(__name__)


class OrconSensor:
    """Create a (binary) sensor if the Ramses id is known, otherwise create them on device discovery"""

    def __init__(
        self,
        hass: HomeAssistant,
        async_add_entities: AddConfigEntryEntitiesCallback,
        config: MappingProxyType[str, Any],
        coordinator: OrconMVS15DataUpdateCoordinator,
        ramses_id: str,
        label: str,
        entities: list,
    ) -> None:
        self.async_add_entities = async_add_entities
        self.config = config
        self.ramses_id = ramses_id
        self.label = label
        self.entities = entities
        self.coordinator = coordinator
        self.discovery_key = f"discovered_{label.lower()}_id"
        if ramses_id:
            self._add_sensors()
            return
        _LOGGER.debug(
            f"Setting up discovery for {label} sensors on '{self.discovery_key}'"
        )
        self._unsub = self.coordinator.async_add_listener(self._add_discovered_sensors)
        hass.async_create_task(self.coordinator.async_refresh())

    def _add_sensors(self) -> None:
        _LOGGER.debug(
            f"Creating {len(self.entities)} {self.label} sensors ({self.ramses_id})"
        )
        new_entities = [
            x(
                self.ramses_id,
                self.config,
                self.coordinator,
                self.label,
            )
            for x in self.entities
        ]
        self.async_add_entities(new_entities, True)

    def _add_discovered_sensors(self) -> None:
        self.ramses_id = self.coordinator.data.get(self.discovery_key)
        if not self.ramses_id:
            return
        _LOGGER.debug(f"Creating discovered {self.label} sensors")
        self._add_sensors()
        self.cleanup()  # done, unsubscribe from DataCoordinator

    def cleanup(self) -> None:
        if hasattr(self, "_unsub") and self._unsub:
            self._unsub()
            self._unsub = None
            _LOGGER.debug(f"Removed listener for {self.discovery_key}")
