# Orcon MVS-15

[![CI](https://github.com/tyz/orcon-mvs15/actions/workflows/ci.yml/badge.svg)](https://github.com/tyz/orcon-mvs15/actions/workflows/ci.yml)
[![CodeQL](https://github.com/tyz/orcon-mvs15/actions/workflows/github-code-scanning/codeql/badge.svg)](https://github.com/tyz/orcon-mvs15/actions/workflows/github-code-scanning/codeql)

(Work in progress, currently requires a working 15RF wireless remote until pairing a fake remote is implemented)

Home Assistant integration for the [Orcon MVS-15 fan](https://orcon.nl/mechanische-ventilatie/),
the (optional) wired `CO2 ruimtesensor 15RF` with its CO₂ sensor and the
(optional) `Afstandsbediening 15RF` wireless remote.

Uses MQTT or a USB serial connection and a
[Ramses ESP stick](https://indalo-tech.onlineweb.shop/product/ramses-esp) to
communicate with the fan.

I used [ramses_rf](https://github.com/zxdavb/ramses_rf) and [this wiki](https://github.com/zxdavb/ramses_protocol/wiki) for some code/inspiration/help.

## Features

- Creates a fan entity with all supported presets (Away, Auto, Low, Medium, High + High 15/30/60m timed modes)
- Exposes the end and the remaining minutes of a timed preset while it runs
- Optional packet log for debugging, disabled by default
- Auto-detects the fan
- Auto-detects the wired `CO2 ruimtesensor 15RF` and creates an HA sensor
- Auto-detects the fan's humidity sensor and creates an HA sensor
- Creates a binary sensor that triggers when the fan reports a fault
- The fan reported mode is used to update the fan's current preset in HA, so it
  will immediately notice when the mode was changed by a 15RF wireless remote, for example

## Supported devices

- Orcon MVS-15 ventilation unit (fan, humidity sensor and fault state). The
  sold model name is `MVS-15xxx`, where `xxx` names the fitted humidity or CO₂
  option, for example `MVS-15RH CO2B`.
- Orcon VMC-15RPS34 ventilation unit (same packets as the MVS-15; it reports
  product ID `5F`)
- Orcon `CO2 ruimtesensor 15RF` wired CO₂ sensor (product ID `51`)
- Orcon `Afstandsbediening 15RF` wireless remote
- Ramses ESP gateway running the Ramses II firmware over MQTT or USB

## TODO

- Set up a fake remote and pair it with the fan

## Install

You can install this integration by adding its GitHub repository to the HACS
configuration under `Custom repositories`. Then install it in HACS, and add the
`Orcon MVS-15` integration in `Settings > Devices & services`.

## Installation parameters

The setup form first asks how the Ramses ESP is connected, then for the remote
ID and the transport settings:

- **Remote ID** — the Ramses ID of the 15RF wireless remote that sends commands
  to the fan, for example `29:163058`. If you do not know it yet, use a fake ID
  and follow [Fan ID](#fan-id).
- **MQTT topic prefix** (MQTT connection) — the base topic of the Ramses ESP
  gateway, for example `RAMSES/GATEWAY`. The integration discovers the gateway
  on `<prefix>/+` and then exchanges packets on `<prefix>/<gateway>/rx` and
  `<prefix>/<gateway>/tx`.
- **Serial port** (USB connection) — the port of the Ramses ESP, picked from the
  ports Home Assistant knows. The stick exposes two interfaces; use interface
  `0`, the one whose description ends in `-if00`. The integration reads the
  board's USB serial number to derive the gateway ID, so there is nothing else
  to enter.

The USB descriptor is shared by every ESP32-S3 board, so Home Assistant cannot
discover the stick reliably. USB setup is a manual port choice instead.

## Fan ID

If you don't know the ID of the 15RF wireless remote then use a fake ID (e.g. `29:123456`).
Enable the packet log first (see [Options](#options)), then tail the
`packet.log` file in the Home Assistant config directory, and press the
`auto` button on the remote a couple of times. The resulting log entries should
look something like this:

```text
2026-09-11T17:29:09.534250+02:00 081  I --- 29:123456 29:654321 --:------ 22F1 003 000404
```

The remote's ID in this example is `29:123456`.

## Auto-discovery

1. Install and configure the integration. The `remote ID` it asks for is the 15RF wireless remote's ID.
1. Turn the fan off and on again
1. The fan will be discovered by a startup message (042F) it sends out
1. The state of the humidity sensor (part of the fan) will be requested (12A0), and will be set up in HA if it responds
1. The wired `CO2 ruimtesensor 15RF` will be discovered as soon as it sends a vent demand message (31E0) to the above fan (might take a while)

## Reconfiguring

If the remote ID, MQTT topic prefix or serial port is wrong, open the
integration's menu in `Settings > Devices & services` and choose
**Reconfigure**. Choose the connection you want to change; the other discovered
IDs are kept and the entry reloads after the change. Switching between MQTT and
USB replaces the gateway ID, because the two gateways are different devices.

## Options

Open the integration's menu in `Settings > Devices & services` and choose
**Configure** to change the optional diagnostics. **Write packets to
packet.log** is off by default. When enabled, every received packet is appended
to `/config/packet.log`, which rolls over at 10 MB. Use it to find the remote ID
or to troubleshoot, then turn it off again.

## Timed modes

The `high_15m`, `high_30m` and `high_60m` presets start a countdown in the
integration. While it runs, the fan entity exposes `timer_end` (an ISO 8601
timestamp) and `timer_remaining` (the number of whole minutes left). Any new
mode command, from Home Assistant or the remote, replaces the previous
countdown. The preset itself still follows the next state the fan reports.

## Lovelace

```yaml
type: tile
entity: fan.orcon_mvs_15_fan
show_entity_picture: false
hide_state: true
vertical: false
features_position: inline
features:
  - type: fan-preset-modes
    style: dropdown
```

## Alert on fault

```
alert:
  orcon_mvs_15_fault:
    title: Orcon MVS-15 fault
    name: The fan reported a fault
    done_message: The fan fault was cleared
    entity_id: binary_sensor.orcon_mvs_15_fan_fault
    repeat: 1440
    notifiers:
      - persistent_notification  # create an alert in the web UI
      - mobile_app_your_phone  # send a notification through the companion app
```

Check the LED on the fan unit if it reports a fault:

| Flashing red | Error                         |
| -------------|-------------------------------|
| 1x           | Motor not running             |
| 2x           | No value from humidity sensor |
| 3x           | RF communication failure      |

## Automations

The fan presets are useful automation targets. This example boosts the fan to
`high` when the CO₂ level stays above 1200 ppm for two minutes, and returns it
to `auto` after ten minutes below 800 ppm. The hysteresis stops the fan
switching back and forth around a single threshold.

```yaml
automation:
  - alias: Boost the Orcon MVS-15 on high CO₂
    triggers:
      - trigger: numeric_state
        entity_id: sensor.orcon_mvs_15_co2
        above: 1200
        for: "00:02:00"
    actions:
      - action: fan.set_preset_mode
        target:
          entity_id: fan.orcon_mvs_15_fan
        data:
          preset_mode: high

  - alias: Return the Orcon MVS-15 to auto
    triggers:
      - trigger: numeric_state
        entity_id: sensor.orcon_mvs_15_co2
        below: 800
        for: "00:10:00"
    actions:
      - action: fan.set_preset_mode
        target:
          entity_id: fan.orcon_mvs_15_fan
        data:
          preset_mode: auto
```

Replace the entity IDs with the ones in your installation.

## Data updates

The integration is push-based: the gateway publishes Ramses packets and the
integration reacts to them. The fan state (`31D9`) and vent demand (`31E0`) are
broadcast every 5 minutes, and device info (`10E0`) every 24 hours. The fan's
humidity sensor (`12A0`) is not broadcast, so it is polled every 5 minutes.
Entities are unavailable until the packet they read has arrived. If the MQTT
connection is lost or the USB cable is unplugged, all entities become unavailable
and the loss is logged once; they recover when the connection returns. A
configured fan that sends no packet for 30 minutes raises a repair issue; every
packet from the fan restarts the window.

## Known limitations

- A working 15RF wireless remote is required to send commands. Pairing a fake remote is
  not implemented yet.
- The timed-mode countdown is maintained by the integration; the fan's next
  reported state remains the source of truth for the preset.
- A `042F` power-up message is accepted from any source while the fan ID is
  unknown. A neighbouring Orcon unit that powers up while this fan is still
  being discovered could be adopted as this fan.
- A USB gateway that is unplugged or reset is not reopened automatically; reload
  the integration or restart Home Assistant once the stick is back.
- The optional `/config/packet.log` (rolled over at 10 MB) is a debugging aid.
  It is not a stable interface.

## Remove

1. Open `Settings > Devices & services`, select **Orcon MVS-15** and choose
   **Delete**.
2. If you installed it through HACS, remove the custom repository there as
   well.
3. The integration does not create configuration files. If you enabled the
   packet log, you can delete `/config/packet.log` if you no longer need it.

## Protocol

The integration speaks the Ramses II protocol over MQTT or a USB serial
connection. The frame format, supported codes, discovery flows and retry
behaviour are documented in [docs/protocol.md](docs/protocol.md).

## Troubleshooting

### The fan stopped responding

When the fan ID is known, the integration asks the fan for its state at startup
and keeps watching for its packets. If no packet arrives from the fan for 30
minutes, Home Assistant shows a repair issue under **Settings > System >
Repairs**. The issue is deleted automatically as soon as the fan is heard again.
Check that the fan has power and that the Ramses ESP gateway is within RF range,
then power-cycle the fan so it announces itself. The watchdog pauses while the
MQTT connection is down or the USB port is closed, because an unreachable
gateway says nothing about the RF link.

### Debug logging

Enable debug logging by adding the following snippet to `configuration.yaml`

```
logger:
  logs:
    custom_components.orcon_mvs15: debug
```
