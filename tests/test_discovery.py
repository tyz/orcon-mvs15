"""Tests for the discovery manager."""

from __future__ import annotations

from unittest.mock import Mock

import pytest
from homeassistant.core import HomeAssistant

from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.orcon_mvs15.const import CONF_FAN_ID, DOMAIN
from custom_components.orcon_mvs15.discovery import DiscoveryManager
from custom_components.orcon_mvs15.ramses.protocol import RamsesID

FAN_ID = "29:224547"


def make_entry(hass: HomeAssistant) -> MockConfigEntry:
    """Add an entry the manager can update."""
    entry = MockConfigEntry(domain=DOMAIN, data={})
    entry.add_to_hass(hass)
    return entry


def test_known_ids_are_returned_and_unknown_kinds_are_empty(
    hass: HomeAssistant,
) -> None:
    """The manager exposes configured ids and an empty id for the rest."""
    discovery = DiscoveryManager(hass, make_entry(hass), {"fan": RamsesID(FAN_ID)})

    assert discovery.get("fan") == FAN_ID
    assert discovery.get("co2") == RamsesID()
    assert discovery.get("other") == RamsesID()


def test_discovering_a_device_stores_it_and_notifies_listeners(
    hass: HomeAssistant,
) -> None:
    """A learned id is written to the entry, the registry and the listeners."""
    entry = make_entry(hass)
    created: list[tuple[str, RamsesID]] = []
    discovery = DiscoveryManager(
        hass,
        entry,
        {},
        create_device=lambda kind, ramses_id: created.append((kind, ramses_id)),
    )
    listener = Mock()
    discovery.subscribe("fan", listener)

    assert discovery.discover("fan", RamsesID(FAN_ID)) is True

    assert discovery.get("fan") == FAN_ID
    assert entry.data[CONF_FAN_ID] == FAN_ID
    assert created == [("fan", RamsesID(FAN_ID))]
    listener.assert_called_once_with(RamsesID(FAN_ID))
    assert discovery.discover("fan", RamsesID("29:000001")) is False


def test_an_empty_id_is_not_discovered(hass: HomeAssistant) -> None:
    """A frame without a usable sender must not stop discovery."""
    discovery = DiscoveryManager(hass, make_entry(hass), {})

    assert discovery.discover("fan", RamsesID()) is False
    assert not discovery.get("fan")


def test_an_id_already_in_the_entry_is_not_written_back(
    hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Only a genuinely new id touches the config entry."""
    entry = MockConfigEntry(domain=DOMAIN, data={CONF_FAN_ID: FAN_ID})
    entry.add_to_hass(hass)
    update = Mock()
    monkeypatch.setattr(hass.config_entries, "async_update_entry", update)
    discovery = DiscoveryManager(hass, entry, {"fan": RamsesID()})

    assert discovery.discover("fan", RamsesID(FAN_ID)) is True

    update.assert_not_called()


def test_unsubscribing_stops_the_listener(hass: HomeAssistant) -> None:
    """Every discovery subscription has its own unsubscribe callable."""
    discovery = DiscoveryManager(hass, make_entry(hass), {})
    fan = Mock()
    co2 = Mock()
    unsub_fan = discovery.subscribe("fan", fan)
    discovery.subscribe("co2", co2)

    unsub_fan()
    discovery.discover("fan", RamsesID(FAN_ID))
    discovery.discover("co2", RamsesID("32:093959"))

    fan.assert_not_called()
    co2.assert_called_once_with(RamsesID("32:093959"))
