"""Shared fakes for the controller and repair tests."""

from __future__ import annotations

import asyncio

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from unittest.mock import Mock

import pytest
from homeassistant.core import HomeAssistant

from pytest_homeassistant_custom_component.common import MockConfigEntry

import custom_components.orcon_mvs15.controller as controller_module
from custom_components.orcon_mvs15.const import CONF_MQTT_TOPIC, DOMAIN
from custom_components.orcon_mvs15.controller import OrconMVS15Controller
from custom_components.orcon_mvs15.discovery import DiscoveryManager
from custom_components.orcon_mvs15.models import OrconMVS15Config
from custom_components.orcon_mvs15.ramses.protocol import RamsesID
from custom_components.orcon_mvs15.ramses.session import RamsesSession
from custom_components.orcon_mvs15.ramses.transport import ConnectionState
from custom_components.orcon_mvs15.ramses.transport.loopback import LoopbackTransport

GATEWAY_ID = "18:149960"
FAN_ID = "29:224547"
CO2_ID = "32:093959"
REMOTE_ID = "29:163058"
NEIGHBOUR_ID = "29:999999"
MQTT_TOPIC = "RAMSES/GATEWAY"
TIMESTAMP = "2026-09-11T17:29:09.534250+02:00"


class RecordingCoordinator:
    """Coordinator stand-in that keeps what was pushed to it."""

    def __init__(self, data: dict[str, object] | None = None) -> None:
        self.data: dict[str, object] = dict(data or {})
        self.available = True
        self.availability_calls: list[bool] = []

    def async_set_updated_data(self, data: dict[str, object]) -> None:
        """Replace the pushed data."""
        self.data = data

    def async_set_available(self, available: bool) -> None:
        """Record an availability change."""
        self.available = available
        self.availability_calls.append(available)


class Timers:
    """Capture the controller's Home Assistant timers."""

    def __init__(self) -> None:
        self.later: list[tuple[timedelta, Callable[[datetime], None], Mock]] = []
        self.intervals: list[tuple[object, timedelta, Mock]] = []

    def call_later(
        self, hass: HomeAssistant, delay: timedelta, action: Callable[[datetime], None]
    ) -> Mock:
        """Record a one-shot timer."""
        cancel = Mock()
        self.later.append((delay, action, cancel))
        return cancel

    def track_interval(
        self, hass: HomeAssistant, action: object, interval: timedelta
    ) -> Mock:
        """Record a repeating timer."""
        cancel = Mock()
        self.intervals.append((action, interval, cancel))
        return cancel


@dataclass
class Harness:
    """One controller wired to a loopback transport."""

    controller: OrconMVS15Controller
    session: RamsesSession
    transport: LoopbackTransport
    discovery: DiscoveryManager
    entry: MockConfigEntry
    fan: RecordingCoordinator
    co2: RecordingCoordinator
    timers: Timers
    config: OrconMVS15Config
    devices: list[tuple[str, RamsesID]] = field(default_factory=list)


def make_controller(
    hass: HomeAssistant,
    monkeypatch: pytest.MonkeyPatch,
    *,
    fan_id: str = FAN_ID,
    co2_id: str = "",
    packet_log: bool = False,
    packet_log_path: str | None = None,
) -> Harness:
    """Build a controller with fake coordinators and captured timers."""
    timers = Timers()
    monkeypatch.setattr(controller_module, "async_call_later", timers.call_later)
    monkeypatch.setattr(
        controller_module, "async_track_time_interval", timers.track_interval
    )
    entry = MockConfigEntry(domain=DOMAIN, data={CONF_MQTT_TOPIC: MQTT_TOPIC})
    entry.add_to_hass(hass)
    devices: list[tuple[str, RamsesID]] = []
    discovery = DiscoveryManager(
        hass,
        entry,
        {"fan": RamsesID(fan_id), "co2": RamsesID(co2_id)},
        create_device=lambda kind, ramses_id: devices.append((kind, ramses_id)),
    )
    config = OrconMVS15Config(
        gateway_id=RamsesID(GATEWAY_ID),
        remote_id=RamsesID(REMOTE_ID),
        fan_id=RamsesID(fan_id),
        co2_id=RamsesID(co2_id),
        mqtt_topic=MQTT_TOPIC,
    )
    transport = LoopbackTransport(gateway_id=RamsesID(GATEWAY_ID))
    session = RamsesSession(transport)
    fan = RecordingCoordinator()
    co2 = RecordingCoordinator()
    controller = OrconMVS15Controller(
        hass,
        config,
        session,
        discovery,
        fan,  # test stub, duck typed on purpose
        co2,  # test stub, duck typed on purpose
        entry_id=entry.entry_id,
        packet_log=packet_log,
        packet_log_path=packet_log_path,
    )
    return Harness(
        controller=controller,
        session=session,
        transport=transport,
        discovery=discovery,
        entry=entry,
        fan=fan,
        co2=co2,
        timers=timers,
        config=config,
        devices=devices,
    )


def envelope(msg: str) -> dict[str, str]:
    """Wrap a frame in the gateway receive envelope."""
    return {"ts": TIMESTAMP, "msg": msg}


def make_envelope(msg: str) -> dict[str, str]:
    """Backwards-compatible alias for :func:`envelope`."""
    return envelope(msg)


async def settle() -> None:
    """Let the session consumer and the tasks it creates run."""
    for _ in range(20):
        await asyncio.sleep(0)


async def feed(harness: Harness, msg: str) -> None:
    """Deliver one frame and let it be handled."""
    await harness.transport.receive(envelope(msg))
    await settle()


async def set_connected(harness: Harness, connected: bool) -> None:
    """Report a connection change and let the subscribers run."""
    harness.transport.set_connection_state(
        ConnectionState.CONNECTED if connected else ConnectionState.DISCONNECTED
    )
    await settle()
