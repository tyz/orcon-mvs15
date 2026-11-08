from __future__ import annotations

import asyncio
import logging

from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, CoreState
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers.device_registry import DeviceEntry
from homeassistant.helpers.start import async_at_started

from .controller import OrconMVS15Controller
from .device import (
    async_get_or_create_co2,
    async_get_or_create_fan,
    async_get_or_create_gateway,
)
from .discovery import DiscoveryManager
from .models import (
    OrconMVS15ConfigEntry,
    OrconMVS15Config,
    OrconMVS15RuntimeData,
)
from .coordinator import OrconMVS15DataUpdateCoordinator
from .mqtt import HassMqttBackend
from .ramses.protocol import RamsesID
from .ramses.session import RamsesSession
from .ramses.transport import Transport, TransportNotReady
from .ramses.transport.ramses_esp import RamsesESP
from .ramses.transport.ramses_esp.serial import RamsesESPSerial
from .serial_backend import SerialxBackend
from .const import (
    CONF_GATEWAY_ID,
    CONF_PACKET_LOG,
    DEFAULT_PACKET_LOG,
    DOMAIN,
    TRANSPORT_USB,
)

PLATFORMS = [
    Platform.FAN,
    Platform.SENSOR,
    Platform.BINARY_SENSOR,
    Platform.UPDATE,
    Platform.BUTTON,
]

_LOGGER = logging.getLogger(__name__)


async def _setup_coordinator(
    hass: HomeAssistant, entry: OrconMVS15ConfigEntry
) -> OrconMVS15DataUpdateCoordinator:
    coordinator = OrconMVS15DataUpdateCoordinator(hass, entry)
    await coordinator.async_config_entry_first_refresh()
    return coordinator


async def async_setup_entry(hass: HomeAssistant, entry: OrconMVS15ConfigEntry) -> bool:
    config = OrconMVS15Config.from_data(entry.data)

    fan_coordinator = await _setup_coordinator(hass, entry)
    co2_coordinator = await _setup_coordinator(hass, entry)
    gateway_coordinator = await _setup_coordinator(hass, entry)

    is_usb = config.transport == TRANSPORT_USB
    setup_failure_key = "usb_setup_failed" if is_usb else "mqtt_setup_failed"
    try:
        transport: Transport
        if is_usb:
            transport = RamsesESPSerial(
                SerialxBackend(config.usb_port), gateway_id=config.gateway_id
            )
        else:
            transport = RamsesESP(
                HassMqttBackend(hass),
                base_topic=config.mqtt_topic,
                gateway_id=config.gateway_id,
            )
        await transport.init()
    except Exception as e:
        raise ConfigEntryNotReady(
            translation_domain=DOMAIN,
            translation_key=setup_failure_key,
            translation_placeholders={"error": str(e)},
        ) from e

    if not config.gateway_id:
        _LOGGER.debug(f"Storing discovered gateway ({transport.gateway_id}) in config")
        new_data = {**entry.data, CONF_GATEWAY_ID: transport.gateway_id}
        hass.config_entries.async_update_entry(entry, data=new_data)
        config.gateway_id = transport.gateway_id

    dev_reg = async_get_or_create_gateway(hass, entry.entry_id, config.gateway_id)
    _LOGGER.debug("Gateway device is %s", dev_reg.id)
    if config.fan_id:
        async_get_or_create_fan(hass, entry.entry_id, config.gateway_id, config.fan_id)
    if config.co2_id:
        async_get_or_create_co2(hass, entry.entry_id, config.gateway_id, config.co2_id)

    def _create_device(kind: str, ramses_id: RamsesID) -> None:
        if kind == "fan":
            async_get_or_create_fan(hass, entry.entry_id, config.gateway_id, ramses_id)
        elif kind == "co2":
            async_get_or_create_co2(hass, entry.entry_id, config.gateway_id, ramses_id)

    try:
        discovery = DiscoveryManager(
            hass,
            entry,
            {"fan": config.fan_id, "co2": config.co2_id},
            create_device=_create_device,
        )
        session = RamsesSession(transport)
        controller = OrconMVS15Controller(
            hass,
            config,
            session,
            discovery,
            fan_coordinator,
            co2_coordinator,
            gateway_coordinator,
            entry_id=entry.entry_id,
            packet_log=entry.options.get(CONF_PACKET_LOG, DEFAULT_PACKET_LOG),
            packet_log_path=hass.config.path("packet.log"),
        )
    except ConfigEntryNotReady:
        raise
    except Exception as e:
        raise ConfigEntryNotReady(
            translation_domain=DOMAIN,
            translation_key="session_setup_failed",
            translation_placeholders={"error": str(e)},
        ) from e

    entry.runtime_data = OrconMVS15RuntimeData(
        config=config,
        fan_coordinator=fan_coordinator,
        co2_coordinator=co2_coordinator,
        gateway_coordinator=gateway_coordinator,
        session=session,
        controller=controller,
        discovery=discovery,
        cleanup=[],
    )

    async def _start_session(delay: bool = False) -> None:
        """Start the session, mapping a missing broker to a retry."""
        try:
            if delay:
                # Home Assistant has just started; give MQTT or the stick a
                # moment to come up after the restart.
                await asyncio.sleep(2)
            await controller.start()
        except TransportNotReady as err:
            raise ConfigEntryNotReady(
                translation_domain=DOMAIN,
                translation_key="usb_not_available" if is_usb else "mqtt_not_available",
            ) from err

    if hass.state == CoreState.running:
        _LOGGER.info("Orcon MVS-15 integration has been setup")
        try:
            # Await setup so a broker that is not ready reaches Home Assistant
            # as ConfigEntryNotReady and the entry retries. A detached task
            # would only log the failure and leave the entry loaded without
            # subscriptions.
            await _start_session()
        except Exception as e:
            await controller.stop()
            if isinstance(e, ConfigEntryNotReady):
                raise
            raise ConfigEntryNotReady(
                translation_domain=DOMAIN,
                translation_key="session_setup_failed",
                translation_placeholders={"error": str(e)},
            ) from e
    else:
        _LOGGER.info("Orcon MVS-15 integration has been loaded after restart")

        async def _start_after_restart(_hass: HomeAssistant) -> None:
            """Start the session once Home Assistant is up, retrying on failure."""
            try:
                await _start_session(delay=True)
            except Exception as err:  # no caller left to raise to
                _LOGGER.error("The Orcon MVS-15 session failed to start: %s", err)
                hass.config_entries.async_schedule_reload(entry.entry_id)

        entry.async_on_unload(async_at_started(hass, _start_after_restart))

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: OrconMVS15ConfigEntry) -> bool:
    _LOGGER.debug("Unloading")
    while entry.runtime_data.cleanup:
        entry.runtime_data.cleanup.pop()()
    await entry.runtime_data.controller.stop()
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def async_remove_config_entry_device(
    hass: HomeAssistant,
    config_entry: OrconMVS15ConfigEntry,
    device_entry: DeviceEntry,
) -> bool:
    """Allow removing a device that is no longer part of the installation.

    The gateway is the connection this entry runs on, so it stays until the
    entry itself is removed. A fan or CO2 device is recreated when it still
    sends packets; the integration cannot know that an RF device is gone.

    Args:
        hass: Home Assistant instance.
        config_entry: The entry the device belongs to.
        device_entry: The device the user wants to remove.

    Returns:
        True when the device may be removed.
    """
    gateway_id = config_entry.data.get(CONF_GATEWAY_ID)
    if gateway_id is not None and (DOMAIN, gateway_id) in device_entry.identifiers:
        _LOGGER.info("Keeping the gateway device %s while the entry exists", gateway_id)
        return False
    return True
