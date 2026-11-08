"""Tests for entity discovery."""

from __future__ import annotations

from unittest.mock import Mock

from homeassistant.core import HomeAssistant

from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.orcon_mvs15.const import DOMAIN
from custom_components.orcon_mvs15.discover_entity import DiscoverEntity
from custom_components.orcon_mvs15.discovery import DiscoveryManager
from custom_components.orcon_mvs15.models import OrconMVS15Config
from custom_components.orcon_mvs15.ramses.protocol import RamsesID

FAN_ID = "29:224547"


class FakeEntity:
    """Records the arguments used to create it."""

    def __init__(self, **kwargs: object) -> None:
        self.kwargs = kwargs


def make_discovery(
    hass: HomeAssistant,
    ramses_id: RamsesID,
    add_entities: Mock,
) -> tuple[DiscoveryManager, DiscoverEntity]:
    """Build a discovery helper on top of the real discovery manager."""
    entry = MockConfigEntry(domain=DOMAIN, data={})
    entry.add_to_hass(hass)
    manager = DiscoveryManager(hass, entry, {"fan": ramses_id})
    helper = DiscoverEntity(
        hass=hass,
        async_add_entities=add_entities,
        config=OrconMVS15Config(),
        coordinator=Mock(),
        controller=Mock(),
        discovery=manager,
        device_kind="fan",
        name="Orcon MVS-15 fan",
        discovery_key="fan",
        entities=[FakeEntity],
    )
    return manager, helper


async def test_known_id_adds_entities_immediately(hass: HomeAssistant) -> None:
    """An id from the config entry does not wait for discovery."""
    add_entities = Mock()

    make_discovery(hass, RamsesID(FAN_ID), add_entities)

    add_entities.assert_called_once()
    (entities, update_before_add) = add_entities.call_args.args
    assert update_before_add is True
    assert entities[0].kwargs["ramses_id"] == FAN_ID
    assert entities[0].kwargs["discovery_key"] == "fan"
    assert entities[0].kwargs["controller"] is not None


async def test_cleanup_is_safe_before_a_listener_exists(
    hass: HomeAssistant,
) -> None:
    """Unloading a known device must not fail."""
    _manager, discovery = make_discovery(hass, RamsesID(FAN_ID), Mock())

    discovery.cleanup()


async def test_discovered_id_adds_entities_once(hass: HomeAssistant) -> None:
    """A discovered id creates the entities and removes the listener."""
    add_entities = Mock()
    manager, discovery = make_discovery(hass, RamsesID(), add_entities)
    assert add_entities.call_count == 0

    assert manager.discover("fan", RamsesID(FAN_ID)) is True

    assert add_entities.call_count == 1
    assert add_entities.call_args.args[0][0].kwargs["ramses_id"] == FAN_ID
    assert discovery.ramses_id == FAN_ID

    assert manager.discover("fan", RamsesID("29:000001")) is False
    assert add_entities.call_count == 1


async def test_missing_discovered_id_is_ignored(hass: HomeAssistant) -> None:
    """Only a real name string creates entities."""
    add_entities = Mock()
    _manager, discovery = make_discovery(hass, RamsesID(), add_entities)

    discovery._add_discovered_entities(RamsesID())

    add_entities.assert_not_called()
    assert not discovery.ramses_id
