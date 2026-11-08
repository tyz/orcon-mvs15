"""Tests for the diagnostics platform."""

from __future__ import annotations

import json
from unittest.mock import Mock

from homeassistant.core import HomeAssistant

from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.orcon_mvs15.const import (
    CONF_FAN_ID,
    CONF_GATEWAY_ID,
    CONF_MQTT_TOPIC,
    CONF_REMOTE_ID,
    DOMAIN,
)
from custom_components.orcon_mvs15.coordinator import (
    CoordinatorData,
    OrconMVS15DataUpdateCoordinator,
)
from custom_components.orcon_mvs15.diagnostics import (
    async_get_config_entry_diagnostics,
)
from custom_components.orcon_mvs15.discovery import DiscoveryManager
from custom_components.orcon_mvs15.models import (
    OrconMVS15Config,
    OrconMVS15RuntimeData,
)
from custom_components.orcon_mvs15.ramses.protocol import (
    RamsesID,
    RamsesPacketDatetime,
)
from custom_components.orcon_mvs15.ramses.session import RamsesSession
from custom_components.orcon_mvs15.ramses.transport.loopback import LoopbackTransport

REMOTE_ID = "29:163058"
FAN_ID = "29:224547"
GATEWAY_ID = "18:149960"
MQTT_TOPIC = "RAMSES/GATEWAY"
TIMESTAMP = "2026-10-31T12:00:00+00:00"


def make_coordinator(
    hass: HomeAssistant,
    entry: MockConfigEntry,
    data: CoordinatorData,
) -> OrconMVS15DataUpdateCoordinator:
    """Build a coordinator with the data a real push would have delivered."""
    coordinator = OrconMVS15DataUpdateCoordinator(hass, entry)
    coordinator.async_set_updated_data(data)
    return coordinator


async def test_diagnostics_report_entry_session_and_coordinators(
    hass: HomeAssistant,
) -> None:
    """Diagnostics show the IDs, subscriptions and decoded values, and serialise."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Orcon MVS-15",
        data={
            CONF_REMOTE_ID: REMOTE_ID,
            CONF_FAN_ID: FAN_ID,
            CONF_GATEWAY_ID: GATEWAY_ID,
            CONF_MQTT_TOPIC: MQTT_TOPIC,
        },
    )
    entry.add_to_hass(hass)

    session = RamsesSession(LoopbackTransport(gateway_id=RamsesID(GATEWAY_ID)))
    session.subscribe("31D9", Mock())
    discovery = DiscoveryManager(hass, entry, {"fan": RamsesID(FAN_ID)})

    entry.runtime_data = OrconMVS15RuntimeData(
        config=OrconMVS15Config(
            gateway_id=RamsesID(GATEWAY_ID),
            remote_id=RamsesID(REMOTE_ID),
            fan_id=RamsesID(FAN_ID),
            mqtt_topic=MQTT_TOPIC,
        ),
        fan_coordinator=make_coordinator(
            hass,
            entry,
            {
                "fan_mode": "low",
                "fan_signal_strength": -68,
                "fan_since": RamsesPacketDatetime(TIMESTAMP),
            },
        ),
        co2_coordinator=make_coordinator(hass, entry, {"co2": 812}),
        gateway_coordinator=make_coordinator(
            hass,
            entry,
            {"firmware_version": "0.5.3", "latest_firmware_version": "0.6.0"},
        ),
        session=session,
        controller=Mock(),
        discovery=discovery,
    )

    diagnostics = await async_get_config_entry_diagnostics(hass, entry)

    assert diagnostics["entry"] == {
        "title": "Orcon MVS-15",
        "data": {
            CONF_REMOTE_ID: REMOTE_ID,
            CONF_FAN_ID: FAN_ID,
            CONF_GATEWAY_ID: GATEWAY_ID,
            CONF_MQTT_TOPIC: MQTT_TOPIC,
        },
        "options": {},
    }
    assert diagnostics["session"] == {
        "gateway_id": GATEWAY_ID,
        "connection_state": "connected",
        "pending_requests": 0,
        "subscribed_codes": ["31D9"],
    }
    assert diagnostics["devices"] == {
        "fan_id": FAN_ID,
        "co2_id": RamsesID.empty_address,
        "remote_id": REMOTE_ID,
    }
    assert diagnostics["coordinators"]["fan"] == {
        "last_update_success": True,
        "data": {
            "fan_mode": "low",
            "fan_signal_strength": -68,
            "fan_since": TIMESTAMP,
        },
    }
    assert diagnostics["coordinators"]["co2"]["data"] == {"co2": 812}
    assert diagnostics["coordinators"]["gateway"] == {
        "last_update_success": True,
        "data": {
            "firmware_version": "0.5.3",
            "latest_firmware_version": "0.6.0",
        },
    }

    json.dumps(diagnostics)
