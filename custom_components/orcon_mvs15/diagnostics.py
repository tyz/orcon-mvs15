"""Diagnostics support for the Orcon MVS-15 integration.

The integration stores no credentials: only Ramses IDs, an MQTT topic prefix
and the decoded packet values. Nothing therefore needs to be redacted; the
payload values are converted to strings so the result is always serialisable.
"""

from __future__ import annotations

from typing import Any

from homeassistant.core import HomeAssistant

from .coordinator import CoordinatorData, OrconMVS15DataUpdateCoordinator
from .models import OrconMVS15ConfigEntry


def _serialisable_data(data: CoordinatorData) -> dict[str, Any]:
    """Return coordinator values as JSON-friendly scalars."""
    return {
        key: value
        if isinstance(value, (str, int, float, bool)) or value is None
        else str(value)
        for key, value in data.items()
    }


def _coordinator_diagnostics(
    coordinator: OrconMVS15DataUpdateCoordinator,
) -> dict[str, Any]:
    """Return the state of one push coordinator."""
    return {
        "last_update_success": coordinator.last_update_success,
        "data": _serialisable_data(coordinator.data or {}),
    }


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: OrconMVS15ConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    runtime = entry.runtime_data
    session = runtime.ramses_esp

    return {
        "entry": {
            "title": entry.title,
            "data": dict(entry.data),
            "options": dict(entry.options),
        },
        "session": {
            "gateway_id": str(session.gateway_id),
            "remote_id": str(session.remote_id),
            "fan_id": str(session.fan_id),
            "co2_id": str(session.co2_id),
            "pending_packets": session.pending_packets,
            "handled_codes": sorted(session.handled_codes),
        },
        "coordinators": {
            "fan": _coordinator_diagnostics(runtime.fan_coordinator),
            "co2": _coordinator_diagnostics(runtime.co2_coordinator),
            "remote": _coordinator_diagnostics(runtime.rem_coordinator),
        },
    }
