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
from custom_components.orcon_mvs15.models import (
    OrconMVS15Config,
    OrconMVS15RuntimeData,
)
from custom_components.orcon_mvs15.ramses_esp import RamsesESP
from custom_components.orcon_mvs15.ramses_packet import (
    RamsesID,
    RamsesPacketDatetime,
)

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
    """Diagnostics show the IDs, handlers and decoded values, and serialise."""
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

    session = RamsesESP(
        hass=hass,
        mqtt=Mock(),
        remote_id=RamsesID(REMOTE_ID),
        fan_id=RamsesID(FAN_ID),
        co2_id=RamsesID(),
        gateway_id=RamsesID(GATEWAY_ID),
        config_entry_id=entry.entry_id,
    )
    session.add_handler("31D9", Mock())

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
        rem_coordinator=make_coordinator(hass, entry, {"last_command": "low"}),
        ramses_esp=session,
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
        "remote_id": REMOTE_ID,
        "fan_id": FAN_ID,
        "co2_id": RamsesID.empty_address,
        "pending_packets": 0,
        "handled_codes": ["31D9"],
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
    assert diagnostics["coordinators"]["remote"]["data"] == {"last_command": "low"}

    json.dumps(diagnostics)
