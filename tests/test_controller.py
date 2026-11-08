"""Tests for the Orcon policy controller."""

from __future__ import annotations

import asyncio
import logging
import time

from collections.abc import AsyncIterator, Callable
from datetime import timedelta
from pathlib import Path
from unittest.mock import AsyncMock, Mock

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.device_registry import DeviceRegistry

from controller_helpers import (
    CO2_ID,
    FAN_ID,
    GATEWAY_ID,
    NEIGHBOUR_ID,
    REMOTE_ID,
    Harness,
    envelope,
    feed,
    make_controller,
    set_connected,
    settle,
)
from custom_components.orcon_mvs15.const import CONF_CO2_ID, CONF_FAN_ID, DOMAIN
from custom_components.orcon_mvs15.ramses.protocol import RamsesID
from custom_components.orcon_mvs15.ramses.transport import TransportError
from custom_components.orcon_mvs15.ramses.transport.loopback import LoopbackTransport

FAN_STATE = f"044 RP --- {FAN_ID} {GATEWAY_ID} --:------ 31D9 003 000001"
FAN_ECHO = f"000 I --- {FAN_ID} {GATEWAY_ID} --:------ 31D9 003 000001"
NEIGHBOUR_STATE = f"044 RP --- {NEIGHBOUR_ID} {GATEWAY_ID} --:------ 31D9 003 000001"
POWERUP = f"044 I --- --:------ --:------ {FAN_ID} 042F 006 00004C004C00"
POWERUP_WITHOUT_ANN = f"044 I --- {FAN_ID} --:------ --:------ 042F 006 00004C004C00"
VENT_DEMAND = f"044 I --- {CO2_ID} {FAN_ID} --:------ 31E0 008 0000000000641E00"
VENT_DEMAND_BROADCAST = (
    f"099  I --- {CO2_ID} --:------ {CO2_ID} 31E0 008 0000000000641E00"
)
HUMIDITY = f"044  I --- {FAN_ID} {GATEWAY_ID} --:------ 12A0 002 0037"
HUMIDITY_REQUEST = f"081  I --- {FAN_ID} {GATEWAY_ID} --:------ 12A0 001 00"
DEVICE_INFO_REQUEST = f"081  I --- {REMOTE_ID} {GATEWAY_ID} --:------ 10E0 001 00"
TIMED_ECHO = f"000 I --- {REMOTE_ID} {FAN_ID} --:------ 22F3 007 00020F03040000"


class FailingTransport(LoopbackTransport):
    """A gateway that cannot publish."""

    async def send(self, packet: object) -> None:
        raise TransportError("broker is offline")


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


async def test_start_subscribes_to_every_code_and_the_transport(
    make: Callable[..., Harness],
) -> None:
    """A started controller listens to all decoded codes and the raw tap."""
    harness = make()

    await harness.controller.start()

    assert harness.session.subscribed_codes == {
        "042F",
        "10E0",
        "1298",
        "12A0",
        "22F1",
        "22F3",
        "31D9",
        "31E0",
    }


async def test_start_initialises_the_known_devices(
    make: Callable[..., Harness],
) -> None:
    """After subscribing, the stored devices are asked for their state."""
    harness = make(co2_id=CO2_ID)
    harness.controller.init_fan = AsyncMock()  # type: ignore[method-assign]
    harness.controller.init_co2 = AsyncMock()  # type: ignore[method-assign]

    await harness.controller.start()

    harness.controller.init_fan.assert_awaited_once_with()
    harness.controller.init_co2.assert_awaited_once_with()


async def test_start_without_devices_only_subscribes(
    make: Callable[..., Harness],
) -> None:
    """With no known device the controller waits for broadcasts."""
    harness = make(fan_id="", co2_id="")
    harness.controller.init_fan = AsyncMock()  # type: ignore[method-assign]
    harness.controller.init_co2 = AsyncMock()  # type: ignore[method-assign]

    await harness.controller.start()

    harness.controller.init_fan.assert_not_awaited()
    harness.controller.init_co2.assert_not_awaited()
    assert "042F" in harness.session.subscribed_codes


async def test_init_fan_requests_the_current_state(
    make: Callable[..., Harness],
) -> None:
    """The fan answers its device info, humidity and fan state requests."""
    harness = make()

    await harness.controller.init_fan()

    assert [packet.code for packet in harness.transport.sent] == [
        "10E0",
        "12A0",
        "31D9",
    ]
    assert all(packet.dst_id == FAN_ID for packet in harness.transport.sent)


async def test_init_co2_requests_the_current_state(
    make: Callable[..., Harness],
) -> None:
    """The CO2 sensor answers its device info, level and vent demand."""
    harness = make(co2_id=CO2_ID)

    await harness.controller.init_co2()

    assert [packet.code for packet in harness.transport.sent] == [
        "10E0",
        "1298",
        "31E0",
    ]
    assert all(packet.dst_id == CO2_ID for packet in harness.transport.sent)


async def test_init_co2_is_a_no_op_without_a_sensor(
    make: Callable[..., Harness],
) -> None:
    """Before discovery there is nothing to ask."""
    harness = make(co2_id="")

    await harness.controller.init_co2()

    assert harness.transport.sent == []


async def test_req_humidity_asks_the_fan(make: Callable[..., Harness]) -> None:
    """The poll interval asks the fan for humidity directly."""
    harness = make()

    await harness.controller.req_humidity()

    assert [packet.code for packet in harness.transport.sent] == ["12A0"]
    assert harness.transport.sent[0].dst_id == FAN_ID


async def test_humidity_polling_starts_once_and_is_cleaned_up(
    make: Callable[..., Harness],
) -> None:
    """Repeated setup does not add intervals, and stop removes it."""
    harness = make()

    harness.controller.start_humidity_polling()
    harness.controller.start_humidity_polling()

    assert len(harness.timers.intervals) == 1
    action, interval, cancel = harness.timers.intervals[0]
    assert action == harness.controller.req_humidity
    assert interval == timedelta(minutes=5)

    await harness.controller.stop()

    cancel.assert_called_once_with()


async def test_a_frame_from_another_fan_is_ignored(
    make: Callable[..., Harness],
) -> None:
    """A neighbouring Orcon's broadcast is not ours to handle."""
    harness = make()
    await harness.controller.start()

    await feed(harness, NEIGHBOUR_STATE)

    assert harness.fan.data == {}


async def test_our_fan_state_updates_the_coordinator(
    make: Callable[..., Harness],
) -> None:
    """A packet from the configured fan drives the fan coordinator."""
    harness = make()
    await harness.controller.start()

    await feed(harness, FAN_STATE)

    assert harness.fan.data["fan_mode"] == "low"
    assert harness.fan.data["discovered_fan_id"] == FAN_ID


async def test_a_gateway_echo_of_our_request_is_ignored(
    make: Callable[..., Harness],
) -> None:
    """The gateway echoes our own requests with no radio signal."""
    harness = make()
    await harness.controller.start()

    await feed(harness, FAN_ECHO)

    assert harness.fan.data == {}


async def test_a_command_echo_still_drives_the_countdown(
    make: Callable[..., Harness],
) -> None:
    """Our own timed command is echoed with no radio signal, but it counts."""
    harness = make()
    await harness.controller.start()

    await feed(harness, TIMED_ECHO)

    assert harness.fan.data["fan_timer_remaining"] == 15


async def test_unknown_31e0_from_the_fan_discovers_the_co2_sensor(
    make: Callable[..., Harness],
) -> None:
    """A vent-demand frame addressed to the fan reveals the CO2 room sensor."""
    harness = make(co2_id="")
    await harness.controller.start()

    await feed(harness, VENT_DEMAND)

    assert harness.discovery.get("co2") == CO2_ID
    assert harness.entry.data[CONF_CO2_ID] == CO2_ID
    assert harness.devices == [("co2", RamsesID(CO2_ID))]


async def test_a_broadcast_31e0_is_not_adopted_without_a_fan(
    make: Callable[..., Harness],
) -> None:
    """Before the fan is known, a neighbour's broadcast is not our sensor."""
    harness = make(fan_id="", co2_id="")
    await harness.controller.start()

    await feed(harness, VENT_DEMAND_BROADCAST)

    assert not harness.discovery.get("co2")
    assert CONF_CO2_ID not in harness.entry.data
    assert harness.devices == []


async def test_a_10e0_request_does_not_break_the_handler(
    make: Callable[..., Harness], caplog: pytest.LogCaptureFixture
) -> None:
    """A device-info request carries no fields, so the handler skips it."""
    harness = make()
    await harness.controller.start()

    with caplog.at_level(logging.ERROR):
        await feed(harness, DEVICE_INFO_REQUEST)

    assert "A RAMSES subscriber failed" not in caplog.text


async def test_a_humidity_request_keeps_the_last_measurement(
    make: Callable[..., Harness], caplog: pytest.LogCaptureFixture
) -> None:
    """A one-byte 12A0 request must not overwrite the humidity with None."""
    harness = make()
    await harness.controller.start()
    await feed(harness, HUMIDITY)

    with caplog.at_level(logging.ERROR):
        await feed(harness, HUMIDITY_REQUEST)

    assert harness.fan.data["relative_humidity"] == 55
    assert "A RAMSES subscriber failed" not in caplog.text


async def test_powerup_discovers_the_fan(
    make: Callable[..., Harness],
) -> None:
    """The 042F broadcast names and stores the fan without a reload."""
    harness = make(fan_id="")
    await harness.controller.start()

    await feed(harness, POWERUP)

    assert harness.discovery.get("fan") == FAN_ID
    assert harness.entry.data[CONF_FAN_ID] == FAN_ID
    assert harness.devices == [("fan", RamsesID(FAN_ID))]
    assert harness.fan.data["fan_signal_strength"] == -44


async def test_powerup_without_ann_id_uses_the_sender(
    make: Callable[..., Harness],
) -> None:
    """Not every unit fills in ann_id, so the sender still names the fan."""
    harness = make(fan_id="")
    await harness.controller.start()

    await feed(harness, POWERUP_WITHOUT_ANN)

    assert harness.discovery.get("fan") == FAN_ID


async def test_a_later_neighbour_powerup_does_not_replace_the_fan(
    make: Callable[..., Harness],
) -> None:
    """The first power-up that names a fan owns the discovery."""
    harness = make(fan_id="")
    await harness.controller.start()

    await feed(harness, POWERUP)
    await feed(
        harness,
        f"044 I --- --:------ --:------ {NEIGHBOUR_ID} 042F 006 00004C004C00",
    )

    assert harness.discovery.get("fan") == FAN_ID


async def test_set_preset_mode_sends_the_command(
    make: Callable[..., Harness],
) -> None:
    """A preset change is a 22F1 command from the remote to the fan."""
    harness = make()

    await harness.controller.set_preset_mode("high")

    assert len(harness.transport.sent) == 1
    packet = harness.transport.sent[0]
    assert packet.code == "22F1"
    assert packet.src_id == REMOTE_ID
    assert packet.dst_id == FAN_ID


async def test_set_preset_mode_rejects_an_unknown_mode(
    make: Callable[..., Harness],
) -> None:
    """An unknown preset is a user error with a translatable message."""
    harness = make()

    with pytest.raises(HomeAssistantError) as err:
        await harness.controller.set_preset_mode("Turbo")

    assert err.value.translation_domain == DOMAIN
    assert err.value.translation_key == "unknown_preset_mode"
    assert err.value.translation_placeholders == {"mode": "Turbo"}


async def test_set_preset_mode_reports_a_publish_failure(
    make: Callable[..., Harness],
) -> None:
    """A failed command must reach the caller so Home Assistant can report it."""

    harness = make()
    harness.session._transport = FailingTransport()  # type: ignore[assignment]

    with pytest.raises(HomeAssistantError) as err:
        await harness.controller.set_preset_mode("low")

    assert err.value.translation_key == "set_preset_failed"
    assert err.value.translation_placeholders == {
        "mode": "low",
        "error": "broker is offline",
    }


async def test_a_closed_controller_ignores_late_work(
    make: Callable[..., Harness],
) -> None:
    """Work started before unload must not publish or arm timers afterwards."""
    harness = make(co2_id=CO2_ID)
    await harness.controller.stop()

    await harness.controller.init_fan()
    await harness.controller.init_co2()
    await harness.controller.req_humidity()
    harness.controller.start_humidity_polling()
    harness.controller.start_fan_watchdog()

    assert harness.transport.sent == []
    assert harness.timers.intervals == []
    assert harness.timers.later == []


async def test_a_closed_controller_refuses_a_command(
    make: Callable[..., Harness],
) -> None:
    """A command after unload must fail instead of pretending to be sent."""
    harness = make()
    await harness.controller.stop()

    with pytest.raises(HomeAssistantError) as err:
        await harness.controller.set_preset_mode("low")

    assert err.value.translation_key == "set_preset_failed"
    assert err.value.translation_placeholders == {
        "mode": "low",
        "error": "The RAMSES session is closed",
    }


async def test_a_connection_loss_makes_the_entities_unavailable(
    make: Callable[..., Harness],
) -> None:
    """An unreachable gateway is no evidence about the devices."""
    harness = make()
    await harness.controller.start()

    await set_connected(harness, False)

    assert harness.fan.available is False
    assert harness.co2.available is False

    await set_connected(harness, True)

    assert harness.fan.available is True
    assert harness.co2.available is True


async def test_the_version_topic_updates_the_gateway_device(
    make: Callable[..., Harness], device_registry: DeviceRegistry
) -> None:
    """The gateway firmware version belongs to the gateway device."""
    harness = make()
    await harness.controller.start()
    device = device_registry.async_get_or_create(
        config_entry_id=harness.entry.entry_id,
        identifiers={(DOMAIN, GATEWAY_ID)},
    )

    harness.transport.receive_version("2026.10.1")
    await settle()

    updated = device_registry.async_get(device.id)
    assert updated is not None
    assert updated.sw_version == "2026.10.1"


async def test_packet_log_is_off_by_default(make: Callable[..., Harness]) -> None:
    """A fresh entry does not write the debugging log."""
    harness = make()
    harness.controller.packet_log = AsyncMock()  # type: ignore[method-assign]

    await harness.controller._log_packet(envelope(FAN_STATE))

    harness.controller.packet_log.assert_not_awaited()


async def test_packet_log_writes_when_enabled(make: Callable[..., Harness]) -> None:
    """The option forwards every raw envelope to the log."""
    harness = make(packet_log=True)
    harness.controller.packet_log = AsyncMock()  # type: ignore[method-assign]

    await harness.controller._log_packet(envelope(FAN_STATE))

    harness.controller.packet_log.assert_awaited_once_with(envelope(FAN_STATE))


async def test_packet_log_uses_the_configured_path(
    make: Callable[..., Harness], tmp_path: Path
) -> None:
    """The injected path is the default for every write."""
    path = tmp_path / "configured.log"
    harness = make(packet_log=True, packet_log_path=str(path))
    item = envelope(FAN_STATE)

    await harness.controller.packet_log(item)

    assert path.read_text().strip() == f"{item['ts']} {item['msg']}"


async def test_packet_log_writes_and_rotates(
    make: Callable[..., Harness], tmp_path: Path
) -> None:
    """The debug log rolls over instead of growing without bound."""
    harness = make()
    path = tmp_path / "packet.log"
    item = envelope(FAN_STATE)

    await harness.controller.packet_log(item, path=str(path), max_size=1)

    rotated = tmp_path / "packet.log.1"
    assert rotated.read_text().strip() == f"{item['ts']} {item['msg']}"
    assert path.read_text() == ""
    assert harness.controller._log_f is not None


async def test_packet_log_reports_an_unwritable_path(
    make: Callable[..., Harness],
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A missing directory is logged instead of breaking packet handling."""
    harness = make()
    path = tmp_path / "missing" / "packet.log"

    with caplog.at_level(logging.ERROR):
        await harness.controller.packet_log(envelope(FAN_STATE), path=str(path))

    assert "Error opening" in caplog.text
    assert harness.controller._log_f is None


async def test_packet_log_reports_a_failed_reopen(
    make: Callable[..., Harness],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A reopen failure leaves the log closed but recoverable."""
    harness = make()
    path = tmp_path / "packet.log"
    real_open = open
    calls = 0

    def fake_open(*args: object, **kwargs: object) -> object:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("disk full")
        return real_open(*args, **kwargs)

    monkeypatch.setattr("builtins.open", fake_open)

    with caplog.at_level(logging.ERROR):
        await harness.controller.packet_log(
            envelope(FAN_STATE), path=str(path), max_size=1
        )

    assert "Error reopening" in caplog.text
    assert harness.controller._log_f is None

    item = envelope(FAN_STATE)
    await harness.controller.packet_log(item, path=str(path))

    assert path.read_text().strip() == f"{item['ts']} {item['msg']}"


async def test_packet_log_recreates_a_deleted_file(
    make: Callable[..., Harness], tmp_path: Path
) -> None:
    """Deleting the log while it is open must not disable packet logging."""
    harness = make()
    path = tmp_path / "packet.log"
    item = envelope(FAN_STATE)
    await harness.controller.packet_log(item, path=str(path))

    path.unlink()
    await harness.controller.packet_log(item, path=str(path))

    assert path.read_text().strip() == f"{item['ts']} {item['msg']}"


async def test_packet_log_ignores_a_failing_close(
    make: Callable[..., Harness], tmp_path: Path
) -> None:
    """A file that cannot be closed must not stop the rotation."""
    harness = make()
    path = tmp_path / "packet.log"
    path.write_text("old")
    log_file = Mock()
    log_file.close.side_effect = OSError("already closed")
    harness.controller._log_f = log_file

    await harness.controller.packet_log(envelope(FAN_STATE), path=str(path), max_size=0)

    assert (tmp_path / "packet.log.1").exists()
    assert harness.controller._log_f is not None
    assert harness.controller._log_f is not log_file


async def test_packet_log_serialises_concurrent_writes(
    make: Callable[..., Harness], tmp_path: Path
) -> None:
    """Two MQTT messages logged at once must not interleave their lines."""
    harness = make()
    path = tmp_path / "packet.log"
    path.touch()

    class OverlapDetectingFile:
        """A log file that notices when two writes overlap."""

        def __init__(self) -> None:
            self.active = False
            self.overlap = False

        def write(self, text: str) -> None:
            if self.active:
                self.overlap = True
            self.active = True
            time.sleep(0.02)  # hold the writer so a second thread can enter
            self.active = False

        def flush(self) -> None:
            """Nothing to flush for the stub."""

        def close(self) -> None:
            """Nothing to close for the stub."""

    log_file = OverlapDetectingFile()
    harness.controller._log_f = log_file

    await asyncio.gather(
        harness.controller.packet_log(
            envelope(FAN_STATE), path=str(path), max_size=10_000_000
        ),
        harness.controller.packet_log(
            envelope(FAN_STATE), path=str(path), max_size=10_000_000
        ),
    )

    assert log_file.overlap is False


async def test_cleanup_closes_the_packet_log(
    make: Callable[..., Harness], tmp_path: Path
) -> None:
    """A reload must not leak the debug log handle."""
    harness = make()
    path = tmp_path / "packet.log"

    await harness.controller.packet_log(envelope(FAN_STATE), path=str(path))
    log_file = harness.controller._log_f
    assert log_file is not None

    await harness.controller.stop()

    assert log_file.closed
    assert harness.controller._log_f is None
