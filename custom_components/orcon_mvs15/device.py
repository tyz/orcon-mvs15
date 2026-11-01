"""Device registry helpers for the Orcon MVS-15 integration.

Entity classes describe their device through this module instead of building
DeviceInfo themselves, so identifiers, names and the gateway relationship stay
consistent across platforms. Registry writes also live here, which keeps the
protocol session free of Home Assistant registry concerns.
"""

from __future__ import annotations

import logging

from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import (
    DeviceEntry,
    DeviceInfo,
    async_get as get_dev_reg,
)

from .const import DOMAIN
from .ramses_packet import RamsesID

_LOGGER = logging.getLogger(__name__)


def _via_device_id(
    hass: HomeAssistant, config_entry_id: str, gateway_id: RamsesID
) -> str | None:
    """Return the registry id of the gateway, if it exists."""
    device = get_dev_reg(hass).async_get_device_by_identifier(
        (DOMAIN, gateway_id), config_entry_id
    )
    return None if device is None else device.id


def gateway_device_info(gateway_id: RamsesID) -> DeviceInfo:
    """Return the device info for the Ramses ESP gateway."""
    return DeviceInfo(
        identifiers={(DOMAIN, gateway_id)},
        manufacturer="Indalo-Tech",
        model="RAMSES_ESP",
        name=f"Indalo-Tech RAMSES_ESP ({gateway_id})",
    )


def _with_via_device(info: DeviceInfo, via_device_id: str | None) -> DeviceInfo:
    """Add the gateway link when the gateway device exists."""
    if via_device_id is not None:
        info["via_device_id"] = via_device_id
    return info


def fan_device_info(
    hass: HomeAssistant,
    config_entry_id: str,
    gateway_id: RamsesID,
    fan_id: RamsesID,
) -> DeviceInfo:
    """Return the device info for the fan, connected through the gateway."""
    return _with_via_device(
        DeviceInfo(
            identifiers={(DOMAIN, fan_id)},
            manufacturer="Orcon",
            model="MVS-15",
            name=f"Orcon MVS-15 fan ({fan_id})",
        ),
        _via_device_id(hass, config_entry_id, gateway_id),
    )


def co2_device_info(
    hass: HomeAssistant,
    config_entry_id: str,
    gateway_id: RamsesID,
    co2_id: RamsesID,
) -> DeviceInfo:
    """Return the device info for the wired CO₂ sensor, connected through the gateway."""
    return _with_via_device(
        DeviceInfo(
            identifiers={(DOMAIN, co2_id)},
            manufacturer="Orcon",
            model="CO2 ruimtesensor 15RF",
            name=f"Orcon CO2 room sensor ({co2_id})",
        ),
        _via_device_id(hass, config_entry_id, gateway_id),
    )


def attached_device_info(ramses_id: RamsesID) -> DeviceInfo:
    """Attach an entity to an existing device without changing it."""
    return DeviceInfo(identifiers={(DOMAIN, ramses_id)})


def _async_get_or_create_device(
    hass: HomeAssistant, config_entry_id: str, info: DeviceInfo
) -> DeviceEntry:
    """Create a device from its DeviceInfo, or update the existing one."""
    return get_dev_reg(hass).async_get_or_create(
        config_entry_id=config_entry_id,
        identifiers=info["identifiers"],
        manufacturer=info.get("manufacturer"),
        model=info.get("model"),
        name=info.get("name"),
        via_device_id=info.get("via_device_id"),
    )


def async_get_or_create_gateway(
    hass: HomeAssistant, config_entry_id: str, gateway_id: RamsesID
) -> DeviceEntry:
    """Create the gateway device or return the existing one."""
    return _async_get_or_create_device(
        hass, config_entry_id, gateway_device_info(gateway_id)
    )


def async_get_or_create_fan(
    hass: HomeAssistant,
    config_entry_id: str,
    gateway_id: RamsesID,
    fan_id: RamsesID,
) -> DeviceEntry:
    """Create the fan device or return the existing one."""
    return _async_get_or_create_device(
        hass,
        config_entry_id,
        fan_device_info(hass, config_entry_id, gateway_id, fan_id),
    )


def async_get_or_create_co2(
    hass: HomeAssistant,
    config_entry_id: str,
    gateway_id: RamsesID,
    co2_id: RamsesID,
) -> DeviceEntry:
    """Create the CO2 room sensor device or return the existing one."""
    return _async_get_or_create_device(
        hass,
        config_entry_id,
        co2_device_info(hass, config_entry_id, gateway_id, co2_id),
    )


def update_gateway_version(
    hass: HomeAssistant,
    config_entry_id: str,
    gateway_id: RamsesID,
    sw_version: str,
) -> None:
    """Store the firmware version reported on the gateway version topic."""
    dev_reg = get_dev_reg(hass)
    device = dev_reg.async_get_device_by_identifier(
        (DOMAIN, gateway_id), config_entry_id
    )
    if device is None:
        _LOGGER.debug("Gateway device %s is not registered", gateway_id)
        return
    dev_reg.async_update_device(device_id=device.id, sw_version=sw_version)
    _LOGGER.info("Updated gateway firmware version to %s", sw_version)


def update_device_info(
    hass: HomeAssistant,
    config_entry_id: str,
    ramses_id: RamsesID,
    software_ver_id: str,
    description: str,
) -> bool:
    """Store the decoded 10E0 version and model on the device.

    Returns:
        True when the device was registered and updated.
    """
    dev_reg = get_dev_reg(hass)
    device = dev_reg.async_get_device_by_identifier(
        (DOMAIN, ramses_id), config_entry_id
    )
    if device is None:
        _LOGGER.debug("Device %s is not registered", ramses_id)
        return False
    sw_version = str(int(software_ver_id, 16))
    dev_reg.async_update_device(
        device_id=device.id, sw_version=sw_version, model_id=description
    )
    return True
