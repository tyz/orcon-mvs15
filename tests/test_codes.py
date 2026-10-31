"""Tests for the Ramses code decoders in codes.py."""

from __future__ import annotations

import pytest

from custom_components.orcon_mvs15.codes import (
    CODE_REGISTRY,
    Code,
    Code042f,
    Code1060,
    Code10e0,
    Code10e1,
    Code1298,
    Code12a0,
    Code1fc9,
    Code22f1,
    Code22f3,
    Code31d9,
    Code31e0,
)
from custom_components.orcon_mvs15.ramses_packet import RamsesID, RamsesPacket

TIMESTAMP = "2026-09-11T17:29:09.534250+02:00"
FAN_ID = "29:224547"
GATEWAY_ID = "18:149960"


def received(msg: str) -> RamsesPacket:
    """Build a packet the way the gateway delivers it."""
    return RamsesPacket(envelope={"ts": TIMESTAMP, "msg": msg})


def made(
    code: str,
    data: str,
    *,
    packet_type: str = "I",
    src_id: str = FAN_ID,
    dst_id: str = GATEWAY_ID,
    signal_strength: int = 68,
) -> RamsesPacket:
    """Build a packet the way the integration builds outgoing frames.

    Used for payload layouts that have no captured gateway frame in the
    repository yet; the field offsets are the ones documented in
    docs/protocol.md.
    """
    packet = RamsesPacket(
        src_id=RamsesID(src_id),
        dst_id=RamsesID(dst_id),
        type=packet_type,
        code=code,
        data=data,
    )
    packet.signal_strength = signal_strength
    return packet


def test_code_registry_maps_every_code_class() -> None:
    """Every decoder is reachable by its wire code and nothing is missing."""
    classes = [
        Code042f,
        Code1060,
        Code10e0,
        Code10e1,
        Code1298,
        Code12a0,
        Code1fc9,
        Code22f1,
        Code22f3,
        Code31d9,
        Code31e0,
    ]

    for code_class in classes:
        assert CODE_REGISTRY[code_class._code] is code_class
    assert len(CODE_REGISTRY) == len(classes)


def test_humidity_decodes_percent() -> None:
    """12A0 carries relative humidity in percent."""
    packet = received(f"044 RP --- {FAN_ID} {GATEWAY_ID} --:------ 12A0 002 002F")
    values = Code12a0(packet).values

    assert values["level"] == 47
    assert values["signal_strength"] == -44


def test_humidity_request_has_no_level() -> None:
    """A 12A0 status request carries no humidity yet."""
    packet = made("12A0", "00", packet_type="RQ", src_id=GATEWAY_ID, dst_id=FAN_ID)
    values = Code12a0(packet).values

    assert values["level"] is None


def test_co2_decodes_ppm() -> None:
    """1298 carries the CO2 concentration in ppm."""
    packet = received(f"044 RP --- {FAN_ID} {GATEWAY_ID} --:------ 1298 003 0001CD")
    values = Code1298(packet).values

    assert values["level"] == 0x01CD == 461


def test_co2_request_has_no_level() -> None:
    """A 1298 status request carries no concentration yet."""
    packet = made("1298", "00", packet_type="RQ", src_id=GATEWAY_ID, dst_id=FAN_ID)
    values = Code1298(packet).values

    assert values["level"] is None


@pytest.mark.parametrize(
    ("data", "preset"),
    [
        ("000004", "Away"),
        ("000104", "Low"),
        ("000204", "Medium"),
        ("000304", "High"),
        ("000404", "Auto"),
    ],
)
def test_fan_mode_decodes_preset(data: str, preset: str) -> None:
    """22F1 maps its three byte payload to a preset name."""
    packet = received(f"081  I --- 29:123456 29:654321 --:------ 22F1 003 {data}")

    assert Code22f1(packet).values["fan_mode"] == preset


def test_fan_mode_request_has_no_preset() -> None:
    """A 22F1 status request carries no mode yet."""
    packet = made("22F1", "00", packet_type="RQ", src_id=GATEWAY_ID, dst_id=FAN_ID)

    assert Code22f1(packet).values["fan_mode"] is None


def test_unknown_fan_mode_is_not_mapped() -> None:
    """An unrecognised payload yields no preset instead of guessing."""
    packet = received("081  I --- 29:123456 29:654321 --:------ 22F1 003 000504")

    assert Code22f1(packet).values["fan_mode"] is None


@pytest.mark.parametrize(
    ("preset", "code", "data"),
    [
        ("Auto", "22F1", "000404"),
        ("Low", "22F1", "000104"),
        ("Medium", "22F1", "000204"),
        ("High", "22F1", "000304"),
        ("Away", "22F1", "000004"),
        ("High (15m)", "22F3", "00020F03040000"),
        ("High (30m)", "22F3", "00021E03040000"),
        ("High (60m)", "22F3", "00023C03040000"),
    ],
)
def test_fan_mode_command(preset: str, code: str, data: str) -> None:
    """22F1 commands switch to 22F3 when the payload is a timed mode."""
    packet = Code22f1.set(RamsesID(GATEWAY_ID), RamsesID(FAN_ID), preset)

    assert packet.type == "I"
    assert packet.src_id == GATEWAY_ID
    assert packet.dst_id == FAN_ID
    assert packet.code == code
    assert packet.data == data
    assert packet.expected_response is not None
    assert packet.expected_response.type == "I"
    assert packet.expected_response.code == "31D9"
    assert packet.expected_response.src_id == FAN_ID


def test_fan_mode_command_rejects_unknown_preset() -> None:
    """Asking for a preset that does not exist is an error, not a silent no-op."""
    with pytest.raises(KeyError):
        Code22f1.set(RamsesID(GATEWAY_ID), RamsesID(FAN_ID), "Turbo")


def test_timed_fan_mode_decodes_preset() -> None:
    """22F3 uses the same preset table as 22F1."""
    packet = received(
        f"044  I --- {FAN_ID} {GATEWAY_ID} --:------ 22F3 007 00020F03040000"
    )

    assert Code22f3(packet).values["fan_mode"] == "High (15m)"


def test_timed_fan_mode_is_not_requestable() -> None:
    """The fan does not answer a 22F3 status request, so there is no getter."""
    with pytest.raises(NotImplementedError):
        Code22f3.get(RamsesID(GATEWAY_ID), RamsesID(FAN_ID))


@pytest.mark.parametrize(
    ("data", "preset"),
    [
        ("000000", "Away"),
        ("000001", "Low"),
        ("000002", "Medium"),
        ("000003", "High"),
        ("000004", "Auto"),
    ],
)
def test_fan_state_decodes_mode(data: str, preset: str) -> None:
    """31D9 maps the last byte to a preset and reports no fault."""
    packet = received(f"044 RP --- {FAN_ID} {GATEWAY_ID} --:------ 31D9 003 {data}")
    values = Code31d9(packet).values

    assert values["fan_mode"] == preset
    assert values["has_fault"] is False


def test_fan_state_decodes_fault_bit() -> None:
    """Bit 0x80 of the bitmap is the fault flag."""
    packet = received(f"044 RP --- {FAN_ID} {GATEWAY_ID} --:------ 31D9 003 008003")
    values = Code31d9(packet).values

    assert values["fan_mode"] == "High"
    assert values["has_fault"] is True


def test_fan_state_request_has_no_mode_or_fault() -> None:
    """A 31D9 status request carries no state yet."""
    packet = made("31D9", "00", packet_type="RQ", src_id=GATEWAY_ID, dst_id=FAN_ID)
    values = Code31d9(packet).values

    assert values["fan_mode"] is None
    assert values["has_fault"] is None


@pytest.mark.parametrize(
    ("data", "percentage", "unknown"),
    [
        ("0000000000000000", 0, "00"),
        ("0000C80000001E00", 100, "1E"),
        ("0000640000001E00", 50, "1E"),
        ("0000FE000000AA00", None, "AA"),
        ("0000FF0000006400", None, "64"),
    ],
)
def test_vent_demand_decodes_percentage(
    data: str, percentage: int | None, unknown: str
) -> None:
    """31E0 encodes vent demand as a half-percent byte."""
    packet = received(f"044  I --- 29:123456 {FAN_ID} --:------ 31E0 008 {data}")
    values = Code31e0(packet).values

    assert values["percentage"] == percentage
    assert values["unknown"] == unknown


def test_vent_demand_request_has_no_percentage() -> None:
    """A 31E0 status request carries no demand yet."""
    packet = made("31E0", "00", packet_type="RQ", src_id=GATEWAY_ID, dst_id=FAN_ID)
    values = Code31e0(packet).values

    assert values["percentage"] is None
    assert values["unknown"] is None


def test_device_info_decodes_fields() -> None:
    """10E0 exposes the device info fields used by the registry."""
    data = (
        "00"  # not decoded
        "0001"  # manufacturer group: HVAC
        "C8"  # manufacturer sub id: Orcon
        "26"  # product id
        "21"  # software version id
        "01"  # list version id
        "01"  # oem code / unknown
        "00"  # additional version A
        "00"  # additional version B
        "050107E9"  # date 2: 2025-01-05
        "020107E9"  # date 1: 2025-01-02
        "4F72636F6E204D56532D3135"  # "Orcon MVS-15"
        "00"  # NUL terminator
    )
    packet = made("10E0", data)
    values = Code10e0(packet).values

    assert values["manufacturer_group"] == "0001"
    assert values["manufacturer_sub_id"] == "C8"
    assert values["product_id"] == "26"
    assert values["software_ver_id"] == "21"
    assert values["list_ver_id"] == "01"
    assert values["sz_oem_code"] == "01"
    assert values["unknown"] == "01"
    assert values["additional_ver_a"] == "00"
    assert values["additional_ver_b"] == "00"
    assert values["date_2"].t_str == "2025-01-05"
    assert values["date_1"].t_str == "2025-01-02"
    assert values["description"] == "Orcon MVS-15"


def test_device_info_request_has_only_signal_strength() -> None:
    """A 10E0 status request carries no device info yet."""
    packet = made("10E0", "00", packet_type="RQ", src_id=GATEWAY_ID, dst_id=FAN_ID)
    values = Code10e0(packet).values

    assert values == {"_label": "Device info", "signal_strength": -68}


def test_device_id_request_has_no_device_id() -> None:
    """A 10E1 status request carries no device id yet."""
    packet = made("10E1", "00", packet_type="RQ", src_id=GATEWAY_ID, dst_id=FAN_ID)
    values = Code10e1(packet).values

    assert values["device_id"] is None


def test_battery_state_decodes_level_and_low_flag() -> None:
    """1060 reports a half-percent level and a low-battery flag."""
    values = Code1060(made("1060", "00C800000000")).values

    assert values["level"] == 100
    assert values["low"] is True

    values = Code1060(made("1060", "00C801000000")).values

    assert values["level"] == 100
    assert values["low"] is False


def test_battery_status_request_has_no_level() -> None:
    """A 1060 status request carries no battery state yet."""
    packet = made("1060", "00", packet_type="RQ", src_id=GATEWAY_ID, dst_id=FAN_ID)
    values = Code1060(packet).values

    assert values["level"] is None
    assert values["low"] is None


def test_rf_bind_decodes_zone_command_and_device() -> None:
    """1FC9 binds a device id in a zone."""
    packet = made("1FC9", "001FC906368E")
    values = Code1fc9(packet).values

    assert values["zone_idx"] == 0
    assert values["command"] == "1FC9"
    assert values["device_id"] == "01:145038"


def test_power_cycle_counter_decodes_counters() -> None:
    """042F reports the power cycle counters sent on power-up."""
    packet = received(f"044  I --- --:------ --:------ {FAN_ID} 042F 006 00004C004C00")
    values = Code042f(packet).values

    assert values["power_cycles"] == "0x004C"
    assert values["power_cycles_2"] == "0x004C"


@pytest.mark.parametrize(
    ("device_hex", "device_id"),
    [
        ("06368E", "01:145038"),
        ("280000", "10:000000"),
        ("", "--:------"),
        ("  ", "--:------"),
    ],
)
def test_device_hex_to_id(device_hex: str, device_id: str) -> None:
    """Device ids are device type plus a six digit device number."""
    code = Code(made("FFFF", "00"))

    assert code._dev_hex_to_id(device_hex) == device_id


def test_device_hex_to_id_ffffff_is_unverified() -> None:
    """FFFFFF currently renders as nine spaces; see AGENTS.md before changing it."""
    code = Code(made("FFFF", "00"))

    assert code._dev_hex_to_id("FFFFFF") == " " * 9
