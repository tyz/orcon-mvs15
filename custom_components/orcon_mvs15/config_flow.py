from __future__ import annotations

from probatio import Required, Schema

from homeassistant.config_entries import (
    SOURCE_RECONFIGURE,
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlowWithReload,
)
from homeassistant.core import callback
from homeassistant.data_entry_flow import AbortFlow
from homeassistant.helpers.selector import BooleanSelector, SerialPortSelector

from secrets import randbelow
from typing import Any

from .const import (
    CONF_GATEWAY_ID,
    CONF_MQTT_TOPIC,
    CONF_PACKET_LOG,
    CONF_REMOTE_FAKE,
    CONF_REMOTE_ID,
    CONF_TRANSPORT,
    CONF_USB_PORT,
    DEFAULT_MQTT_TOPIC,
    DEFAULT_PACKET_LOG,
    DEFAULT_REMOTE_ID,
    DOMAIN,
    STEP_MQTT,
    STEP_USB,
    TRANSPORT_MQTT,
    TRANSPORT_USB,
)
from .ramses.protocol import RamsesID
from .ramses.transport.ramses_esp.serial import gateway_id_from_serial
from .serial_backend import async_serial_number


def _random_remote_id() -> str:
    """Return a Ramses ID that is unlikely to belong to another remote."""
    return f"29:{randbelow(1_000_000):06d}"


def _topic_error(topic: str) -> str | None:
    """Return the translation key for a base topic that cannot be used."""
    if not topic.strip():
        return "mqtt_topic_required"
    if topic != topic.strip():
        return "mqtt_topic_whitespace"
    if "+" in topic or "#" in topic:
        return "mqtt_topic_wildcard"
    return None


def _remote_id(current: dict[str, Any], user_input: dict[str, Any]) -> str:
    """Return the remote ID to store, generating one for a fake remote."""
    if not user_input[CONF_REMOTE_FAKE]:
        return str(user_input[CONF_REMOTE_ID])
    if current.get(CONF_REMOTE_FAKE) and current.get(CONF_REMOTE_ID):
        return str(current[CONF_REMOTE_ID])
    return _random_remote_id()


def _remote_schema(remote_id: str, fake_remote: bool) -> dict[Any, Any]:
    """Return the remote fields shared by both connection forms."""
    return {
        Required(CONF_REMOTE_FAKE, default=fake_remote): BooleanSelector(),
        Required(CONF_REMOTE_ID, default=remote_id): str,
    }


def _mqtt_schema(remote_id: str, fake_remote: bool, mqtt_topic: str) -> Schema:
    """Build the MQTT connection form with defaults for the entered values."""
    return Schema(
        {
            **_remote_schema(remote_id, fake_remote),
            Required(CONF_MQTT_TOPIC, default=mqtt_topic): str,
        }
    )


def _usb_schema(remote_id: str, fake_remote: bool, usb_port: str) -> Schema:
    """Build the USB connection form with the current port preselected."""
    return Schema(
        {
            **_remote_schema(remote_id, fake_remote),
            Required(CONF_USB_PORT, default=usb_port): SerialPortSelector(),
        }
    )


class OrconConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1

    def __init__(self) -> None:
        self._connection: dict[str, Any] = {}

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OrconOptionsFlow:
        """Return the options flow for the packet log."""
        return OrconOptionsFlow()

    def _current_data(self) -> dict[str, Any]:
        """Return the entry data when reconfiguring, or an empty mapping."""
        if self.source != SOURCE_RECONFIGURE:
            return {}
        return dict(self._get_reconfigure_entry().data)

    def _is_reconfigure(self) -> bool:
        return self.source == SOURCE_RECONFIGURE

    def _async_abort_duplicate(self, key: str, value: str, transport: str) -> None:
        """Abort when an entry of the same transport already uses this value.

        An entry keeps the settings of the transport it was switched away from,
        so the key alone is not unique. Entries created before the transport
        menu have no transport key and are MQTT entries.
        """
        for entry in self._async_current_entries(include_ignore=False):
            if entry.entry_id == self.context.get("entry_id"):
                continue
            if entry.data.get(key) != value:
                continue
            if entry.data.get(CONF_TRANSPORT, TRANSPORT_MQTT) == transport:
                raise AbortFlow("already_configured")

    async def _async_finish(self, data: dict[str, Any]) -> ConfigFlowResult:
        """Reconfigure the entry, or remember the connection for discovery."""
        if self._is_reconfigure():
            return self.async_update_reload_and_abort(
                self._get_reconfigure_entry(), data_updates=data
            )
        self._connection = data
        return await self.async_step_fan_discovery()

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        return self.async_show_menu(
            step_id="user",
            menu_options=[STEP_MQTT, STEP_USB],
        )

    async def async_step_mqtt_connection(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        current = self._current_data()
        errors: dict[str, str] = {}
        if user_input is not None:
            topic = user_input[CONF_MQTT_TOPIC]
            if error := _topic_error(topic):
                errors[CONF_MQTT_TOPIC] = error
            else:
                self._async_abort_duplicate(CONF_MQTT_TOPIC, topic, TRANSPORT_MQTT)
                data: dict[str, Any] = {
                    CONF_REMOTE_FAKE: user_input[CONF_REMOTE_FAKE],
                    CONF_REMOTE_ID: _remote_id(current, user_input),
                    CONF_MQTT_TOPIC: topic,
                    CONF_TRANSPORT: TRANSPORT_MQTT,
                }
                # The USB gateway id is derived from its MAC and is not the
                # MQTT gateway; let setup discover the new one.
                if current.get(CONF_TRANSPORT) == TRANSPORT_USB:
                    data[CONF_GATEWAY_ID] = ""
                return await self._async_finish(data)

        return self.async_show_form(
            step_id=STEP_MQTT,
            data_schema=_mqtt_schema(
                current.get(CONF_REMOTE_ID, DEFAULT_REMOTE_ID),
                current.get(CONF_REMOTE_FAKE, False),
                current.get(CONF_MQTT_TOPIC, DEFAULT_MQTT_TOPIC),
            ),
            errors=errors,
        )

    async def async_step_usb_connection(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        current = self._current_data()
        errors: dict[str, str] = {}
        if user_input is not None:
            port = user_input[CONF_USB_PORT].strip()
            if not port:
                errors[CONF_USB_PORT] = "usb_port_required"
            else:
                self._async_abort_duplicate(CONF_USB_PORT, port, TRANSPORT_USB)
                gateway_id = await self._async_usb_gateway_id(port)
                if not gateway_id and current.get(CONF_TRANSPORT) == TRANSPORT_USB:
                    # A transient lookup failure must not lose a gateway id
                    # this entry already proved.
                    gateway_id = RamsesID(current.get(CONF_GATEWAY_ID))
                if not gateway_id:
                    errors["base"] = "gateway_id_unavailable"
                else:
                    return await self._async_finish(
                        {
                            CONF_REMOTE_FAKE: user_input[CONF_REMOTE_FAKE],
                            CONF_REMOTE_ID: _remote_id(current, user_input),
                            CONF_TRANSPORT: TRANSPORT_USB,
                            CONF_USB_PORT: port,
                            CONF_GATEWAY_ID: gateway_id,
                        }
                    )

        return self.async_show_form(
            step_id=STEP_USB,
            data_schema=_usb_schema(
                current.get(CONF_REMOTE_ID, DEFAULT_REMOTE_ID),
                current.get(CONF_REMOTE_FAKE, False),
                current.get(CONF_USB_PORT, ""),
            ),
            errors=errors,
        )

    async def _async_usb_gateway_id(self, port: str) -> RamsesID:
        """Derive the gateway id from the port's USB serial number."""
        try:
            serial_number = await async_serial_number(port)
        except Exception:
            # A missing udev or an unreadable port is a form error, not a
            # broken flow.
            return RamsesID()
        return gateway_id_from_serial(serial_number)

    async def async_step_fan_discovery(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(
                title="Orcon MVS-15",
                data=self._connection,
            )

        return self.async_show_form(
            step_id="fan_discovery",
            description_placeholders={},
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        return self.async_show_menu(
            step_id="reconfigure",
            menu_options=[STEP_MQTT, STEP_USB],
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
