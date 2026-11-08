"""Tests for the gateway firmware update entity."""

from __future__ import annotations

from unittest.mock import AsyncMock, Mock

from homeassistant.components.update import UpdateDeviceClass, UpdateEntityFeature
from homeassistant.core import HomeAssistant

from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.orcon_mvs15.const import (
    CONF_MQTT_TOPIC,
    DOMAIN,
    TRANSPORT_MQTT,
    TRANSPORT_USB,
)
from custom_components.orcon_mvs15.coordinator import (
    OrconMVS15DataUpdateCoordinator,
)
from custom_components.orcon_mvs15.models import OrconMVS15Config
from custom_components.orcon_mvs15.ramses.protocol import RamsesID
from custom_components.orcon_mvs15.update import GatewayFirmwareUpdate

GATEWAY_ID = "18:149960"
MQTT_TOPIC = "RAMSES/GATEWAY"


def make_coordinator(
    hass: HomeAssistant, data: dict[str, object] | None = None
) -> OrconMVS15DataUpdateCoordinator:
    """Build a push coordinator for the gateway."""
    entry = MockConfigEntry(domain=DOMAIN, data={CONF_MQTT_TOPIC: MQTT_TOPIC})
    entry.add_to_hass(hass)
    coordinator = OrconMVS15DataUpdateCoordinator(hass, entry)
    coordinator.async_set_updated_data(data or {})
    return coordinator


def make_entity(
    hass: HomeAssistant,
    *,
    transport: str = TRANSPORT_MQTT,
    data: dict[str, object] | None = None,
    controller: Mock | None = None,
) -> GatewayFirmwareUpdate:
    """Build the firmware entity without adding it to a platform."""
    return GatewayFirmwareUpdate(
        config=OrconMVS15Config(
            gateway_id=RamsesID(GATEWAY_ID),
            mqtt_topic=MQTT_TOPIC,
            transport=transport,
        ),
        coordinator=make_coordinator(hass, data),
        controller=controller or Mock(),
    )


async def test_update_reports_the_gateway_versions(hass: HomeAssistant) -> None:
    """The installed and newest versions come from the gateway topics."""
    entity = make_entity(
        hass,
        data={
            "firmware_version": "0.5.3",
            "latest_firmware_version": "0.6.0",
        },
    )

    assert entity.installed_version == "0.5.3"
    assert entity.latest_version == "0.6.0"
    assert entity.available is True
    assert entity.device_class is UpdateDeviceClass.FIRMWARE
    assert entity.translation_key == "firmware"
    assert entity.has_entity_name is True


async def test_update_is_unknown_until_the_gateway_reports(
    hass: HomeAssistant,
) -> None:
    """A missing version is unknown, not an optimistic 'up to date'."""
    entity = make_entity(hass)

    assert entity.installed_version is None
    assert entity.latest_version is None
    assert entity.state is None


async def test_installing_is_offered_over_mqtt_only(hass: HomeAssistant) -> None:
    """USB firmware installation is not offered yet, so it stays read-only."""
    mqtt = make_entity(hass, transport=TRANSPORT_MQTT)
    usb = make_entity(hass, transport=TRANSPORT_USB)

    assert mqtt.supported_features == (
        UpdateEntityFeature.INSTALL | UpdateEntityFeature.SPECIFIC_VERSION
    )
    assert usb.supported_features == UpdateEntityFeature(0)
    assert usb.installed_version is None


async def test_update_belongs_to_the_gateway_device(hass: HomeAssistant) -> None:
    """The firmware entity lives on the gateway, next to its version."""
    entity = make_entity(hass)

    assert entity.unique_id == f"orcon_mvs15_gateway_firmware_{GATEWAY_ID}"
    assert entity.device_info["identifiers"] == {(DOMAIN, RamsesID(GATEWAY_ID))}
    assert entity.device_info["model"] == "RAMSES_ESP"


async def test_install_forwards_the_version_to_the_controller(
    hass: HomeAssistant,
) -> None:
    """Home Assistant's install version reaches the controller unchanged."""
    controller = Mock()
    controller.async_install_firmware = AsyncMock()
    entity = make_entity(hass, controller=controller)

    await entity.async_install("0.6.0", False)

    controller.async_install_firmware.assert_awaited_once_with("0.6.0")


async def test_update_follows_the_gateway_availability(
    hass: HomeAssistant,
) -> None:
    """A lost gateway makes the firmware entity unavailable."""
    entity = make_entity(hass, data={"firmware_version": "0.5.3"})

    entity.coordinator.async_set_available(False)

    assert entity.available is False
