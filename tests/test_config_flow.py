"""Tests for the config flow."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType

from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.orcon_mvs15.config_flow import _random_remote_id
from custom_components.orcon_mvs15.const import (
    CONF_GATEWAY_ID,
    CONF_MQTT_TOPIC,
    CONF_PACKET_LOG,
    CONF_REMOTE_FAKE,
    CONF_REMOTE_ID,
    CONF_TRANSPORT,
    CONF_USB_PORT,
    DOMAIN,
    STEP_MQTT,
    STEP_USB,
    TRANSPORT_MQTT,
    TRANSPORT_USB,
)

USB_MAC = "34:85:18:AA:B7:C8"
USB_GATEWAY_ID = "18:178120"
USB_PORT = "/dev/serial/by-id/usb-Espressif_USB_JTAG_serial_debug_unit-if00"


async def _choose(hass: HomeAssistant, result: dict, step: str) -> dict:
    """Pick a transport from the menu shown by the flow."""
    assert result["type"] is FlowResultType.MENU
    return await hass.config_entries.flow.async_configure(
        result["flow_id"], user_input={"next_step_id": step}
    )


async def test_user_flow_shows_the_transport_menu(hass: HomeAssistant) -> None:
    """The integration asks how the gateway is connected first."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )

    assert result["type"] is FlowResultType.MENU
    assert result["step_id"] == "user"
    assert result["menu_options"] == [STEP_MQTT, STEP_USB]


@pytest.mark.parametrize(
    ("step", "field"), [(STEP_MQTT, CONF_MQTT_TOPIC), (STEP_USB, CONF_USB_PORT)]
)
async def test_the_connection_forms_ask_only_for_the_connection(
    hass: HomeAssistant, step: str, field: str
) -> None:
    """The remote is generated, so the form must not ask for one."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await _choose(hass, result, step)

    schema = result["data_schema"].schema

    assert {marker.schema for marker in schema} == {field}


def test_a_generated_remote_id_fits_the_ramses_address(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A larger number would alias to another remote ID on the air."""
    monkeypatch.setattr(
        "custom_components.orcon_mvs15.config_flow.randbelow",
        lambda upper: upper - 1,
    )

    assert _random_remote_id() == "29:262143"


@pytest.mark.parametrize("step", [STEP_MQTT, STEP_USB])
async def test_a_new_entry_generates_a_fake_remote(
    hass: HomeAssistant, step: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A new entry stores a generated ID and enables automatic pairing."""
    monkeypatch.setattr(
        "custom_components.orcon_mvs15.config_flow._random_remote_id",
        lambda: "29:424242",
    )
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await _choose(hass, result, step)

    user_input: dict[str, object] = {}
    if step == STEP_MQTT:
        user_input[CONF_MQTT_TOPIC] = "RAMSES/GATEWAY"
    else:
        user_input[CONF_USB_PORT] = USB_PORT
    with patch(
        "custom_components.orcon_mvs15.config_flow.async_serial_number",
        AsyncMock(return_value=USB_MAC),
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], user_input=user_input
        )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], user_input={}
    )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_REMOTE_FAKE] is True
    assert result["data"][CONF_REMOTE_ID] == "29:424242"


async def test_mqtt_flow_creates_an_entry(
    hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The user data is stored after the discovery info step."""
    monkeypatch.setattr(
        "custom_components.orcon_mvs15.config_flow._random_remote_id",
        lambda: "29:424242",
    )
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await _choose(hass, result, STEP_MQTT)

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == STEP_MQTT

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        user_input={CONF_MQTT_TOPIC: "RAMSES/GATEWAY"},
    )

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "fan_discovery"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], user_input={}
    )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Orcon MVS-15"
    assert result["data"] == {
        CONF_REMOTE_FAKE: True,
        CONF_REMOTE_ID: "29:424242",
        CONF_MQTT_TOPIC: "RAMSES/GATEWAY",
        CONF_TRANSPORT: TRANSPORT_MQTT,
    }


async def test_reconfigure_keeps_a_generated_remote_id(
    hass: HomeAssistant,
) -> None:
    """Reconfiguring the connection must not orphan the paired fake remote."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            CONF_REMOTE_FAKE: True,
            CONF_REMOTE_ID: "29:424242",
            CONF_MQTT_TOPIC: "RAMSES/GATEWAY",
            CONF_TRANSPORT: TRANSPORT_MQTT,
        },
    )
    entry.add_to_hass(hass)
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={
            "source": config_entries.SOURCE_RECONFIGURE,
            "entry_id": entry.entry_id,
        },
    )
    result = await _choose(hass, result, STEP_MQTT)

    with patch.object(hass.config_entries, "async_schedule_reload"):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            user_input={
                CONF_MQTT_TOPIC: "RAMSES/NEW",
            },
        )

    assert result["type"] is FlowResultType.ABORT
    assert entry.data[CONF_REMOTE_FAKE] is True
    assert entry.data[CONF_REMOTE_ID] == "29:424242"


async def test_reconfigure_keeps_a_manual_remote(
    hass: HomeAssistant,
) -> None:
    """An entry from before the generated remote must keep its own remote."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            CONF_REMOTE_FAKE: False,
            CONF_REMOTE_ID: "29:123456",
            CONF_MQTT_TOPIC: "RAMSES/GATEWAY",
            CONF_TRANSPORT: TRANSPORT_MQTT,
        },
    )
    entry.add_to_hass(hass)
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={
            "source": config_entries.SOURCE_RECONFIGURE,
            "entry_id": entry.entry_id,
        },
    )
    result = await _choose(hass, result, STEP_MQTT)

    with patch.object(hass.config_entries, "async_schedule_reload"):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            user_input={
                CONF_MQTT_TOPIC: "RAMSES/NEW",
            },
        )

    assert result["type"] is FlowResultType.ABORT
    assert entry.data[CONF_REMOTE_FAKE] is False
    assert entry.data[CONF_REMOTE_ID] == "29:123456"


async def test_usb_flow_derives_the_gateway_from_the_serial_number(
    hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A USB entry stores the port and the gateway id derived from the MAC."""
    monkeypatch.setattr(
        "custom_components.orcon_mvs15.config_flow._random_remote_id",
        lambda: "29:424242",
    )
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await _choose(hass, result, STEP_USB)

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == STEP_USB

    with patch(
        "custom_components.orcon_mvs15.config_flow.async_serial_number",
        AsyncMock(return_value=USB_MAC),
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            user_input={CONF_USB_PORT: USB_PORT},
        )

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "fan_discovery"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], user_input={}
    )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"] == {
        CONF_REMOTE_FAKE: True,
        CONF_REMOTE_ID: "29:424242",
        CONF_TRANSPORT: TRANSPORT_USB,
        CONF_USB_PORT: USB_PORT,
        CONF_GATEWAY_ID: USB_GATEWAY_ID,
    }


async def test_usb_flow_requires_a_port(hass: HomeAssistant) -> None:
    """The USB form cannot be submitted without a serial port."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await _choose(hass, result, STEP_USB)

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        user_input={CONF_USB_PORT: "   "},
    )

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == STEP_USB
    assert result["errors"] == {CONF_USB_PORT: "usb_port_required"}


async def test_usb_flow_rejects_a_port_without_a_serial_number(
    hass: HomeAssistant,
) -> None:
    """The gateway id cannot be guessed when the port has no USB serial."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await _choose(hass, result, STEP_USB)

    with patch(
        "custom_components.orcon_mvs15.config_flow.async_serial_number",
        AsyncMock(return_value=None),
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            user_input={CONF_USB_PORT: USB_PORT},
        )

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == STEP_USB
    assert result["errors"] == {"base": "gateway_id_unavailable"}


async def test_usb_flow_survives_a_failed_serial_lookup(hass: HomeAssistant) -> None:
    """A failing port scan becomes a form error, not a broken flow."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await _choose(hass, result, STEP_USB)

    with patch(
        "custom_components.orcon_mvs15.config_flow.async_serial_number",
        AsyncMock(side_effect=OSError("no udev")),
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            user_input={CONF_USB_PORT: USB_PORT},
        )

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == STEP_USB
    assert result["errors"] == {"base": "gateway_id_unavailable"}


async def test_duplicate_mqtt_topic_is_rejected(hass: HomeAssistant) -> None:
    """The same gateway cannot be configured twice under another remote ID."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            CONF_REMOTE_ID: "29:123456",
            CONF_MQTT_TOPIC: "RAMSES/GATEWAY",
            CONF_TRANSPORT: TRANSPORT_MQTT,
        },
    )
    entry.add_to_hass(hass)
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await _choose(hass, result, STEP_MQTT)

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        user_input={
            CONF_MQTT_TOPIC: "RAMSES/GATEWAY",
        },
    )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_duplicate_usb_port_is_rejected(hass: HomeAssistant) -> None:
    """One serial port cannot back two entries."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            CONF_REMOTE_ID: "29:123456",
            CONF_TRANSPORT: TRANSPORT_USB,
            CONF_USB_PORT: USB_PORT,
            CONF_GATEWAY_ID: USB_GATEWAY_ID,
        },
    )
    entry.add_to_hass(hass)
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await _choose(hass, result, STEP_USB)

    with patch(
        "custom_components.orcon_mvs15.config_flow.async_serial_number",
        AsyncMock(return_value=USB_MAC),
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            user_input={CONF_USB_PORT: USB_PORT},
        )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_reconfigure_updates_the_connection_settings(
    hass: HomeAssistant,
) -> None:
    """The MQTT topic can be corrected after setup."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            CONF_REMOTE_ID: "29:123456",
            CONF_MQTT_TOPIC: "RAMSES/GATEWAY",
            CONF_TRANSPORT: TRANSPORT_MQTT,
        },
    )
    entry.add_to_hass(hass)
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={
            "source": config_entries.SOURCE_RECONFIGURE,
            "entry_id": entry.entry_id,
        },
    )

    assert result["type"] is FlowResultType.MENU
    assert result["step_id"] == "reconfigure"

    result = await _choose(hass, result, STEP_MQTT)
    assert result["step_id"] == STEP_MQTT

    with patch.object(hass.config_entries, "async_schedule_reload") as schedule:
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            user_input={
                CONF_MQTT_TOPIC: "RAMSES/NEW",
            },
        )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
    assert entry.data[CONF_REMOTE_ID] == "29:123456"
    assert entry.data[CONF_MQTT_TOPIC] == "RAMSES/NEW"
    assert entry.data[CONF_TRANSPORT] == TRANSPORT_MQTT
    schedule.assert_called_once_with(entry.entry_id)


async def test_reconfigure_can_switch_to_usb(hass: HomeAssistant) -> None:
    """Switching transports replaces the MQTT gateway with the USB one."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            CONF_REMOTE_ID: "29:123456",
            CONF_MQTT_TOPIC: "RAMSES/GATEWAY",
            CONF_TRANSPORT: TRANSPORT_MQTT,
            CONF_GATEWAY_ID: "18:149960",
        },
    )
    entry.add_to_hass(hass)
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={
            "source": config_entries.SOURCE_RECONFIGURE,
            "entry_id": entry.entry_id,
        },
    )
    result = await _choose(hass, result, STEP_USB)

    with (
        patch(
            "custom_components.orcon_mvs15.config_flow.async_serial_number",
            AsyncMock(return_value=USB_MAC),
        ),
        patch.object(hass.config_entries, "async_schedule_reload"),
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            user_input={CONF_USB_PORT: USB_PORT},
        )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
    assert entry.data[CONF_TRANSPORT] == TRANSPORT_USB
    assert entry.data[CONF_USB_PORT] == USB_PORT
    assert entry.data[CONF_GATEWAY_ID] == USB_GATEWAY_ID


async def test_switching_back_to_mqtt_clears_the_usb_gateway(
    hass: HomeAssistant,
) -> None:
    """The USB MAC-derived gateway id must not survive a switch to MQTT."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            CONF_REMOTE_ID: "29:123456",
            CONF_TRANSPORT: TRANSPORT_USB,
            CONF_USB_PORT: USB_PORT,
            CONF_GATEWAY_ID: USB_GATEWAY_ID,
        },
    )
    entry.add_to_hass(hass)
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={
            "source": config_entries.SOURCE_RECONFIGURE,
            "entry_id": entry.entry_id,
        },
    )
    result = await _choose(hass, result, STEP_MQTT)

    with patch.object(hass.config_entries, "async_schedule_reload"):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            user_input={
                CONF_MQTT_TOPIC: "RAMSES/GATEWAY",
            },
        )

    assert result["type"] is FlowResultType.ABORT
    assert entry.data[CONF_TRANSPORT] == TRANSPORT_MQTT
    assert entry.data[CONF_GATEWAY_ID] == ""


async def test_reconfigure_may_keep_the_current_topic(hass: HomeAssistant) -> None:
    """The duplicate check ignores the entry that is being reconfigured."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            CONF_REMOTE_ID: "29:123456",
            CONF_MQTT_TOPIC: "RAMSES/GATEWAY",
            CONF_TRANSPORT: TRANSPORT_MQTT,
        },
    )
    entry.add_to_hass(hass)
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={
            "source": config_entries.SOURCE_RECONFIGURE,
            "entry_id": entry.entry_id,
        },
    )
    result = await _choose(hass, result, STEP_MQTT)

    with patch.object(hass.config_entries, "async_schedule_reload"):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            user_input={
                CONF_MQTT_TOPIC: "RAMSES/GATEWAY",
            },
        )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
    assert entry.data[CONF_REMOTE_ID] == "29:123456"
    assert entry.data[CONF_MQTT_TOPIC] == "RAMSES/GATEWAY"


@pytest.mark.parametrize(
    ("topic", "error"),
    [
        ("", "mqtt_topic_required"),
        ("   ", "mqtt_topic_required"),
        (" RAMSES/GATEWAY", "mqtt_topic_whitespace"),
        ("RAMSES/GATEWAY ", "mqtt_topic_whitespace"),
        ("RAMSES/+", "mqtt_topic_wildcard"),
        ("RAMSES/GATEWAY/#", "mqtt_topic_wildcard"),
        ("+", "mqtt_topic_wildcard"),
    ],
)
async def test_user_flow_rejects_an_unusable_topic(
    hass: HomeAssistant, topic: str, error: str
) -> None:
    """A blank topic, a wildcard or surrounding spaces never reaches setup."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await _choose(hass, result, STEP_MQTT)

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        user_input={
            CONF_MQTT_TOPIC: topic,
        },
    )

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == STEP_MQTT
    assert result["errors"] == {CONF_MQTT_TOPIC: error}


async def test_reconfigure_rejects_a_wildcard_topic(hass: HomeAssistant) -> None:
    """The reconfigure flow cannot store a topic that subscribes too widely."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            CONF_REMOTE_ID: "29:123456",
            CONF_MQTT_TOPIC: "RAMSES/GATEWAY",
            CONF_TRANSPORT: TRANSPORT_MQTT,
        },
    )
    entry.add_to_hass(hass)
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={
            "source": config_entries.SOURCE_RECONFIGURE,
            "entry_id": entry.entry_id,
        },
    )
    result = await _choose(hass, result, STEP_MQTT)

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        user_input={
            CONF_MQTT_TOPIC: "RAMSES/+",
        },
    )

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == STEP_MQTT
    assert result["errors"] == {CONF_MQTT_TOPIC: "mqtt_topic_wildcard"}
    assert entry.data[CONF_MQTT_TOPIC] == "RAMSES/GATEWAY"


async def test_options_flow_keeps_the_packet_log_off_by_default(
    hass: HomeAssistant,
) -> None:
    """Submitting the empty options form stores the disabled default."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            CONF_REMOTE_ID: "29:123456",
            CONF_MQTT_TOPIC: "RAMSES/GATEWAY",
        },
    )
    entry.add_to_hass(hass)
    result = await hass.config_entries.options.async_init(entry.entry_id)

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "init"

    with patch.object(hass.config_entries, "async_schedule_reload") as schedule:
        result = await hass.config_entries.options.async_configure(
            result["flow_id"], user_input={}
        )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options == {CONF_PACKET_LOG: False}
    schedule.assert_called_once_with(entry.entry_id)


async def test_options_flow_can_enable_the_packet_log(hass: HomeAssistant) -> None:
    """The options flow turns the debugging packet log on."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            CONF_REMOTE_ID: "29:123456",
            CONF_MQTT_TOPIC: "RAMSES/GATEWAY",
        },
    )
    entry.add_to_hass(hass)
    result = await hass.config_entries.options.async_init(entry.entry_id)

    with patch.object(hass.config_entries, "async_schedule_reload") as schedule:
        result = await hass.config_entries.options.async_configure(
            result["flow_id"], user_input={CONF_PACKET_LOG: True}
        )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options == {CONF_PACKET_LOG: True}
    schedule.assert_called_once_with(entry.entry_id)


async def test_a_switched_entry_does_not_block_its_old_topic(
    hass: HomeAssistant,
) -> None:
    """A USB entry remembers its old MQTT topic but is not an MQTT entry."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            CONF_REMOTE_ID: "29:123456",
            CONF_TRANSPORT: TRANSPORT_USB,
            CONF_USB_PORT: USB_PORT,
            CONF_GATEWAY_ID: USB_GATEWAY_ID,
            CONF_MQTT_TOPIC: "RAMSES/GATEWAY",
        },
    )
    entry.add_to_hass(hass)
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await _choose(hass, result, STEP_MQTT)

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        user_input={
            CONF_MQTT_TOPIC: "RAMSES/GATEWAY",
        },
    )

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "fan_discovery"


async def test_a_switched_entry_does_not_block_its_old_port(
    hass: HomeAssistant,
) -> None:
    """An MQTT entry remembers its old USB port but is not a USB entry."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            CONF_REMOTE_ID: "29:123456",
            CONF_TRANSPORT: TRANSPORT_MQTT,
            CONF_MQTT_TOPIC: "RAMSES/GATEWAY",
            CONF_USB_PORT: USB_PORT,
        },
    )
    entry.add_to_hass(hass)
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await _choose(hass, result, STEP_USB)

    with patch(
        "custom_components.orcon_mvs15.config_flow.async_serial_number",
        AsyncMock(return_value=USB_MAC),
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            user_input={CONF_USB_PORT: USB_PORT},
        )

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "fan_discovery"


async def test_reconfigure_keeps_the_gateway_when_the_lookup_fails(
    hass: HomeAssistant,
) -> None:
    """A transient USB lookup failure must not erase the proven gateway id."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            CONF_REMOTE_ID: "29:123456",
            CONF_TRANSPORT: TRANSPORT_USB,
            CONF_USB_PORT: USB_PORT,
            CONF_GATEWAY_ID: USB_GATEWAY_ID,
        },
    )
    entry.add_to_hass(hass)
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={
            "source": config_entries.SOURCE_RECONFIGURE,
            "entry_id": entry.entry_id,
        },
    )
    result = await _choose(hass, result, STEP_USB)

    with (
        patch(
            "custom_components.orcon_mvs15.config_flow.async_serial_number",
            AsyncMock(side_effect=OSError("no udev")),
        ),
        patch.object(hass.config_entries, "async_schedule_reload"),
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            user_input={CONF_USB_PORT: USB_PORT},
        )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
    assert entry.data[CONF_GATEWAY_ID] == USB_GATEWAY_ID
