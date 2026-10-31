"""Tests for config entry setup and unload."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant

from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.orcon_mvs15.const import (
    CONF_MQTT_TOPIC,
    CONF_REMOTE_ID,
    DOMAIN,
)
from custom_components.orcon_mvs15.mqtt import MQTTException

REMOTE_ID = "29:163058"
MQTT_TOPIC = "RAMSES/GATEWAY"


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
