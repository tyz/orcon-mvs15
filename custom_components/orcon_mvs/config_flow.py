import voluptuous as vol
from homeassistant import config_entries
from .const import DOMAIN, CONF_GATEWAY_ID, CONF_REMOTE_ID, CONF_FAN_ID, CONF_CO2_ID, CONF_MQTT_TOPIC


class OrconConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(self, user_input=None):
        if user_input is not None:
            return self.async_create_entry(title="Orcon MVS", data=user_input)

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_GATEWAY_ID): str,
                    vol.Required(CONF_REMOTE_ID): str,
                    vol.Required(CONF_FAN_ID): str,
                    vol.Required(CONF_CO2_ID): str,
                    vol.Required(CONF_MQTT_TOPIC, default="RAMSES/GATEWAY"): str,
                }
            ),
        )
