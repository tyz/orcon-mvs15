"""Home Assistant MQTT adapter for the RAMSES ESP transport."""

from __future__ import annotations

import inspect
import logging

from collections.abc import Callable

from homeassistant.components import mqtt
from homeassistant.components.mqtt import ReceiveMessage
from homeassistant.core import HomeAssistant

from .ramses.transport.base import TransportNotReady
from .ramses.transport.ramses_esp.backend import (
    ConnectionHandler,
    MessageHandler,
    MqttBackendError,
)

_LOGGER = logging.getLogger(__name__)


class HassMqttBackend:
    """Adapt Home Assistant's MQTT client to the transport's backend protocol."""

    def __init__(self, hass: HomeAssistant) -> None:
        self.hass = hass

    async def start(self) -> None:
        """Wait until Home Assistant's MQTT client is usable."""
        if not await mqtt.async_wait_for_mqtt_client(self.hass):
            raise TransportNotReady("MQTT is not available")

    async def stop(self) -> None:
        """The transport owns the subscriptions and unsubscribes them itself."""

    async def subscribe(
        self, topic: str, handler: MessageHandler
    ) -> Callable[[], None]:
        """Subscribe to a topic and normalise the message for the transport."""

        async def _handle_message(msg: ReceiveMessage) -> None:
            result = handler(msg.topic, msg.payload)
            if inspect.isawaitable(result):
                await result

        _LOGGER.debug(f"Subscribed to {topic}")
        return await mqtt.async_subscribe(self.hass, topic, _handle_message)

    async def publish(self, topic: str, payload: str) -> None:
        """Publish one payload, translating client errors."""
        try:
            await mqtt.async_publish(self.hass, topic, payload)
        except Exception as err:
            raise MqttBackendError(f"Failed to publish to {topic}: {err}") from err

    def subscribe_connection(self, handler: ConnectionHandler) -> Callable[[], None]:
        """Subscribe to the MQTT client's connection state."""
        return mqtt.async_subscribe_connection_status(self.hass, handler)

    def is_connected(self) -> bool:
        """Return whether the MQTT client is currently connected."""
        return mqtt.is_connected(self.hass)
