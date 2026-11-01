"""Repair issues raised by the Orcon MVS-15 integration.

The integration cannot repair a broken RF link itself, so the issues it raises
are informational: they tell the user which device stopped answering and what
to check. Every issue is deleted as soon as the device is heard again.
"""

from __future__ import annotations

import logging

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import issue_registry as ir

from .const import DOMAIN
from .ramses_packet import RamsesID

_LOGGER = logging.getLogger(__name__)

FAN_NOT_RESPONDING = "fan_not_responding"


def fan_not_responding_issue_id(fan_id: RamsesID) -> str:
    """Return the issue id for one fan.

    The Ramses ID contains a colon; replace it so the id stays a plain
    identifier in the repairs URL and the registry store.
    """
    return f"{FAN_NOT_RESPONDING}_{fan_id.replace(':', '_')}"


@callback
def async_create_fan_not_responding_issue(
    hass: HomeAssistant, fan_id: RamsesID
) -> None:
    """Tell the user that a configured fan did not answer.

    A silent fan usually means it lost power, the remote ID is wrong, or the
    gateway is out of RF range. The user can check those; Home Assistant
    cannot.
    """
    _LOGGER.warning("No packet received from the fan %s", fan_id)
    ir.async_create_issue(
        hass,
        DOMAIN,
        fan_not_responding_issue_id(fan_id),
        is_fixable=False,
        severity=ir.IssueSeverity.WARNING,
        translation_key=FAN_NOT_RESPONDING,
        translation_placeholders={"fan_id": str(fan_id)},
    )


@callback
def async_delete_fan_not_responding_issue(
    hass: HomeAssistant, fan_id: RamsesID
) -> None:
    """Delete the issue once the fan sends a packet again."""
    ir.async_delete_issue(hass, DOMAIN, fan_not_responding_issue_id(fan_id))
