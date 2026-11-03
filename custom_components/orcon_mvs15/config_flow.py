from __future__ import annotations

from probatio import Required, Schema

from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlowWithReload,
)
from homeassistant.core import callback

from typing import Any

from .const import (
    DOMAIN,
    CONF_PACKET_LOG,
    CONF_REMOTE_ID,
    CONF_MQTT_TOPIC,
    DEFAULT_PACKET_LOG,
)


class OrconConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OrconOptionsFlow:
        """Return the options flow for the packet log."""
        return OrconOptionsFlow()

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            self._async_abort_entries_match(
                {CONF_MQTT_TOPIC: user_input[CONF_MQTT_TOPIC]}
            )
            self._user_input = user_input
            return await self.async_step_fan_discovery()

        return self.async_show_form(
            step_id="user",
            data_schema=Schema(
                {
                    Required(CONF_REMOTE_ID, default="29:163058"): str,
                    Required(CONF_MQTT_TOPIC, default="RAMSES/GATEWAY"): str,
                }
            ),
        )

    async def async_step_fan_discovery(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(
                title="Orcon MVS-15",
                data=self._user_input,
            )

        return self.async_show_form(
            step_id="fan_discovery",
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


class OrconOptionsFlow(OptionsFlowWithReload):
    """Options that do not belong in the connection setup."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        return self.async_show_form(
            step_id="init",
            data_schema=Schema(
                {
                    Required(
                        CONF_PACKET_LOG,
                        default=self.config_entry.options.get(
                            CONF_PACKET_LOG, DEFAULT_PACKET_LOG
                        ),
                    ): bool,
                }
            ),
        )
