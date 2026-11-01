"""Tests for the Ramses ESP session."""

from __future__ import annotations

import json
import logging

from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import AsyncMock, Mock

import pytest
from homeassistant.components.mqtt import ReceiveMessage
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady, HomeAssistantError
from homeassistant.helpers.device_registry import DeviceRegistry

from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.orcon_mvs15 import ramses_esp as ramses_esp_module
from custom_components.orcon_mvs15.codes import Code12a0
from custom_components.orcon_mvs15.const import (
    CONF_MQTT_TOPIC,
    CONF_REMOTE_ID,
    DOMAIN,
)
from custom_components.orcon_mvs15.mqtt import MQTTException
from custom_components.orcon_mvs15.ramses_esp import RamsesESP
from custom_components.orcon_mvs15.ramses_packet import RamsesID, RamsesPacket

GATEWAY_ID = "18:149960"
FAN_ID = "29:224547"
REMOTE_ID = "29:163058"
CO2_ID = "29:111111"
MQTT_TOPIC = "RAMSES/GATEWAY"
TIMESTAMP = "2026-09-11T17:29:09.534250+02:00"


def make_session(
    hass: HomeAssistant,
    config_entry_id: str = "test_entry",
    *,
    fan_id: str = FAN_ID,
    co2_id: str = "",
) -> RamsesESP:
    """Build a session without an MQTT connection."""
    return RamsesESP(
        hass=hass,
        mqtt=Mock(),
        remote_id=RamsesID(REMOTE_ID),
        fan_id=RamsesID(fan_id),
        co2_id=RamsesID(co2_id),
        gateway_id=RamsesID(GATEWAY_ID),
        config_entry_id=config_entry_id,
    )


class RecordingMQTT:
    """Record whether a packet was already queued when it was published."""

    def __init__(self, session: RamsesESP) -> None:
        self.session = session
        self.published: list[RamsesPacket] = []
        self.queued_at_publish: list[bool] = []

    async def publish(self, packet: RamsesPacket) -> None:
        self.queued_at_publish.append(packet in self.session._send_queue)
        self.published.append(packet)


async def test_version_message_updates_the_gateway_device(
    hass: HomeAssistant, device_registry: DeviceRegistry
) -> None:
    """The gateway firmware version belongs to the gateway device."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_REMOTE_ID: REMOTE_ID, CONF_MQTT_TOPIC: MQTT_TOPIC},
    )
    entry.add_to_hass(hass)
    device = device_registry.async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={(DOMAIN, GATEWAY_ID)},
    )
    session = make_session(hass, entry.entry_id)
    msg = ReceiveMessage(
        topic=f"{MQTT_TOPIC}/{GATEWAY_ID}/info/version",
        payload=b"2026.10.1",
        qos=0,
        retain=False,
        subscribed_topic=f"{MQTT_TOPIC}/{GATEWAY_ID}/info/version",
        timestamp=0.0,
    )

    await session.handle_ramses_mqtt_version_message(msg)

    updated = device_registry.async_get(device.id)
    assert updated is not None
    assert updated.sw_version == "2026.10.1"


async def test_packet_is_queued_before_it_is_published(
    hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A fast response must find the packet in the retry queue."""
    cancel_retry = Mock()
    monkeypatch.setattr(
        ramses_esp_module, "async_call_later", Mock(return_value=cancel_retry)
    )
    session = make_session(hass)
    mqtt = RecordingMQTT(session)
    session.mqtt = mqtt  # pytest stub, duck typed on purpose
    packet = Code12a0.get(RamsesID(GATEWAY_ID), RamsesID(FAN_ID))

    await session.publish(packet)

    assert mqtt.queued_at_publish == [True]
    assert mqtt.published == [packet]
    assert packet in session._send_queue
    assert session.pending_packets == 1
    assert packet.expected_response is not None
    assert packet.expected_response.cancel_retry_handler is cancel_retry


async def test_retry_callback_accepts_the_scheduled_time(
    hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch
) -> None:
    """async_call_later passes the scheduled time to the retry callback."""
    scheduled: list[Callable[[datetime], None]] = []
    monkeypatch.setattr(
        ramses_esp_module,
        "async_call_later",
        lambda hass_, delay, action: scheduled.append(action),
    )
    session = make_session(hass)
    mqtt = RecordingMQTT(session)
    session.mqtt = mqtt  # pytest stub, duck typed on purpose
    packet = Code12a0.get(RamsesID(GATEWAY_ID), RamsesID(FAN_ID))

    await session.publish(packet)
    scheduled[0](datetime.now(UTC))
    await hass.async_block_till_done()

    assert mqtt.published == [packet, packet]
    assert len(scheduled) == 2
    assert packet in session._send_queue
    assert packet.expected_response is not None
    assert packet.expected_response.max_retries == 1


async def test_handled_codes_reports_the_registered_handlers(
    hass: HomeAssistant,
) -> None:
    """Diagnostics see which packet codes the session handles."""
    session = make_session(hass)

    assert session.handled_codes == set()

    session.add_handler("31D9", Mock())

    assert session.handled_codes == {"31D9"}


async def test_init_fan_starts_humidity_polling(
    hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch
) -> None:
    """12A0 is not broadcast, so polling must not depend on a response."""
    track = Mock(return_value=Mock())
    monkeypatch.setattr(ramses_esp_module, "async_track_time_interval", track)
    session = make_session(hass)
    session.publish = AsyncMock()

    await session.init_fan(discovered_fan_id=RamsesID(FAN_ID))

    track.assert_called_once()
    assert track.call_args.args[1] == session.req_humidity
    session.cleanup()


async def test_humidity_polling_starts_once_and_is_cleaned_up(
    hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Repeated fan setup does not add intervals, and cleanup removes it."""
    unsub = Mock()
    track = Mock(return_value=unsub)
    monkeypatch.setattr(ramses_esp_module, "async_track_time_interval", track)
    session = make_session(hass)
    session.publish = AsyncMock()

    await session.init_fan(discovered_fan_id=RamsesID(FAN_ID))
    await session.init_fan(discovered_fan_id=RamsesID(FAN_ID))
    session.cleanup()

    track.assert_called_once()
    unsub.assert_called_once_with()


async def test_set_preset_mode_rejects_an_unknown_mode(hass: HomeAssistant) -> None:
    """An unknown preset is a user error with a translatable message."""
    session = make_session(hass)

    with pytest.raises(HomeAssistantError) as err:
        await session.set_preset_mode("Turbo")

    assert err.value.translation_domain == DOMAIN
    assert err.value.translation_key == "unknown_preset_mode"
    assert err.value.translation_placeholders == {"mode": "Turbo"}


async def test_set_preset_mode_reports_a_publish_failure(hass: HomeAssistant) -> None:
    """A failed command must reach the caller so Home Assistant can report it."""
    session = make_session(hass)

    class FailingMQTT:
        async def publish(self, packet: RamsesPacket) -> None:
            raise MQTTException("broker is offline")

    session.mqtt = FailingMQTT()  # pytest stub, duck typed on purpose

    with pytest.raises(HomeAssistantError) as err:
        await session.set_preset_mode("low")

    assert err.value.translation_domain == DOMAIN
    assert err.value.translation_key == "set_preset_failed"
    assert err.value.translation_placeholders == {
        "mode": "low",
        "error": "broker is offline",
    }
    assert len(session._send_queue) == 0


async def test_session_logs_that_no_devices_are_known(
    hass: HomeAssistant, caplog: pytest.LogCaptureFixture
) -> None:
    """Without stored devices the session says what it is waiting for."""
    with caplog.at_level(logging.INFO):
        make_session(hass, fan_id="", co2_id="")

    assert "fan has not yet been discovered" in caplog.text
    assert "CO2 sensor has not yet been discovered" in caplog.text
    assert "Using previously discovered fan id" not in caplog.text


async def test_setup_raises_when_mqtt_is_not_available(
    hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch
) -> None:
    """No MQTT client means a retryable setup failure."""
    monkeypatch.setattr(
        ramses_esp_module.mqtt_client,
        "async_wait_for_mqtt_client",
        AsyncMock(return_value=False),
    )
    session = make_session(hass)

    with pytest.raises(ConfigEntryNotReady) as err:
        await session.setup()

    assert err.value.translation_domain == DOMAIN
    assert err.value.translation_key == "mqtt_not_available"


async def test_setup_subscribes_and_initialises_known_devices(
    hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch
) -> None:
    """After a restart the session waits for the stick and then fetches state."""
    monkeypatch.setattr(
        ramses_esp_module.mqtt_client,
        "async_wait_for_mqtt_client",
        AsyncMock(return_value=True),
    )
    sleep = AsyncMock()
    monkeypatch.setattr(ramses_esp_module.asyncio, "sleep", sleep)
    session = make_session(hass, co2_id=CO2_ID)
    session.mqtt = Mock()
    session.mqtt.setup = AsyncMock()
    session.init_fan = AsyncMock()
    session.init_co2 = AsyncMock()

    await session.setup(event=Mock())

    sleep.assert_awaited_once_with(2)
    session.mqtt.setup.assert_awaited_once_with(
        session.handle_ramses_mqtt_message,
        session.handle_ramses_mqtt_version_message,
    )
    session.init_fan.assert_awaited_once_with()
    session.init_co2.assert_awaited_once_with()


async def test_setup_without_devices_only_subscribes(
    hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch
) -> None:
    """With neither device known the session waits for broadcasts."""
    monkeypatch.setattr(
        ramses_esp_module.mqtt_client,
        "async_wait_for_mqtt_client",
        AsyncMock(return_value=True),
    )
    session = make_session(hass, fan_id="", co2_id="")
    session.mqtt = Mock()
    session.mqtt.setup = AsyncMock()
    session.init_fan = AsyncMock()
    session.init_co2 = AsyncMock()

    await session.setup()

    session.init_fan.assert_not_awaited()
    session.init_co2.assert_not_awaited()


async def test_init_co2_stores_the_discovered_sensor(hass: HomeAssistant) -> None:
    """A newly discovered CO2 sensor is fetched without a reload."""
    session = make_session(hass, co2_id="")
    session.publish = AsyncMock()

    await session.init_co2(discovered_co2_id=RamsesID(CO2_ID))

    assert session.co2_id == CO2_ID
    sent = [call.args[0] for call in session.publish.await_args_list]
    assert [packet.code for packet in sent] == ["10E0", "1298", "31E0"]
    assert all(packet.dst_id == CO2_ID for packet in sent)


async def test_req_humidity_publishes_a_12a0_request(hass: HomeAssistant) -> None:
    """The poll interval asks the fan for humidity directly."""
    session = make_session(hass)
    session.publish = AsyncMock()

    await session.req_humidity()

    packet = session.publish.await_args.args[0]
    assert packet.code == "12A0"
    assert packet.dst_id == FAN_ID


async def test_handle_ramses_mqtt_message_logs_a_bad_envelope(
    hass: HomeAssistant, caplog: pytest.LogCaptureFixture
) -> None:
    """A malformed MQTT payload is reported instead of killing the subscription."""
    session = make_session(hass)
    msg = ReceiveMessage(
        topic=f"{MQTT_TOPIC}/{GATEWAY_ID}/rx",
        payload=b"not json",
        qos=0,
        retain=False,
        subscribed_topic=f"{MQTT_TOPIC}/{GATEWAY_ID}/rx",
        timestamp=0.0,
    )

    with caplog.at_level(logging.ERROR):
        await session.handle_ramses_mqtt_message(msg)

    assert "Failed to process Ramses-ESP MQTT message" in caplog.text


async def test_handle_ramses_mqtt_message_processes_and_logs_the_packet(
    hass: HomeAssistant,
) -> None:
    """A valid envelope is parsed and appended to the packet log."""
    session = make_session(hass)
    session._handle_ramses_packet = AsyncMock()
    session.packet_log = AsyncMock()
    envelope = {
        "ts": TIMESTAMP,
        "msg": f"044 RP --- {FAN_ID} {GATEWAY_ID} --:------ 31D9 003 000004",
    }
    msg = ReceiveMessage(
        topic=f"{MQTT_TOPIC}/{GATEWAY_ID}/rx",
        payload=json.dumps(envelope).encode(),
        qos=0,
        retain=False,
        subscribed_topic=f"{MQTT_TOPIC}/{GATEWAY_ID}/rx",
        timestamp=0.0,
    )

    await session.handle_ramses_mqtt_message(msg)

    session._handle_ramses_packet.assert_awaited_once_with(envelope)
    session.packet_log.assert_awaited_once_with(envelope)


async def test_remove_handler_stops_dispatching(hass: HomeAssistant) -> None:
    """Unloading a handler removes it from the handled set."""
    session = make_session(hass)
    session.add_handler("31D9", Mock())

    session.remove_handler("31D9")

    assert session.handled_codes == set()
    with pytest.raises(KeyError):
        session.remove_handler("31D9")


async def test_retry_exhaustion_drops_the_packet(
    hass: HomeAssistant, caplog: pytest.LogCaptureFixture
) -> None:
    """After the last retry the request is reported and forgotten."""
    session = make_session(hass)
    session.publish = AsyncMock()
    packet = Code12a0.get(RamsesID(GATEWAY_ID), RamsesID(FAN_ID))
    assert packet.expected_response is not None
    packet.expected_response.max_retries = 0
    session._send_queue.add(packet)

    with caplog.at_level(logging.WARNING):
        await session._retry_pending_request(packet)

    assert "Request timed out" in caplog.text
    assert session.pending_packets == 0
    session.publish.assert_not_awaited()


async def test_malformed_packet_is_logged_and_ignored(
    hass: HomeAssistant, caplog: pytest.LogCaptureFixture
) -> None:
    """A frame that cannot be parsed is reported and skipped."""
    session = make_session(hass)

    with caplog.at_level(logging.ERROR):
        await session._handle_ramses_packet({"ts": TIMESTAMP, "msg": "not a frame"})

    assert "Error parsing MQTT message" in caplog.text


def make_envelope(msg: str) -> dict[str, str]:
    """Build the JSON envelope the gateway delivers."""
    return {"ts": TIMESTAMP, "msg": msg}


async def test_unknown_code_is_decoded_generically(
    hass: HomeAssistant, caplog: pytest.LogCaptureFixture
) -> None:
    """A code without a decoder still reaches a registered handler."""
    session = make_session(hass)
    handler = Mock()
    session.add_handler("9999", handler)

    with caplog.at_level(logging.WARNING):
        await session._handle_ramses_packet(
            make_envelope(f"044 RP --- {FAN_ID} {GATEWAY_ID} --:------ 9999 002 0000")
        )

    assert "There is no class for code 9999" in caplog.text
    handler.assert_called_once()
    assert handler.call_args.args[0].values["_label"] == "Unsupported code"


async def test_a_packet_from_another_fan_is_ignored(hass: HomeAssistant) -> None:
    """A neighbouring Orcon's broadcast is not ours to handle."""
    session = make_session(hass)
    handler = Mock()
    session.add_handler("31D9", handler)

    await session._handle_ramses_packet(
        make_envelope(f"044 RP --- 29:999999 {GATEWAY_ID} --:------ 31D9 003 000004")
    )

    handler.assert_not_called()


async def test_unknown_31e0_from_the_fan_discovers_the_co2_sensor(
    hass: HomeAssistant,
) -> None:
    """A vent-demand frame addressed to the fan reveals the CO2 room sensor."""
    session = make_session(hass, co2_id="")
    handler = Mock()
    session.add_handler("31E0", handler)

    await session._handle_ramses_packet(
        make_envelope(
            f"044 I --- {CO2_ID} {FAN_ID} --:------ 31E0 008 0000000000641E00"
        )
    )

    assert session.co2_id == CO2_ID
    handler.assert_called_once()


async def test_a_packet_with_zero_signal_strength_is_ignored(
    hass: HomeAssistant,
) -> None:
    """A frame the gateway sent itself has no radio signal and no handler."""
    session = make_session(hass)
    handler = Mock()
    session.add_handler("31D9", handler)

    await session._handle_ramses_packet(
        make_envelope(f"000 I --- {FAN_ID} {GATEWAY_ID} --:------ 31D9 003 000004")
    )

    handler.assert_not_called()


async def test_a_response_removes_its_request_and_calls_the_handler(
    hass: HomeAssistant,
) -> None:
    """The matching response ends the retry and updates the coordinator."""
    session = make_session(hass)
    handler = Mock()
    session.add_handler("12A0", handler)
    request = Code12a0.get(RamsesID(GATEWAY_ID), RamsesID(FAN_ID))
    session._send_queue.add(request)

    await session._handle_ramses_packet(
        make_envelope(f"044 RP --- {FAN_ID} {GATEWAY_ID} --:------ 12A0 002 002F")
    )

    assert session.pending_packets == 0
    handler.assert_called_once()
    assert isinstance(handler.call_args.args[0], Code12a0)


async def test_packet_log_writes_and_rotates(
    hass: HomeAssistant, tmp_path: Path
) -> None:
    """The debug log rolls over instead of growing without bound."""
    session = make_session(hass)
    path = tmp_path / "packet.log"
    envelope = {
        "ts": TIMESTAMP,
        "msg": f"044 RP --- {FAN_ID} {GATEWAY_ID} --:------ 12A0 002 002F",
    }

    await session.packet_log(envelope, path=str(path), max_size=1)

    rotated = tmp_path / "packet.log.1"
    assert rotated.read_text().strip() == f"{envelope['ts']} {envelope['msg']}"
    assert path.read_text() == ""
    assert session._log_f is not None
    session._log_f.close()


async def test_packet_log_reports_an_unwritable_path(
    hass: HomeAssistant,
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A missing directory is logged instead of breaking packet handling."""
    session = make_session(hass)
    path = tmp_path / "missing" / "packet.log"

    with caplog.at_level(logging.ERROR):
        await session.packet_log({"ts": TIMESTAMP, "msg": "frame"}, path=str(path))

    assert "Error opening" in caplog.text
    assert session._log_f is None


async def test_packet_log_reports_a_failed_reopen(
    hass: HomeAssistant,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A reopen failure after rotation is logged, not raised to the caller."""
    session = make_session(hass)
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
        await session.packet_log(
            {"ts": TIMESTAMP, "msg": "frame"}, path=str(path), max_size=1
        )

    assert "Error reopening" in caplog.text
    assert session._log_f is not None
    assert session._log_f.closed


async def test_packet_log_ignores_a_failing_close(
    hass: HomeAssistant, tmp_path: Path
) -> None:
    """A file that cannot be closed must not stop the rotation."""
    session = make_session(hass)
    path = tmp_path / "packet.log"
    path.write_text("old")
    log_file = Mock()
    log_file.close.side_effect = OSError("already closed")
    session._log_f = log_file

    await session.packet_log(
        {"ts": TIMESTAMP, "msg": "frame"}, path=str(path), max_size=0
    )

    assert (tmp_path / "packet.log.1").exists()
    assert session._log_f is not None
    assert session._log_f is not log_file
    session._log_f.close()
