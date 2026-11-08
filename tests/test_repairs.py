"""Tests for the repair issues raised by the integration."""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from datetime import UTC, datetime

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.helpers import issue_registry as ir

from controller_helpers import (
    FAN_ID,
    GATEWAY_ID,
    NEIGHBOUR_ID,
    Harness,
    feed,
    make_controller,
    set_connected,
)
from custom_components.orcon_mvs15.const import DOMAIN
from custom_components.orcon_mvs15.controller import FAN_RESPONSE_TIMEOUT
from custom_components.orcon_mvs15.issues import (
    async_create_fan_not_responding_issue,
    fan_not_responding_issue_id,
)
from custom_components.orcon_mvs15.ramses.protocol import RamsesID

FAN_STATE = f"044 RP --- {FAN_ID} {GATEWAY_ID} --:------ 31D9 003 000001"
OWN_POWERUP = f"044 I --- --:------ --:------ {FAN_ID} 042F 006 00004C004C00"
NEIGHBOUR_POWERUP = (
    f"044 I --- --:------ --:------ {NEIGHBOUR_ID} 042F 006 00004C004C00"
)


@pytest.fixture
async def make(
    hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch
) -> AsyncIterator[Callable[..., Harness]]:
    """Build controllers and stop them after the test."""
    created: list[Harness] = []

    def _make(**kwargs: object) -> Harness:
        harness = make_controller(hass, monkeypatch, **kwargs)  # type: ignore[arg-type]
        created.append(harness)
        return harness

    yield _make

    for harness in created:
        await harness.controller.stop()


def get_issue(hass: HomeAssistant) -> ir.IssueEntry | None:
    """Return the repair issue for the configured fan."""
    issue_id = fan_not_responding_issue_id(RamsesID(FAN_ID))
    return ir.async_get(hass).async_get_issue(DOMAIN, issue_id)


async def test_fan_watchdog_raises_an_issue_after_the_timeout(
    hass: HomeAssistant, make: Callable[..., Harness]
) -> None:
    """A configured fan that never answers gets an actionable repair issue."""
    harness = make()

    harness.controller.start_fan_watchdog()

    assert len(harness.timers.later) == 1
    delay, action, _cancel = harness.timers.later[0]
    assert delay == FAN_RESPONSE_TIMEOUT

    action(datetime.now(UTC))

    issue = get_issue(hass)
    assert issue is not None
    assert issue.translation_key == "fan_not_responding"
    assert issue.translation_placeholders == {"fan_id": FAN_ID}
    assert issue.severity is ir.IssueSeverity.WARNING
    assert issue.is_fixable is False


async def test_a_fan_packet_clears_the_issue_and_the_watchdog(
    make: Callable[..., Harness], hass: HomeAssistant
) -> None:
    """The first packet from the fan proves the RF link works again."""
    harness = make()
    await harness.controller.start()
    _delay, _action, cancel = harness.timers.later[0]
    async_create_fan_not_responding_issue(hass, RamsesID(FAN_ID))
    assert get_issue(hass) is not None

    await feed(harness, FAN_STATE)

    assert get_issue(hass) is None
    cancel.assert_called_once_with()


async def test_only_this_fans_powerup_clears_the_issue(
    make: Callable[..., Harness], hass: HomeAssistant
) -> None:
    """A neighbour's 042F must not hide this fan staying silent."""
    harness = make()
    await harness.controller.start()
    async_create_fan_not_responding_issue(hass, RamsesID(FAN_ID))

    await feed(harness, NEIGHBOUR_POWERUP)

    assert get_issue(hass) is not None

    await feed(harness, OWN_POWERUP)

    assert get_issue(hass) is None


async def test_mqtt_outage_pauses_the_watchdog_and_reconnect_restarts_it(
    make: Callable[..., Harness],
) -> None:
    """An unreachable gateway is no evidence that the fan stopped answering."""
    harness = make()
    await harness.controller.start()
    assert len(harness.timers.later) == 1
    _delay, _action, cancel = harness.timers.later[0]

    await set_connected(harness, False)

    cancel.assert_called_once_with()
    assert harness.controller._fan_watchdog_unsub is None

    await set_connected(harness, True)

    assert len(harness.timers.later) == 2
    assert harness.timers.later[1][0] == FAN_RESPONSE_TIMEOUT


async def test_cleanup_stops_the_watchdog_and_removes_the_issue(
    make: Callable[..., Harness], hass: HomeAssistant
) -> None:
    """Unloading the entry must not leave a repair issue behind."""
    harness = make()
    harness.controller.start_fan_watchdog()
    _delay, _action, cancel = harness.timers.later[0]
    async_create_fan_not_responding_issue(hass, RamsesID(FAN_ID))

    await harness.controller.stop()

    cancel.assert_called_once_with()
    assert get_issue(hass) is None


async def test_no_watchdog_without_a_known_fan(
    make: Callable[..., Harness],
) -> None:
    """Before discovery there is nothing to watch and nothing to report."""
    harness = make(fan_id="")

    harness.controller.start_fan_watchdog()
    harness.controller.async_set_connected(True)

    assert harness.timers.later == []
