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
    DEFAULT_MQTT_TOPIC,
    DEFAULT_PACKET_LOG,
    DEFAULT_REMOTE_ID,
)


def _topic_error(topic: str) -> str | None:
    """Return the translation key for a base topic that cannot be used."""
    if not topic.strip():
        return "mqtt_topic_required"
    if topic != topic.strip():
        return "mqtt_topic_whitespace"
    if "+" in topic or "#" in topic:
        return "mqtt_topic_wildcard"
    return None


def _connection_schema(remote_id: str, mqtt_topic: str) -> Schema:
    """Build the connection form with defaults for the entered values."""
    return Schema(
        {
            Required(CONF_REMOTE_ID, default=remote_id): str,
            Required(CONF_MQTT_TOPIC, default=mqtt_topic): str,
        }
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
            topic = user_input[CONF_MQTT_TOPIC]
            if error := _topic_error(topic):
                return self.async_show_form(
                    step_id="user",
                    data_schema=_connection_schema(user_input[CONF_REMOTE_ID], topic),
                    errors={CONF_MQTT_TOPIC: error},
                )
            self._async_abort_entries_match({CONF_MQTT_TOPIC: topic})
            self._user_input = user_input
            return await self.async_step_fan_discovery()

        return self.async_show_form(
            step_id="user",
            data_schema=_connection_schema(DEFAULT_REMOTE_ID, DEFAULT_MQTT_TOPIC),
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
            topic = user_input[CONF_MQTT_TOPIC]
            if error := _topic_error(topic):
                return self.async_show_form(
                    step_id="reconfigure",
                    data_schema=_connection_schema(user_input[CONF_REMOTE_ID], topic),
                    errors={CONF_MQTT_TOPIC: error},
                )
            self._async_abort_entries_match({CONF_MQTT_TOPIC: topic})
            return self.async_update_reload_and_abort(entry, data_updates=user_input)

        return self.async_show_form(
            step_id="reconfigure",
            data_schema=_connection_schema(
                entry.data.get(CONF_REMOTE_ID, DEFAULT_REMOTE_ID),
                entry.data.get(CONF_MQTT_TOPIC, DEFAULT_MQTT_TOPIC),
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
