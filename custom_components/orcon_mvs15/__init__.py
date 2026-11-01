from __future__ import annotations

import logging

from homeassistant.const import Platform, EVENT_HOMEASSISTANT_STARTED
from homeassistant.core import HomeAssistant, CoreState
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers.device_registry import DeviceEntry

from .device import async_get_or_create_gateway
from .models import (
    OrconMVS15ConfigEntry,
    OrconMVS15Config,
    OrconMVS15RuntimeData,
)
from .coordinator import OrconMVS15DataUpdateCoordinator
from .mqtt import MQTT
from .ramses_esp import RamsesESP
from .handlers import DataHandlers
from .const import (
    CONF_CO2_ID,
    CONF_FAN_ID,
    CONF_GATEWAY_ID,
    CONF_REMOTE_ID,
    DOMAIN,
)

PLATFORMS = [Platform.FAN, Platform.SENSOR, Platform.BINARY_SENSOR]

_LOGGER = logging.getLogger(__name__)


async def _setup_coordinator(
    hass: HomeAssistant,
    entry: OrconMVS15ConfigEntry,
    discover_key: str,
    config_key: str,
) -> OrconMVS15DataUpdateCoordinator:
    coordinator = OrconMVS15DataUpdateCoordinator(hass, entry)
    await coordinator.async_config_entry_first_refresh()
    unsub = None

    def _device_discovered() -> None:
        if entry.data.get(config_key):
            _LOGGER.debug(f"Discovered {config_key} already in config")
            if unsub:
                unsub()
            return
        if (ramses_id := coordinator.data.get(discover_key)) is None:
            _LOGGER.debug(
                f"_device_discovered: Got {coordinator.data} without {discover_key}"
            )
            return
        _LOGGER.debug(f"Storing discovered {config_key} ({ramses_id}) in config")
        new_data = {**entry.data, config_key: ramses_id}
        hass.config_entries.async_update_entry(entry, data=new_data)
        if unsub:
            unsub()

    unsub = coordinator.async_add_listener(_device_discovered)
    return coordinator


async def async_setup_entry(hass: HomeAssistant, entry: OrconMVS15ConfigEntry) -> bool:
    config = OrconMVS15Config.from_data(entry.data)

    fan_coordinator = await _setup_coordinator(
        hass, entry, "discovered_fan_id", CONF_FAN_ID
    )
    co2_coordinator = await _setup_coordinator(
        hass, entry, "discovered_co2_id", CONF_CO2_ID
    )
    rem_coordinator = await _setup_coordinator(
        hass, entry, "discovered_rem_id", CONF_REMOTE_ID
    )

    def _handle_connection(connected: bool) -> None:
        """Mark every coordinator unavailable while MQTT is down."""
        for coordinator in (fan_coordinator, co2_coordinator, rem_coordinator):
            coordinator.async_set_available(connected)

    try:
        mqtt = MQTT(
            hass,
            base_topic=config.mqtt_topic,
            gateway_id=config.gateway_id,
            connection_callback=_handle_connection,
        )
        await mqtt.init()
    except Exception as e:
        raise ConfigEntryNotReady(
            translation_domain=DOMAIN,
            translation_key="mqtt_setup_failed",
            translation_placeholders={"error": str(e)},
        ) from e

    if not config.gateway_id:
        _LOGGER.debug(f"Storing discovered gateway ({mqtt.gateway_id}) in config")
        new_data = {**entry.data, CONF_GATEWAY_ID: mqtt.gateway_id}
        hass.config_entries.async_update_entry(entry, data=new_data)
        config.gateway_id = mqtt.gateway_id

    dev_reg = async_get_or_create_gateway(hass, entry.entry_id, config.gateway_id)
    _LOGGER.debug("Gateway device is %s", dev_reg.id)

    try:
        ramses_esp = RamsesESP(
            hass=hass,
            mqtt=mqtt,
            gateway_id=config.gateway_id,
            remote_id=config.remote_id,
            fan_id=config.fan_id,
            co2_id=config.co2_id,
            config_entry_id=entry.entry_id,
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
        rem_coordinator=rem_coordinator,
        ramses_esp=ramses_esp,
        cleanup=[mqtt.cleanup, ramses_esp.cleanup],
    )

    dh = DataHandlers(hass, entry)
    for code, func in dh.pointers.items():
        ramses_esp.add_handler(code, func)

    if hass.state == CoreState.running:
        _LOGGER.info("Orcon MVS-15 integration has been setup")
        hass.async_create_task(ramses_esp.setup())
    else:
        _LOGGER.info("Orcon MVS-15 integration has been loaded after restart")
        hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STARTED, ramses_esp.setup)

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: OrconMVS15ConfigEntry) -> bool:
    _LOGGER.debug("Unloading")
    while entry.runtime_data.cleanup:
        entry.runtime_data.cleanup.pop()()
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
