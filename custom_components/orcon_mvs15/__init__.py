import logging

from datetime import timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady, PlatformNotReady
from homeassistant.helpers.device_registry import async_get as get_dev_reg

from .typing import OrconMVS15RuntimeData
from .coordinator import (
    OrconMVS15PushDataUpdateCoordinator,
    OrconMVS15PullDataUpdateCoordinator,
)
from .mqtt import MQTT
from .ramses_esp import RamsesESP
from .const import (
    DOMAIN,
    CONF_GATEWAY_ID,
    CONF_REMOTE_ID,
    CONF_FAN_ID,
    CONF_CO2_ID,
    CONF_MQTT_TOPIC,
)

PLATFORMS = [Platform.FAN, Platform.SENSOR]

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = entry.data

    try:
        mqtt = MQTT(
            hass,
            base_topic=entry.data.get(CONF_MQTT_TOPIC),
            gateway_id=entry.data.get(CONF_GATEWAY_ID),
        )
        await mqtt.init()
    except Exception as e:
        raise PlatformNotReady(f"MQTT: {e}")

    if not entry.data.get(CONF_GATEWAY_ID):
        _LOGGER.debug(f"Storing discovered gateway ({mqtt.gateway_id}) in config")
        new_data = {**entry.data, CONF_GATEWAY_ID: mqtt.gateway_id}
        hass.config_entries.async_update_entry(entry, data=new_data)

    dev_reg = get_dev_reg(hass)
    dev_reg.async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={(DOMAIN, mqtt.gateway_id)},
        manufacturer="Indalo-Tech",
        model="RAMSES_ESP",
        name=f"Indalo-Tech RAMSES_ESP ({mqtt.gateway_id})",
    )

    try:
        ramses_esp = RamsesESP(
            hass=hass,
            mqtt=mqtt,
            gateway_id=entry.data.get(CONF_GATEWAY_ID),
            remote_id=entry.data.get(CONF_REMOTE_ID),
            fan_id=entry.data.get(CONF_FAN_ID),
            co2_id=entry.data.get(CONF_CO2_ID),
        )
    except ConfigEntryNotReady:
        raise
    except Exception as e:
        raise PlatformNotReady(f"RamsesESP: {e}")

    pull_coordinator = OrconMVS15PullDataUpdateCoordinator(
        hass,
        entry,
        update_interval=timedelta(minutes=5),
        callback_func=ramses_esp.req_humidity,
    )
    await pull_coordinator.async_config_entry_first_refresh()

    push_coordinator = OrconMVS15PushDataUpdateCoordinator(
        hass,
        entry,
    )
    await push_coordinator.async_config_entry_first_refresh()

    entry.runtime_data = OrconMVS15RuntimeData(
        pull_coordinator=pull_coordinator,
        push_coordinator=push_coordinator,
        ramses_esp=ramses_esp,
    )

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
