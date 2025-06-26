from __future__ import annotations

import voluptuous as vol

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult

from typing import Any

from .const import (
    DOMAIN,
    CONF_REMOTE_ID,
    CONF_MQTT_TOPIC,
)


class OrconConfigFlow(ConfigFlow, domain=DOMAIN):  # type: ignore[call-arg]
    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(title="Orcon MVS-15", data=user_input)

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_REMOTE_ID, default="29:163058"): str,
                    vol.Required(CONF_MQTT_TOPIC, default="RAMSES/GATEWAY"): str,
                }
            ),
        )
