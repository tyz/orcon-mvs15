"""Tests for config entry setup and unload."""

from __future__ import annotations

import logging

from unittest.mock import AsyncMock, patch

import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import EVENT_HOMEASSISTANT_STARTED
from homeassistant.core import CoreState, HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.device_registry import DeviceRegistry
from homeassistant.helpers.entity_registry import RegistryEntryDisabler

from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.orcon_mvs15 import async_remove_config_entry_device
from custom_components.orcon_mvs15.const import (
    CONF_CO2_ID,
    CONF_FAN_ID,
    CONF_GATEWAY_ID,
    CONF_MQTT_TOPIC,
    CONF_PACKET_LOG,
    CONF_REMOTE_ID,
    DOMAIN,
)
from custom_components.orcon_mvs15.ramses.protocol import RamsesID
from custom_components.orcon_mvs15.ramses.transport import (
    ConnectionState,
    TransportError,
)
from custom_components.orcon_mvs15.ramses.transport.loopback import LoopbackTransport

REMOTE_ID = "29:163058"
FAN_ID = "29:224547"
CO2_ID = "29:111111"
GATEWAY_ID = "18:149960"
MQTT_TOPIC = "RAMSES/GATEWAY"
TIMESTAMP = "2026-09-11T17:29:09.534250+02:00"

POWERUP = f"044 I --- --:------ --:------ {FAN_ID} 042F 006 00004C004C00"


class FakeTransport(LoopbackTransport):
    """Stand-in for the MQTT transport during entry setup."""

    last_instance: FakeTransport | None = None

    def __init__(
        self,
        backend: object,
        base_topic: str,
        gateway_id: RamsesID = RamsesID(),
        discovery_timeout: float = 10.0,
    ) -> None:
        super().__init__(gateway_id=gateway_id)
        self.backend = backend
        self.base_topic = base_topic
        self.cleaned = False
        FakeTransport.last_instance = self

    async def init(self) -> None:
        """Discover the gateway the way the real transport does."""
        if not self.gateway_id:
            self._gateway_id = RamsesID(GATEWAY_ID)

    async def stop(self) -> None:
        """Record that the transport was released."""
        self.cleaned = True
        await super().stop()


def make_entry(**data: str) -> MockConfigEntry:
    """Build a registered config entry with the MQTT topic filled in."""
    return MockConfigEntry(domain=DOMAIN, data={CONF_MQTT_TOPIC: MQTT_TOPIC, **data})


async def test_setup_retries_when_the_gateway_is_not_found(
    hass: HomeAssistant,
) -> None:
    """A missing gateway is a retryable setup failure, not a broken entry."""
    entry = make_entry(**{CONF_REMOTE_ID: REMOTE_ID, CONF_MQTT_TOPIC: MQTT_TOPIC})
    entry.add_to_hass(hass)

    with patch(
        "custom_components.orcon_mvs15.RamsesESP.init",
        AsyncMock(side_effect=TransportError("No gateway message")),
    ):
        assert await hass.config_entries.async_setup(entry.entry_id) is False

    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.SETUP_RETRY
    assert entry.error_reason_translation_domain == DOMAIN
    assert entry.error_reason_translation_key == "mqtt_setup_failed"
    assert entry.error_reason_translation_placeholders == {
        "error": "No gateway message"
    }


async def test_setup_builds_the_runtime_data_and_unloads(
    hass: HomeAssistant, device_registry: DeviceRegistry
) -> None:
    """A successful setup fills runtime data, then unload cleans it up."""
    entry = make_entry(
        **{
            CONF_REMOTE_ID: REMOTE_ID,
            CONF_FAN_ID: FAN_ID,
            CONF_GATEWAY_ID: GATEWAY_ID,
            CONF_MQTT_TOPIC: MQTT_TOPIC,
        }
    )
    entry.add_to_hass(hass)

    with patch("custom_components.orcon_mvs15.RamsesESP", FakeTransport):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    assert entry.state is ConfigEntryState.LOADED
    runtime = entry.runtime_data
    assert runtime.config.fan_id == FAN_ID
    assert runtime.config.gateway_id == GATEWAY_ID
    assert runtime.session.gateway_id == GATEWAY_ID
    assert runtime.controller.fan_id == FAN_ID
    assert runtime.discovery.get("fan") == FAN_ID
    assert runtime.session.subscribed_codes == {
        "042F",
        "10E0",
        "1298",
        "12A0",
        "22F1",
        "22F3",
        "31D9",
        "31E0",
    }
    assert FakeTransport.last_instance is not None
    transport = FakeTransport.last_instance
    assert transport.started

    transport.set_connection_state(ConnectionState.DISCONNECTED)
    await hass.async_block_till_done()
    assert runtime.fan_coordinator.last_update_success is False
    assert runtime.co2_coordinator.last_update_success is False

    transport.set_connection_state(ConnectionState.CONNECTED)
    await hass.async_block_till_done()
    assert runtime.fan_coordinator.last_update_success is True

    fan_states = hass.states.async_all("fan")
    assert len(fan_states) == 1
    assert fan_states[0].name == "Orcon MVS-15 fan (29:224547) Fan"
    gateway = device_registry.async_get_device_by_identifier(
        (DOMAIN, GATEWAY_ID), entry.entry_id
    )
    assert gateway is not None

    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()

    assert entry.state is ConfigEntryState.NOT_LOADED
    assert transport.cleaned


async def test_setup_passes_the_packet_log_option_to_the_controller(
    hass: HomeAssistant,
) -> None:
    """Enabling the option turns the debugging log on for the controller."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            CONF_REMOTE_ID: REMOTE_ID,
            CONF_FAN_ID: FAN_ID,
            CONF_GATEWAY_ID: GATEWAY_ID,
            CONF_MQTT_TOPIC: MQTT_TOPIC,
        },
        options={CONF_PACKET_LOG: True},
    )
    entry.add_to_hass(hass)

    with patch("custom_components.orcon_mvs15.RamsesESP", FakeTransport):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    assert entry.runtime_data.controller.packet_log_enabled is True
    assert entry.runtime_data.controller.packet_log_path == hass.config.path(
        "packet.log"
    )

    assert await hass.config_entries.async_unload(entry.entry_id)


async def test_setup_stores_a_discovered_fan_id(hass: HomeAssistant) -> None:
    """The fan announced by 042F is remembered without reloading the entry."""
    entry = make_entry(**{CONF_REMOTE_ID: REMOTE_ID, CONF_GATEWAY_ID: GATEWAY_ID})
    entry.add_to_hass(hass)

    with patch("custom_components.orcon_mvs15.RamsesESP", FakeTransport):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    assert entry.runtime_data.fan_coordinator.data == {}
    assert FakeTransport.last_instance is not None

    await FakeTransport.last_instance.receive_frame(POWERUP, TIMESTAMP)
    await hass.async_block_till_done()

    assert entry.data[CONF_FAN_ID] == FAN_ID

    assert await hass.config_entries.async_unload(entry.entry_id)


async def test_an_empty_discovered_fan_id_is_not_stored(
    hass: HomeAssistant,
) -> None:
    """A 042F without a sender must not stop discovery for the real fan."""
    entry = make_entry(**{CONF_REMOTE_ID: REMOTE_ID, CONF_GATEWAY_ID: GATEWAY_ID})
    entry.add_to_hass(hass)

    with patch("custom_components.orcon_mvs15.RamsesESP", FakeTransport):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    assert FakeTransport.last_instance is not None

    await FakeTransport.last_instance.receive_frame(
        "044 I --- --:------ --:------ --:------ 042F 006 00004C004C00", TIMESTAMP
    )
    await hass.async_block_till_done()

    assert CONF_FAN_ID not in entry.data

    await FakeTransport.last_instance.receive_frame(POWERUP, TIMESTAMP)
    await hass.async_block_till_done()

    assert entry.data[CONF_FAN_ID] == FAN_ID

    assert await hass.config_entries.async_unload(entry.entry_id)


async def test_setup_creates_the_configured_devices(
    hass: HomeAssistant, device_registry: DeviceRegistry
) -> None:
    """The fan and CO2 devices exist before any entity is added."""
    entry = make_entry(
        **{
            CONF_REMOTE_ID: REMOTE_ID,
            CONF_FAN_ID: FAN_ID,
            CONF_CO2_ID: CO2_ID,
            CONF_GATEWAY_ID: GATEWAY_ID,
            CONF_MQTT_TOPIC: MQTT_TOPIC,
        }
    )
    entry.add_to_hass(hass)

    with (
        patch("custom_components.orcon_mvs15.RamsesESP", FakeTransport),
        patch.object(hass.config_entries, "async_forward_entry_setups", AsyncMock()),
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    gateway = device_registry.async_get_device_by_identifier(
        (DOMAIN, GATEWAY_ID), entry.entry_id
    )
    fan = device_registry.async_get_device_by_identifier(
        (DOMAIN, FAN_ID), entry.entry_id
    )
    co2 = device_registry.async_get_device_by_identifier(
        (DOMAIN, CO2_ID), entry.entry_id
    )

    assert gateway is not None
    assert fan is not None
    assert fan.model == "MVS-15"
    assert fan.via_device_id == gateway.id
    assert co2 is not None
    assert co2.model == "CO2 ruimtesensor 15RF"
    assert co2.via_device_id == gateway.id

    assert await hass.config_entries.async_unload(entry.entry_id)


async def test_a_discovered_fan_creates_its_device(
    hass: HomeAssistant, device_registry: DeviceRegistry
) -> None:
    """Discovery registers the device even when no entity is added yet."""
    entry = make_entry(**{CONF_REMOTE_ID: REMOTE_ID, CONF_GATEWAY_ID: GATEWAY_ID})
    entry.add_to_hass(hass)

    with (
        patch("custom_components.orcon_mvs15.RamsesESP", FakeTransport),
        patch.object(hass.config_entries, "async_forward_entry_setups", AsyncMock()),
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    assert FakeTransport.last_instance is not None
    await FakeTransport.last_instance.receive_frame(POWERUP, TIMESTAMP)
    await hass.async_block_till_done()

    fan = device_registry.async_get_device_by_identifier(
        (DOMAIN, FAN_ID), entry.entry_id
    )

    assert entry.data[CONF_FAN_ID] == FAN_ID
    assert fan is not None
    assert fan.model == "MVS-15"

    assert await hass.config_entries.async_unload(entry.entry_id)


async def test_setup_stores_a_discovered_gateway_id(hass: HomeAssistant) -> None:
    """A wildcard-discovered gateway is remembered in the entry data."""
    entry = make_entry(**{CONF_REMOTE_ID: REMOTE_ID, CONF_MQTT_TOPIC: MQTT_TOPIC})
    entry.add_to_hass(hass)

    with patch("custom_components.orcon_mvs15.RamsesESP", FakeTransport):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    assert entry.data[CONF_GATEWAY_ID] == GATEWAY_ID
    assert entry.runtime_data.config.gateway_id == GATEWAY_ID

    assert await hass.config_entries.async_unload(entry.entry_id)


async def test_setup_retries_when_the_session_cannot_be_built(
    hass: HomeAssistant,
) -> None:
    """A session construction error is retryable, not a permanent failure."""
    entry = make_entry(**{CONF_REMOTE_ID: REMOTE_ID, CONF_GATEWAY_ID: GATEWAY_ID})
    entry.add_to_hass(hass)

    with (
        patch("custom_components.orcon_mvs15.RamsesESP", FakeTransport),
        patch(
            "custom_components.orcon_mvs15.RamsesSession",
            side_effect=RuntimeError("bad configuration"),
        ),
    ):
        assert await hass.config_entries.async_setup(entry.entry_id) is False

    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.SETUP_RETRY
    assert entry.error_reason_translation_domain == DOMAIN
    assert entry.error_reason_translation_key == "session_setup_failed"
    assert entry.error_reason_translation_placeholders == {"error": "bad configuration"}


async def test_setup_keeps_a_retryable_session_error(hass: HomeAssistant) -> None:
    """ConfigEntryNotReady from the session is not wrapped a second time."""
    entry = make_entry(**{CONF_REMOTE_ID: REMOTE_ID, CONF_GATEWAY_ID: GATEWAY_ID})
    entry.add_to_hass(hass)

    with (
        patch("custom_components.orcon_mvs15.RamsesESP", FakeTransport),
        patch(
            "custom_components.orcon_mvs15.RamsesSession",
            side_effect=ConfigEntryNotReady("MQTT is not ready"),
        ),
    ):
        assert await hass.config_entries.async_setup(entry.entry_id) is False

    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.SETUP_RETRY


async def test_setup_waits_for_home_assistant_to_start(hass: HomeAssistant) -> None:
    """During a restart the session starts with Home Assistant, not before."""
    entry = make_entry(
        **{
            CONF_REMOTE_ID: REMOTE_ID,
            CONF_FAN_ID: FAN_ID,
            CONF_GATEWAY_ID: GATEWAY_ID,
            CONF_MQTT_TOPIC: MQTT_TOPIC,
        }
    )
    entry.add_to_hass(hass)
    hass.set_state(CoreState.not_running)

    with (
        patch("custom_components.orcon_mvs15.RamsesESP", FakeTransport),
        patch("custom_components.orcon_mvs15.asyncio.sleep", AsyncMock()),
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

        runtime = entry.runtime_data
        assert FakeTransport.last_instance is not None
        assert FakeTransport.last_instance.started is False

        hass.bus.async_fire(EVENT_HOMEASSISTANT_STARTED)
        await hass.async_block_till_done()

    assert FakeTransport.last_instance.started is True
    assert runtime.session.subscribed_codes

    assert await hass.config_entries.async_unload(entry.entry_id)


async def test_a_failed_session_start_retries_the_entry(
    hass: HomeAssistant,
) -> None:
    """A broker that is not ready must send the entry back to SETUP_RETRY."""
    entry = make_entry(
        **{
            CONF_REMOTE_ID: REMOTE_ID,
            CONF_FAN_ID: FAN_ID,
            CONF_GATEWAY_ID: GATEWAY_ID,
            CONF_MQTT_TOPIC: MQTT_TOPIC,
        }
    )
    entry.add_to_hass(hass)

    with (
        patch("custom_components.orcon_mvs15.RamsesESP", FakeTransport),
        patch(
            "custom_components.orcon_mvs15.RamsesSession.start",
            AsyncMock(
                side_effect=ConfigEntryNotReady(
                    translation_domain=DOMAIN,
                    translation_key="mqtt_not_available",
                )
            ),
        ),
    ):
        assert await hass.config_entries.async_setup(entry.entry_id) is False

    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.SETUP_RETRY
    assert entry.error_reason_translation_key == "mqtt_not_available"
    assert FakeTransport.last_instance is not None
    assert FakeTransport.last_instance.cleaned


async def test_an_unexpected_session_start_failure_is_retryable(
    hass: HomeAssistant,
) -> None:
    """A broken session becomes a translated retryable failure."""
    entry = make_entry(
        **{
            CONF_REMOTE_ID: REMOTE_ID,
            CONF_FAN_ID: FAN_ID,
            CONF_GATEWAY_ID: GATEWAY_ID,
            CONF_MQTT_TOPIC: MQTT_TOPIC,
        }
    )
    entry.add_to_hass(hass)

    with (
        patch("custom_components.orcon_mvs15.RamsesESP", FakeTransport),
        patch(
            "custom_components.orcon_mvs15.RamsesSession.start",
            AsyncMock(side_effect=RuntimeError("the stick is unplugged")),
        ),
    ):
        assert await hass.config_entries.async_setup(entry.entry_id) is False

    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.SETUP_RETRY
    assert entry.error_reason_translation_domain == DOMAIN
    assert entry.error_reason_translation_key == "session_setup_failed"
    assert entry.error_reason_translation_placeholders == {
        "error": "the stick is unplugged"
    }


async def test_a_failed_start_after_restart_schedules_a_reload(
    hass: HomeAssistant, caplog: pytest.LogCaptureFixture
) -> None:
    """The deferred start has no caller to raise to, so it reloads instead."""
    entry = make_entry(
        **{
            CONF_REMOTE_ID: REMOTE_ID,
            CONF_FAN_ID: FAN_ID,
            CONF_GATEWAY_ID: GATEWAY_ID,
            CONF_MQTT_TOPIC: MQTT_TOPIC,
        }
    )
    entry.add_to_hass(hass)
    hass.set_state(CoreState.not_running)

    with (
        patch("custom_components.orcon_mvs15.RamsesESP", FakeTransport),
        patch(
            "custom_components.orcon_mvs15.RamsesSession.start",
            AsyncMock(
                side_effect=ConfigEntryNotReady(
                    translation_domain=DOMAIN,
                    translation_key="mqtt_not_available",
                )
            ),
        ),
        patch("custom_components.orcon_mvs15.asyncio.sleep", AsyncMock()),
        patch.object(hass.config_entries, "async_schedule_reload") as reload,
        caplog.at_level(logging.ERROR),
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

        hass.bus.async_fire(EVENT_HOMEASSISTANT_STARTED)
        await hass.async_block_till_done()

    reload.assert_called_once_with(entry.entry_id)
    assert "failed to start" in caplog.text


async def test_signal_strength_is_disabled_by_default(hass: HomeAssistant) -> None:
    """A noisy diagnostic entity stays out of the history until enabled."""
    entry = make_entry(
        **{
            CONF_REMOTE_ID: REMOTE_ID,
            CONF_FAN_ID: FAN_ID,
            CONF_GATEWAY_ID: GATEWAY_ID,
            CONF_MQTT_TOPIC: MQTT_TOPIC,
        }
    )
    entry.add_to_hass(hass)

    with patch("custom_components.orcon_mvs15.RamsesESP", FakeTransport):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    registry = er.async_get(hass)
    signal_entries = [
        registry_entry
        for registry_entry in registry.entities.values()
        if registry_entry.unique_id.startswith("orcon_mvs15_fan_dbm_")
    ]

    assert len(signal_entries) == 1
    assert signal_entries[0].disabled_by is RegistryEntryDisabler.INTEGRATION


async def test_stale_device_removal_keeps_the_gateway(
    hass: HomeAssistant, device_registry: DeviceRegistry
) -> None:
    """A fan may be removed; the gateway stays while the entry exists."""
    entry = make_entry(**{CONF_GATEWAY_ID: GATEWAY_ID, CONF_MQTT_TOPIC: MQTT_TOPIC})
    entry.add_to_hass(hass)
    gateway = device_registry.async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={(DOMAIN, GATEWAY_ID)},
    )
    fan = device_registry.async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={(DOMAIN, FAN_ID)},
    )

    assert await async_remove_config_entry_device(hass, entry, gateway) is False
    assert await async_remove_config_entry_device(hass, entry, fan) is True
