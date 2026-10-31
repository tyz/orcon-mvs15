"""Tests for the config flow."""

from __future__ import annotations

from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType

from custom_components.orcon_mvs15.const import (
    CONF_MQTT_TOPIC,
    CONF_REMOTE_ID,
    DOMAIN,
)


async def test_user_flow_shows_the_form(hass: HomeAssistant) -> None:
    """The integration is loadable and its config flow is registered."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"


async def test_user_flow_creates_an_entry(hass: HomeAssistant) -> None:
    """The user data is stored after the discovery info step."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        user_input={
            CONF_REMOTE_ID: "29:163058",
            CONF_MQTT_TOPIC: "RAMSES/GATEWAY",
        },
    )

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "discovery_info"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], user_input={}
    )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Orcon MVS-15"
    assert result["data"] == {
        CONF_REMOTE_ID: "29:163058",
        CONF_MQTT_TOPIC: "RAMSES/GATEWAY",
    }
