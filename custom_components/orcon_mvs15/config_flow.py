import voluptuous as vol
from homeassistant import config_entries
from .const import (
    DOMAIN,
    CONF_REMOTE_ID,
    CONF_FAN_ID,
    CONF_MQTT_TOPIC,
)


class OrconConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(self, user_input=None):
        if user_input is not None:
            return self.async_create_entry(title="Orcon MVS-15", data=user_input)

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_REMOTE_ID, default="29:163058"): str,
                    vol.Required(CONF_FAN_ID, default="29:224547"): str,
                    vol.Required(CONF_MQTT_TOPIC, default="RAMSES/GATEWAY"): str,
                }
            ),
        )
