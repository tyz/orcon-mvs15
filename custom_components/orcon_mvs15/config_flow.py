from __future__ import annotations

from probatio import Required, Schema

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult

from typing import Any

from .const import (
    DOMAIN,
    CONF_REMOTE_ID,
    CONF_MQTT_TOPIC,
)


class OrconConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            self._async_abort_entries_match(
                {CONF_MQTT_TOPIC: user_input[CONF_MQTT_TOPIC]}
            )
            self._user_input = user_input
            return await self.async_step_discovery_info()

        return self.async_show_form(
            step_id="user",
            data_schema=Schema(
                {
                    Required(CONF_REMOTE_ID, default="29:163058"): str,
                    Required(CONF_MQTT_TOPIC, default="RAMSES/GATEWAY"): str,
                }
            ),
        )

    async def async_step_discovery_info(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(
                title="Orcon MVS-15",
                data=self._user_input,
            )

        return self.async_show_form(
            step_id="discovery_info",
            description_placeholders={},
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        entry = self._get_reconfigure_entry()
        if user_input is not None:
            self._async_abort_entries_match(
                {CONF_MQTT_TOPIC: user_input[CONF_MQTT_TOPIC]}
            )
            return self.async_update_reload_and_abort(entry, data_updates=user_input)

        return self.async_show_form(
            step_id="reconfigure",
            data_schema=Schema(
                {
                    Required(
                        CONF_REMOTE_ID,
                        default=entry.data.get(CONF_REMOTE_ID, "29:163058"),
                    ): str,
                    Required(
                        CONF_MQTT_TOPIC,
                        default=entry.data.get(CONF_MQTT_TOPIC, "RAMSES/GATEWAY"),
                    ): str,
                }
            ),
        )
