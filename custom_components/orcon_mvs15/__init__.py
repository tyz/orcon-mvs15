from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform, EVENT_HOMEASSISTANT_STARTED
from homeassistant.core import HomeAssistant, CoreState
from homeassistant.exceptions import ConfigEntryNotReady, PlatformNotReady
from homeassistant.helpers.device_registry import async_get as get_dev_reg

from .models import OrconMVS15RuntimeData, OrconMVS15Config
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
    hass: HomeAssistant, entry: ConfigEntry, discover_key: str, config_key: str
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
        # TODO?
        # dev_reg = get_dev_reg(hass)
        # dev_reg.async_get_or_create(
        #    config_entry_id=entry.entry_id,
        #    identifiers={(DOMAIN, ramses_id)},
        #    manufacturer="TODO",
        #    model="TODO",
        #    name=f"TODO ({ramses_id})",
        # )
        if unsub:
            unsub()

    unsub = coordinator.async_add_listener(_device_discovered)
    return coordinator


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = entry.data

    entry.runtime_data = OrconMVS15RuntimeData()

    entry.runtime_data.config = OrconMVS15Config.from_data(entry.data)

    entry.runtime_data.fan_coordinator = await _setup_coordinator(
        hass, entry, "discovered_fan_id", CONF_FAN_ID
    )
    entry.runtime_data.co2_coordinator = await _setup_coordinator(
        hass, entry, "discovered_co2_id", CONF_CO2_ID
    )
    entry.runtime_data.rem_coordinator = await _setup_coordinator(
        hass, entry, "discovered_rem_id", CONF_REMOTE_ID
    )

    try:
        mqtt = MQTT(
            hass,
            base_topic=entry.runtime_data.config.mqtt_topic,
            gateway_id=entry.runtime_data.config.gateway_id,
        )
        await mqtt.init()
    except Exception as e:
        raise PlatformNotReady(f"MQTT: {e}")

    entry.runtime_data.cleanup.append(mqtt.cleanup)

    if not entry.runtime_data.config.gateway_id:
        _LOGGER.debug(f"Storing discovered gateway ({mqtt.gateway_id}) in config")
        new_data = {**entry.data, CONF_GATEWAY_ID: mqtt.gateway_id}
        hass.config_entries.async_update_entry(entry, data=new_data)
        entry.runtime_data.config.gateway_id = mqtt.gateway_id

    dev_reg = get_dev_reg(hass)
    dev_reg.async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={(DOMAIN, entry.runtime_data.config.gateway_id)},
        manufacturer="Indalo-Tech",
        model="RAMSES_ESP",
        name=f"Indalo-Tech RAMSES_ESP ({entry.runtime_data.config.gateway_id})",
    )

    try:
        ramses_esp = RamsesESP(
            hass=hass,
            mqtt=mqtt,
            gateway_id=entry.runtime_data.config.gateway_id,
            remote_id=entry.runtime_data.config.remote_id,
            fan_id=entry.runtime_data.config.fan_id,
            co2_id=entry.runtime_data.config.co2_id,
        )
    except ConfigEntryNotReady:
        raise
    except Exception as e:
        raise PlatformNotReady(f"RamsesESP: {e}")

    entry.runtime_data.ramses_esp = ramses_esp

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


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    _LOGGER.debug("Unloading")
    while entry.runtime_data.cleanup:
        entry.runtime_data.cleanup.pop()()
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
