"""Tests for config entry setup and unload."""

from __future__ import annotations

from collections.abc import Callable
from unittest.mock import AsyncMock, patch

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceRegistry

from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.orcon_mvs15.const import (
    CONF_FAN_ID,
    CONF_GATEWAY_ID,
    CONF_MQTT_TOPIC,
    CONF_REMOTE_ID,
    DOMAIN,
)
from custom_components.orcon_mvs15.mqtt import MQTTException
from custom_components.orcon_mvs15.ramses_packet import RamsesID

REMOTE_ID = "29:163058"
FAN_ID = "29:224547"
GATEWAY_ID = "18:149960"
MQTT_TOPIC = "RAMSES/GATEWAY"


class FakeMQTT:
    """Stand-in for the transport during entry setup."""

    last_instance: FakeMQTT | None = None

    def __init__(
        self,
        hass: HomeAssistant,
        base_topic: str,
        gateway_id: RamsesID,
        connection_callback: Callable[[bool], None] | None = None,
    ) -> None:
        self.gateway_id = gateway_id
        self.connection_callback = connection_callback
        self.cleaned = False
        FakeMQTT.last_instance = self

    async def init(self) -> None:
        pass

    def cleanup(self) -> None:
        self.cleaned = True


class FakeRamses:
    """Stand-in for the protocol session during entry setup."""

    def __init__(self, **kwargs: object) -> None:
        self.kwargs = kwargs
        self.handlers: dict[str, object] = {}
        self.cleaned = False
        self.started = False

    def add_handler(self, code: str, func: object) -> None:
        self.handlers[code] = func

    async def init_fan(self, discovered_fan_id: RamsesID) -> None:
        self.discovered_fan_id = discovered_fan_id

    async def setup(self) -> None:
        self.started = True

    def cleanup(self) -> None:
        self.cleaned = True


async def test_setup_retries_when_the_gateway_is_not_found(
    hass: HomeAssistant,
) -> None:
    """A missing gateway is a retryable setup failure, not a broken entry."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_REMOTE_ID: REMOTE_ID, CONF_MQTT_TOPIC: MQTT_TOPIC},
    )
    entry.add_to_hass(hass)

    with patch(
        "custom_components.orcon_mvs15.MQTT.init",
        AsyncMock(side_effect=MQTTException("No gateway message")),
    ):
        assert await hass.config_entries.async_setup(entry.entry_id) is False

    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.SETUP_RETRY


async def test_setup_builds_the_runtime_data_and_unloads(
    hass: HomeAssistant, device_registry: DeviceRegistry
) -> None:
    """A successful setup fills runtime data, then unload cleans it up."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            CONF_REMOTE_ID: REMOTE_ID,
            CONF_FAN_ID: FAN_ID,
            CONF_GATEWAY_ID: GATEWAY_ID,
            CONF_MQTT_TOPIC: MQTT_TOPIC,
        },
    )
    entry.add_to_hass(hass)

    with (
        patch("custom_components.orcon_mvs15.MQTT", FakeMQTT),
        patch("custom_components.orcon_mvs15.RamsesESP", FakeRamses),
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    assert entry.state is ConfigEntryState.LOADED
    runtime = entry.runtime_data
    assert runtime.config.fan_id == FAN_ID
    assert runtime.config.gateway_id == GATEWAY_ID
    assert runtime.ramses_esp.kwargs["fan_id"] == RamsesID(FAN_ID)
    assert runtime.ramses_esp.kwargs["config_entry_id"] == entry.entry_id
    assert set(runtime.ramses_esp.handlers) == {
        "042F",
        "10E0",
        "1298",
        "12A0",
        "31D9",
        "31E0",
    }
    assert runtime.ramses_esp.started
    assert FakeMQTT.last_instance is not None
    connection_callback = FakeMQTT.last_instance.connection_callback
    assert connection_callback is not None
    connection_callback(False)
    assert runtime.fan_coordinator.last_update_success is False
    assert runtime.co2_coordinator.last_update_success is False
    assert runtime.rem_coordinator.last_update_success is False
    connection_callback(True)
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
    assert runtime.ramses_esp.cleaned
