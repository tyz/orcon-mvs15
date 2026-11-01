"""Regression tests over frames recorded from a real Orcon installation.

The files in ``tests/fixtures`` are gateway frames with the timestamp
stripped; ``tests/fixtures/README.md`` records where they came from. They keep
the frames that a synthetic payload cannot prove: the real device info strings,
the fault bitmaps, the remote presets and the gateway echoes of our own
commands.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceRegistry

from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.orcon_mvs15.codes import CODE_REGISTRY
from custom_components.orcon_mvs15.const import DOMAIN
from custom_components.orcon_mvs15.handlers import DataHandlers
from custom_components.orcon_mvs15.ramses_esp import RamsesESP
from custom_components.orcon_mvs15.ramses_packet import RamsesID

from recorded_frames import (
    FIXTURES,
    decode,
    envelope,
    envelopes,
    frames,
    packet_from,
    packet_with_data,
    packets,
)

FAN_ID = "29:224547"
CO2_ID = "32:093959"
GATEWAY_ID = "18:149960"
REMOTE_ID = "29:163058"

FIXTURE_FILES = sorted(path.name for path in FIXTURES.glob("*.log"))


def make_session(hass: HomeAssistant, co2_id: str = CO2_ID) -> RamsesESP:
    """Build a session for the recorded installation."""
    return RamsesESP(
        hass=hass,
        mqtt=Mock(),
        remote_id=RamsesID(REMOTE_ID),
        fan_id=RamsesID(FAN_ID),
        co2_id=RamsesID(co2_id),
        gateway_id=RamsesID(GATEWAY_ID),
        config_entry_id="test_entry",
    )


def make_handlers(hass: HomeAssistant) -> tuple[MockConfigEntry, DataHandlers]:
    """Build handlers for an entry that can own devices."""
    entry = MockConfigEntry(domain=DOMAIN, data={})
    entry.add_to_hass(hass)
    entry.runtime_data = SimpleNamespace(
        co2_coordinator=SimpleNamespace(data={}),
        fan_coordinator=SimpleNamespace(data={}),
    )
    return entry, DataHandlers(hass, entry)


def test_the_fixtures_cover_the_codes_the_installation_sends() -> None:
    """The capture exercises every code this installation actually uses."""
    recorded = {packet.code for name in FIXTURE_FILES for packet in packets(name)}

    assert recorded == {
        "042F",
        "10E0",
        "1298",
        "12A0",
        "22F1",
        "22F3",
        "31D9",
        "31E0",
    }


@pytest.mark.parametrize("name", FIXTURE_FILES)
def test_every_recorded_frame_parses_and_decodes(name: str) -> None:
    """No recorded frame crashes the parser or falls back to the generic code."""
    recorded = packets(name)

    assert recorded
    for packet in recorded:
        assert packet.code in CODE_REGISTRY
        assert decode(packet).values["_label"] != "Unsupported code"


def test_recorded_power_up_frames_name_the_fan() -> None:
    """The captured 042F broadcasts name the fan in ann_id and count cycles."""
    recorded = packets("power_up.log")

    assert [packet.ann_id for packet in recorded] == [
        FAN_ID,
        FAN_ID,
        "29:224179",
        "29:223489",
    ]
    assert decode(recorded[0]).values["power_cycles"] == "0x0051"
    assert decode(recorded[0]).values["power_cycles_2"] == "0x0051"


@pytest.mark.parametrize(
    ("data", "mode"),
    [
        ("000004", "auto"),
        ("000002", "medium"),
        ("000003", "high"),
        ("000000", "away"),
        ("000001", "low"),
    ],
)
def test_recorded_fan_state_decodes_the_mode(data: str, mode: str) -> None:
    """Every mode the installation can report is decoded."""
    payload = decode(packet_with_data("fan_state.log", data))

    assert payload.values["fan_mode"] == mode
    assert payload.values["has_fault"] is False


@pytest.mark.parametrize(
    ("data", "mode"),
    [("008001", "low"), ("008008", "08"), ("008078", "78")],
)
def test_recorded_fan_state_decodes_the_fault_bit(data: str, mode: str) -> None:
    """The fault bit is independent of the mode, including an unknown one."""
    payload = decode(packet_with_data("fan_state.log", data))

    assert payload.values["has_fault"] is True
    assert payload.values["fan_mode"] == mode


@pytest.mark.parametrize(
    ("data", "mode"),
    [
        ("000404", "auto"),
        ("000104", "low"),
        ("000204", "medium"),
        ("000304", "high"),
        ("000004", "away"),
    ],
)
def test_recorded_fan_mode_decodes_the_preset(data: str, mode: str) -> None:
    """A real remote press maps to the same preset as a reported fan state."""
    payload = decode(packet_with_data("fan_modes.log", data))

    assert payload.values["fan_mode"] == mode


@pytest.mark.parametrize(
    ("data", "mode"),
    [
        ("00020F03040000", "high_15m"),
        ("00021E03040000", "high_30m"),
        ("00023C03040000", "high_60m"),
    ],
)
def test_recorded_timed_fan_mode_decodes_the_preset(data: str, mode: str) -> None:
    """The 7-byte timed presses keep their duration in the preset name."""
    payload = decode(packet_with_data("fan_modes.log", data))

    assert payload.values["fan_mode"] == mode


def test_recorded_signal_strength_is_negated_once() -> None:
    """The gateway sends the RSSI positive; the payload exposes it negative."""
    packet = packet_with_data("fan_modes.log", "000404")

    assert packet.signal_strength == 81
    assert decode(packet).values["signal_strength"] == -81


@pytest.mark.parametrize(
    ("data", "percentage", "unknown"),
    [
        ("0000C8000100AA00", 100, "AA"),
        ("0000000001006400", 0, "64"),
        ("0000000001001E00", 0, "1E"),
        ("0000C6000100AA00", 99, "AA"),
        ("000092000100AA00", 73, "AA"),
        ("000006000100AA00", 3, "AA"),
    ],
)
def test_recorded_vent_demand_decodes_the_percentage(
    data: str, percentage: int, unknown: str
) -> None:
    """Both half-percent bytes and the undecoded byte are real field values."""
    payload = decode(packet_with_data("vent_demand.log", data))

    assert payload.values["percentage"] == percentage
    assert payload.values["unknown"] == unknown


@pytest.mark.parametrize(
    ("data", "level"),
    [("000182", 386), ("0003F8", 1016), ("000424", 1060)],
)
def test_recorded_co2_decodes_the_ppm(data: str, level: int) -> None:
    """The whole payload is the concentration, request or broadcast."""
    payload = decode(packet_with_data("co2_levels.log", data))

    assert payload.values["level"] == level


def test_recorded_co2_request_has_no_level() -> None:
    """A one-byte request carries no concentration."""
    packet = packet_with_data("co2_levels.log", "00")

    assert packet.length == 1
    assert decode(packet).values["level"] is None


@pytest.mark.parametrize(("data", "level"), [("003B", 59), ("0029", 41), ("0042", 66)])
def test_recorded_humidity_decodes_the_percent(data: str, level: int) -> None:
    """The two-byte humidity response is a percentage, not a half-percent."""
    payload = decode(packet_with_data("humidity.log", data))

    assert payload.values["level"] == level


def test_recorded_humidity_request_has_no_level() -> None:
    """A one-byte request carries no humidity."""
    packet = packet_with_data("humidity.log", "00")

    assert packet.length == 1
    assert decode(packet).values["level"] is None


def test_recorded_device_info_describes_the_real_devices() -> None:
    """The captured 10E0 payloads keep their firmware and model strings."""
    fan = decode(packet_from("device_info.log", FAN_ID, "10E0"))
    co2 = decode(packet_from("device_info.log", CO2_ID, "10E0"))

    assert fan.values["manufacturer_sub_id"] == "C8"
    assert fan.values["product_id"] == "26"
    assert fan.values["software_ver_id"] == "0D"
    assert fan.values["description"] == "VMC-15RP01"

    assert co2.values["product_id"] == "51"
    assert co2.values["software_ver_id"] == "0B"
    assert co2.values["description"] == "VMS-15CM17"


def test_recorded_product_27_is_not_a_fan() -> None:
    """A neighbouring Orcon system reports its own model and is not a fan."""
    payload = decode(packet_from("device_info.log", "29:167925", "10E0"))

    assert payload.values["product_id"] == "27"
    assert payload.values["description"] == "VMN-15LF01"


async def test_recorded_device_info_updates_the_fan_device(
    hass: HomeAssistant, device_registry: DeviceRegistry
) -> None:
    """The fan's real device info is accepted and stored on its device."""
    entry, handlers = make_handlers(hass)
    device = device_registry.async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={(DOMAIN, FAN_ID)},
    )

    handlers._device_info_handler(
        decode(packet_from("device_info.log", FAN_ID, "10E0"))
    )

    updated = device_registry.async_get(device.id)
    assert updated is not None
    assert updated.sw_version == "13"
    assert updated.model_id == "VMC-15RP01"


async def test_the_recorded_restart_reaches_the_handlers(hass: HomeAssistant) -> None:
    """Every frame of the captured restart is accepted and dispatched."""
    session = make_session(hass)
    seen: list[str] = []
    for code in ("042F", "10E0", "31D9", "12A0"):
        session.add_handler(code, lambda payload: seen.append(payload.packet.code))

    for item in envelopes("startup.log"):
        await session._handle_ramses_packet(item)

    # The gateway's own requests have signal strength 000 and are not dispatched.
    assert seen == ["042F", "10E0", "10E0", "31D9", "12A0", "31D9"]


async def test_the_recorded_power_up_ignores_the_neighbour(hass: HomeAssistant) -> None:
    """A neighbouring fan's power-up does not replace the configured fan."""
    session = make_session(hass)
    handler = Mock()
    session.add_handler("042F", handler)

    for item in envelopes("power_up.log"):
        await session._handle_ramses_packet(item)

    assert handler.call_count == 4
    assert session.fan_id == FAN_ID


async def test_the_recorded_command_echo_is_ignored(hass: HomeAssistant) -> None:
    """The gateway echoes our own command with signal strength 000."""
    session = make_session(hass)
    handler = Mock()
    session.add_handler("22F1", handler)

    echo = next(
        frame
        for frame in frames("fan_modes.log")
        if frame.startswith("000 ") and frame.endswith("000204")
    )
    press = next(
        frame
        for frame in frames("fan_modes.log")
        if frame.startswith("081 ") and frame.endswith("000404")
    )

    await session._handle_ramses_packet(envelope(echo))
    handler.assert_not_called()

    await session._handle_ramses_packet(envelope(press))
    handler.assert_called_once()
    assert handler.call_args.args[0].values["fan_mode"] == "auto"
