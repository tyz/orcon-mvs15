"""Tests for the config flow."""

from __future__ import annotations

from unittest.mock import patch

from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType

from pytest_homeassistant_custom_component.common import MockConfigEntry

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


async def test_reconfigure_updates_the_connection_settings(
    hass: HomeAssistant,
) -> None:
    """The remote ID and MQTT topic can be corrected after setup."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            CONF_REMOTE_ID: "29:163058",
            CONF_MQTT_TOPIC: "RAMSES/GATEWAY",
        },
    )
    entry.add_to_hass(hass)
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={
            "source": config_entries.SOURCE_RECONFIGURE,
            "entry_id": entry.entry_id,
        },
    )

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "reconfigure"

    with patch.object(hass.config_entries, "async_schedule_reload") as schedule:
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            user_input={
                CONF_REMOTE_ID: "29:111111",
                CONF_MQTT_TOPIC: "RAMSES/NEW",
            },
        )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
    assert entry.data[CONF_REMOTE_ID] == "29:111111"
    assert entry.data[CONF_MQTT_TOPIC] == "RAMSES/NEW"
    schedule.assert_called_once_with(entry.entry_id)
