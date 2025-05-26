import logging
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import async_get as get_dev_reg
from .const import DOMAIN, CONF_GATEWAY_ID

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = entry.data
    hass.data[DOMAIN]["co2_sensor"] = None
    hass.data[DOMAIN]["humidity_sensor"] = None

    gateway_id = hass.data[DOMAIN][entry.entry_id].get(CONF_GATEWAY_ID)
    dev_reg = get_dev_reg(hass)
    dev_reg.async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={(DOMAIN, gateway_id)},
        manufacturer="Indalo-Tech",
        model="RAMSES_ESP",
        name=f"Indalo-Tech RAMSES_ESP ({gateway_id})",
    )

    await hass.config_entries.async_forward_entry_setups(entry, ["fan", "sensor"])
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    unload_ok = await hass.config_entries.async_forward_entry_unload(entry, "fan")
    unload_ok &= await hass.config_entries.async_forward_entry_unload(entry, "sensor")
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id)
    return unload_ok
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id)
    return unload_ok
