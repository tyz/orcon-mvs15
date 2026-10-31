"""Tests for entity discovery."""

from __future__ import annotations

from typing import Any
from unittest.mock import Mock

import pytest
from homeassistant.core import HomeAssistant

from custom_components.orcon_mvs15.discover_entity import DiscoverEntity
from custom_components.orcon_mvs15.models import OrconMVS15Config
from custom_components.orcon_mvs15.ramses_packet import RamsesID

FAN_ID = "29:224547"


class FakeCoordinator:
    """Minimal coordinator that records its listener."""

    def __init__(self) -> None:
        self.data: dict[str, Any] = {}
        self.listener: Mock | None = None
        self.unsub = Mock()

    def async_add_listener(self, listener: Mock) -> Mock:
        self.listener = listener
        return self.unsub


class FakeEntity:
    """Records the arguments used to create it."""

    def __init__(self, **kwargs: object) -> None:
        self.kwargs = kwargs


def make_discovery(
    hass: HomeAssistant,
    ramses_id: RamsesID,
    add_entities: Mock,
    coordinator: FakeCoordinator,
) -> DiscoverEntity:
    """Build a discovery helper without a real coordinator."""
    return DiscoverEntity(
        hass=hass,
        async_add_entities=add_entities,
        config=OrconMVS15Config(),
        coordinator=coordinator,  # test stub, duck typed on purpose
        ramses_esp=Mock(),
        ramses_id=ramses_id,
        name="Orcon MVS-15 fan",
        discovery_key="fan",
        entities=[FakeEntity],
    )


async def test_known_id_adds_entities_immediately(hass: HomeAssistant) -> None:
    """An id from the config entry does not wait for discovery."""
    coordinator = FakeCoordinator()
    add_entities = Mock()

    make_discovery(hass, RamsesID(FAN_ID), add_entities, coordinator)

    add_entities.assert_called_once()
    (entities, update_before_add) = add_entities.call_args.args
    assert update_before_add is True
    assert entities[0].kwargs["ramses_id"] == FAN_ID
    assert coordinator.listener is None


async def test_cleanup_is_safe_before_a_listener_exists(
    hass: HomeAssistant,
) -> None:
    """Unloading a known device must not fail."""
    discovery = make_discovery(hass, RamsesID(FAN_ID), Mock(), FakeCoordinator())

    discovery.cleanup()


async def test_discovered_id_adds_entities_once(hass: HomeAssistant) -> None:
    """A discovered id creates the entities and removes the listener."""
    coordinator = FakeCoordinator()
    add_entities = Mock()
    make_discovery(hass, RamsesID(), add_entities, coordinator)
    assert coordinator.listener is not None

    coordinator.data = {"discovered_fan_id": RamsesID(FAN_ID)}
    coordinator.listener()

    add_entities.assert_called_once()
    assert add_entities.call_args.args[0][0].kwargs["ramses_id"] == FAN_ID
    coordinator.unsub.assert_called_once_with()

    coordinator.listener()
    assert add_entities.call_count == 1


@pytest.mark.parametrize("value", [123, None, "--:------", ""])
async def test_missing_or_invalid_discovered_id_is_ignored(
    hass: HomeAssistant, value: object
) -> None:
    """Only a real name string creates entities."""
    coordinator = FakeCoordinator()
    add_entities = Mock()
    discovery = make_discovery(hass, RamsesID(), add_entities, coordinator)
    assert coordinator.listener is not None

    coordinator.data = {"discovered_fan_id": value}
    coordinator.listener()

    add_entities.assert_not_called()
    coordinator.unsub.assert_not_called()
    assert not discovery.ramses_id
