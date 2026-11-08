from __future__ import annotations

import logging

from collections.abc import Callable
from typing import Protocol

from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import Entity
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .controller import OrconMVS15Controller
from .coordinator import OrconMVS15DataUpdateCoordinator
from .discovery import DiscoveryManager
from .models import OrconMVS15Config
from .ramses.protocol import RamsesID

_LOGGER = logging.getLogger(__name__)


class EntityFactory(Protocol):
    """Constructor of one entity created for a discovered device.

    The concrete classes live in the platform modules and share this keyword
    interface. Typing it here keeps DiscoverEntity independent of them.
    """

    __name__: str

    def __call__(
        self,
        *,
        hass: HomeAssistant,
        ramses_id: RamsesID,
        config: OrconMVS15Config,
        coordinator: OrconMVS15DataUpdateCoordinator,
        controller: OrconMVS15Controller,
        discovery_key: str,
    ) -> Entity: ...


class DiscoverEntity:
    """Create entities if the Ramses id is known, otherwise create them on device discovery."""

    def __init__(
        self,
        hass: HomeAssistant,
        async_add_entities: AddConfigEntryEntitiesCallback,
        config: OrconMVS15Config,
        coordinator: OrconMVS15DataUpdateCoordinator,
        controller: OrconMVS15Controller,
        discovery: DiscoveryManager,
        *,
        device_kind: str,
        name: str,
        discovery_key: str,
        entities: list[EntityFactory],
    ) -> None:
        self.hass = hass
        self.async_add_entities = async_add_entities
        self.config = config
        self.controller = controller
        self.discovery = discovery
        self.device_kind = device_kind
        self.ramses_id = discovery.get(device_kind)
        self.name = name
        self.entities = entities
        self.coordinator = coordinator
        self.discovery_key = discovery_key
        self.entity_names_csv = ",".join([x.__name__ for x in entities])
        self._unsub: Callable[[], None] | None = None
        if self.ramses_id:
            _LOGGER.debug(
                f"Setting up previously discovered '{name}' entities {self.entity_names_csv}"
            )
            self._add_entities()
            return
        _LOGGER.debug(
            f"Setting up '{name}' entity discovery for {self.entity_names_csv} "
            f"on '{device_kind}'"
        )
        self._unsub = discovery.subscribe(device_kind, self._add_discovered_entities)

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
                controller=self.controller,
                discovery_key=self.discovery_key,
            )
            for x in self.entities
        ]
        self.async_add_entities(new_entities, True)

    def _add_discovered_entities(self, ramses_id: RamsesID) -> None:
        self.ramses_id = ramses_id
        if not self.ramses_id:
            return
        self.cleanup()  # got the data, unsubscribe from the discovery manager
        _LOGGER.debug(
            f"Discovered '{self.name}' ({self.ramses_id}) entities: '{self.entity_names_csv}'"
        )
        self._add_entities()

    def cleanup(self) -> None:
        if self._unsub is not None:
            self._unsub()
            self._unsub = None
            _LOGGER.debug(
                f"Removed listener for '{self.device_kind}' after creating {self.entity_names_csv}"
            )
