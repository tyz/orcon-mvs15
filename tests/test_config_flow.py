"""Tests that the Home Assistant harness loads and drives this integration."""

from __future__ import annotations

from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType

from custom_components.orcon_mvs15.const import DOMAIN


async def test_user_flow_shows_the_form(hass: HomeAssistant) -> None:
    """The integration is loadable and its config flow is registered."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"
