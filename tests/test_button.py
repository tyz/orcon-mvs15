"""Tests for the gateway reboot button."""

from __future__ import annotations

from unittest.mock import AsyncMock, Mock

from homeassistant.components.button import ButtonDeviceClass
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.orcon_mvs15.button import (
    GatewayRebootButton,
    PairRemoteButton,
)
from custom_components.orcon_mvs15.const import CONF_MQTT_TOPIC, DOMAIN
from custom_components.orcon_mvs15.coordinator import (
    OrconMVS15DataUpdateCoordinator,
)
from custom_components.orcon_mvs15.models import OrconMVS15Config
from custom_components.orcon_mvs15.ramses.protocol import RamsesID

GATEWAY_ID = "18:149960"
FAN_ID = "29:224547"
MQTT_TOPIC = "RAMSES/GATEWAY"


def make_entity(
    hass: HomeAssistant, controller: Mock | None = None
) -> GatewayRebootButton:
    """Build the reboot button without adding it to a platform."""
    entry = MockConfigEntry(domain=DOMAIN, data={CONF_MQTT_TOPIC: MQTT_TOPIC})
    entry.add_to_hass(hass)
    coordinator = OrconMVS15DataUpdateCoordinator(hass, entry)
    coordinator.async_set_updated_data({})
    return GatewayRebootButton(
        config=OrconMVS15Config(
            gateway_id=RamsesID(GATEWAY_ID),
            mqtt_topic=MQTT_TOPIC,
        ),
        coordinator=coordinator,
        controller=controller or Mock(),
    )


async def test_the_button_is_a_config_action_on_the_gateway(
    hass: HomeAssistant,
) -> None:
    """A maintenance action stays off the dashboard and names the gateway."""
    entity = make_entity(hass)

    assert entity.unique_id == f"orcon_mvs15_gateway_reboot_{GATEWAY_ID}"
    assert entity.device_class is ButtonDeviceClass.RESTART
    assert entity.entity_category is EntityCategory.CONFIG
    assert entity.translation_key == "reboot"
    assert entity.has_entity_name is True
    assert entity.device_info["identifiers"] == {(DOMAIN, RamsesID(GATEWAY_ID))}
    assert entity.device_info["model"] == "RAMSES_ESP"


async def test_pressing_asks_the_controller_to_reboot(
    hass: HomeAssistant,
) -> None:
    """The entity has no protocol knowledge of its own."""
    controller = Mock()
    controller.async_reboot_gateway = AsyncMock()
    entity = make_entity(hass, controller)

    await entity.async_press()

    controller.async_reboot_gateway.assert_awaited_once_with()


async def test_a_failed_reboot_reaches_the_caller(hass: HomeAssistant) -> None:
    """Home Assistant must show the translated failure, not swallow it."""
    controller = Mock()
    controller.async_reboot_gateway = AsyncMock(
        side_effect=HomeAssistantError(
            translation_domain=DOMAIN, translation_key="reboot_failed"
        )
    )
    entity = make_entity(hass, controller)

    with pytest.raises(HomeAssistantError) as err:
        await entity.async_press()

    assert err.value.translation_key == "reboot_failed"


async def test_the_button_follows_the_gateway_availability(
    hass: HomeAssistant,
) -> None:
    """An unreachable gateway cannot reboot, so the button is unavailable."""
    entity = make_entity(hass)

    entity.coordinator.async_set_available(False)

    assert entity.available is False


def make_pair_entity(
    hass: HomeAssistant, controller: Mock | None = None
) -> PairRemoteButton:
    """Build the pairing button on the fan device."""
    entry = MockConfigEntry(domain=DOMAIN, data={CONF_MQTT_TOPIC: MQTT_TOPIC})
    entry.add_to_hass(hass)
    coordinator = OrconMVS15DataUpdateCoordinator(hass, entry)
    coordinator.async_set_updated_data({})
    return PairRemoteButton(
        hass=hass,
        ramses_id=RamsesID(FAN_ID),
        config=OrconMVS15Config(mqtt_topic=MQTT_TOPIC),
        coordinator=coordinator,
        controller=controller or Mock(),
        discovery_key="fan",
    )


async def test_the_pairing_button_is_a_config_action_on_the_fan(
    hass: HomeAssistant,
) -> None:
    """Pairing is a one-time setup action and belongs with the fan."""
    entity = make_pair_entity(hass)

    assert entity.unique_id == f"orcon_mvs15_pair_remote_{FAN_ID}"
    assert entity.entity_category is EntityCategory.CONFIG
    assert entity.translation_key == "pair_remote"
    assert entity.has_entity_name is True
    assert entity.device_info["identifiers"] == {(DOMAIN, RamsesID(FAN_ID))}


async def test_pressing_the_pairing_button_asks_the_controller(
    hass: HomeAssistant,
) -> None:
    """The entity has no protocol knowledge of its own."""
    controller = Mock()
    controller.async_pair_remote = AsyncMock()
    entity = make_pair_entity(hass, controller)

    await entity.async_press()

    controller.async_pair_remote.assert_awaited_once_with()
