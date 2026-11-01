"""Tests for the repair issues raised by the integration."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, Mock

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.helpers import issue_registry as ir

from custom_components.orcon_mvs15 import ramses_esp as ramses_esp_module
from custom_components.orcon_mvs15.const import DOMAIN
from custom_components.orcon_mvs15.issues import (
    async_create_fan_not_responding_issue,
    fan_not_responding_issue_id,
)
from custom_components.orcon_mvs15.ramses_esp import FAN_RESPONSE_TIMEOUT, RamsesESP
from custom_components.orcon_mvs15.ramses_packet import RamsesID

GATEWAY_ID = "18:149960"
FAN_ID = "29:224547"
REMOTE_ID = "29:163058"
NEIGHBOUR_ID = "29:999999"
TIMESTAMP = "2026-09-11T17:29:09.534250+02:00"


@pytest.fixture(autouse=True)
def no_humidity_timer(monkeypatch: pytest.MonkeyPatch) -> None:
    """init_fan() starts the humidity poll; the repair tests only need the fan."""
    monkeypatch.setattr(
        ramses_esp_module, "async_track_time_interval", Mock(return_value=Mock())
    )


def make_session(hass: HomeAssistant, *, fan_id: str = FAN_ID) -> RamsesESP:
    """Build a session without an MQTT connection."""
    return RamsesESP(
        hass=hass,
        mqtt=Mock(),
        remote_id=RamsesID(REMOTE_ID),
        fan_id=RamsesID(fan_id),
        co2_id=RamsesID(),
        gateway_id=RamsesID(GATEWAY_ID),
        config_entry_id="test_entry",
    )


def get_issue(hass: HomeAssistant) -> ir.IssueEntry | None:
    """Return the repair issue for the configured fan."""
    issue_id = fan_not_responding_issue_id(RamsesID(FAN_ID))
    return ir.async_get(hass).async_get_issue(DOMAIN, issue_id)


def make_envelope(msg: str) -> dict[str, str]:
    """Build the JSON envelope the gateway delivers."""
    return {"ts": TIMESTAMP, "msg": msg}


async def test_fan_watchdog_raises_an_issue_after_the_timeout(
    hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A configured fan that never answers gets an actionable repair issue."""
    scheduled: list[tuple[timedelta, Callable[[datetime], None]]] = []
    monkeypatch.setattr(
        ramses_esp_module,
        "async_call_later",
        lambda hass_, delay, action: scheduled.append((delay, action)),
    )
    session = make_session(hass)
    session.publish = AsyncMock()

    await session.init_fan()

    assert len(scheduled) == 1
    delay, action = scheduled[0]
    assert delay == FAN_RESPONSE_TIMEOUT

    action(datetime.now(UTC))

    issue = get_issue(hass)
    assert issue is not None
    assert issue.translation_key == "fan_not_responding"
    assert issue.translation_placeholders == {"fan_id": FAN_ID}
    assert issue.severity is ir.IssueSeverity.WARNING
    assert issue.is_fixable is False


async def test_a_fan_packet_clears_the_issue_and_the_watchdog(
    hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The first packet from the fan proves the RF link works again."""
    cancel = Mock()
    monkeypatch.setattr(
        ramses_esp_module, "async_call_later", Mock(return_value=cancel)
    )
    session = make_session(hass)
    session.publish = AsyncMock()
    await session.init_fan()
    async_create_fan_not_responding_issue(hass, RamsesID(FAN_ID))
    assert get_issue(hass) is not None
    session.add_handler("31D9", Mock())

    await session._handle_ramses_packet(
        make_envelope(f"044 RP --- {FAN_ID} {GATEWAY_ID} --:------ 31D9 003 000004")
    )

    assert get_issue(hass) is None
    cancel.assert_called_once_with()


async def test_only_this_fans_powerup_clears_the_issue(
    hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A neighbour's 042F must not hide this fan staying silent."""
    monkeypatch.setattr(
        ramses_esp_module, "async_call_later", Mock(return_value=Mock())
    )
    session = make_session(hass)
    session.publish = AsyncMock()
    await session.init_fan()
    async_create_fan_not_responding_issue(hass, RamsesID(FAN_ID))

    await session._handle_ramses_packet(
        make_envelope(
            f"044 I --- --:------ --:------ {NEIGHBOUR_ID} 042F 006 00004C004C00"
        )
    )

    assert get_issue(hass) is not None

    await session._handle_ramses_packet(
        make_envelope(f"044 I --- --:------ --:------ {FAN_ID} 042F 006 00004C004C00")
    )

    assert get_issue(hass) is None


async def test_mqtt_outage_pauses_the_watchdog_and_reconnect_restarts_it(
    hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An unreachable gateway is no evidence that the fan stopped answering."""
    cancel = Mock()
    call_later = Mock(return_value=cancel)
    monkeypatch.setattr(ramses_esp_module, "async_call_later", call_later)
    session = make_session(hass)
    session.publish = AsyncMock()
    await session.init_fan()
    assert call_later.call_count == 1

    session.async_set_mqtt_connected(False)

    cancel.assert_called_once_with()
    assert session._fan_watchdog_unsub is None

    session.async_set_mqtt_connected(True)

    assert call_later.call_count == 2
    assert call_later.call_args.args[1] == FAN_RESPONSE_TIMEOUT


async def test_cleanup_stops_the_watchdog_and_removes_the_issue(
    hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Unloading the entry must not leave a repair issue behind."""
    cancel = Mock()
    monkeypatch.setattr(
        ramses_esp_module, "async_call_later", Mock(return_value=cancel)
    )
    session = make_session(hass)
    session.publish = AsyncMock()
    await session.init_fan()
    async_create_fan_not_responding_issue(hass, RamsesID(FAN_ID))

    session.cleanup()

    cancel.assert_called_once_with()
    assert get_issue(hass) is None


async def test_no_watchdog_without_a_known_fan(
    hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Before discovery there is nothing to watch and nothing to report."""
    call_later = Mock()
    monkeypatch.setattr(ramses_esp_module, "async_call_later", call_later)
    session = make_session(hass, fan_id="")

    session.start_fan_watchdog()
    session.async_set_mqtt_connected(True)

    call_later.assert_not_called()
