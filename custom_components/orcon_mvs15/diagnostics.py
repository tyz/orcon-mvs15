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
    session = runtime.session
    discovery = runtime.discovery

    return {
        "entry": {
            "title": entry.title,
            "data": dict(entry.data),
            "options": dict(entry.options),
        },
        "session": {
            "gateway_id": str(session.gateway_id),
            "connection_state": session.connection_state.value,
            "pending_requests": len(session.pending_requests),
            "subscribed_codes": sorted(session.subscribed_codes),
        },
        "devices": {
            "fan_id": str(discovery.get("fan")),
            "co2_id": str(discovery.get("co2")),
            "remote_id": str(runtime.config.remote_id),
        },
        "coordinators": {
            "fan": _coordinator_diagnostics(runtime.fan_coordinator),
            "co2": _coordinator_diagnostics(runtime.co2_coordinator),
        },
    }
