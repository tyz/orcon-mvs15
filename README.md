# Orcon MVS-15

(Work in progress, currently requires a working 15RF remote until pairing a fake remote is implemented)

Home Assistant integration for the [Orcon MVS-15 fan](https://orcon.nl/mechanische-ventilatie/),
(optional) remote with CO₂ sensor and (optional) 15RF remote.

Uses MQTT and a [Ramses ESP stick](https://indalo-tech.onlineweb.shop/product/ramses-esp)
to communicate with the fan.

I used [ramses_rf](https://github.com/zxdavb/ramses_rf) and [this wiki](https://github.com/zxdavb/ramses_protocol/wiki) for some code/inspiration/help.

## Features

- Creates a fan entity with all supported presets (Away, Auto, Low, Medium, High + High 15/30/60m timed modes)
- Auto-detects the fan
- Auto-detects a CO₂ remote and creates an HA sensor
- Auto-detects the fan's humidity sensor and creates an HA sensor
- Creates a binary sensor that triggers when the fan reports a fault
- The fan reported mode is used to update the fan's current preset in HA, so it
  will immediately notice when the mode was changed by a 15RF remote, for example

## Supported devices

- Orcon MVS-15 ventilation unit (fan, humidity sensor and fault state)
- Orcon VMC-15RPS34 ventilation unit (same packets as the MVS-15; it reports
  product ID `5F`)
- Orcon MVS-15RH CO2B CO₂/humidity remote (15RF)
- Ramses ESP gateway running the Ramses II firmware over MQTT

## TODO

- Set up a fake remote and pair it with the fan
- Ramses ESP stick via USB (currently only supports MQTT)

## Install

You can install this integration by adding its GitHub repository to the HACS
configuration under `Custom repositories`. Then install it in HACS, and add the
`Orcon MVS-15` integration in `Settings > Devices & services`.

## Installation parameters

The setup form asks for two values:

- **Remote ID** — the Ramses ID of the 15RF remote that sends commands to the
  fan, for example `29:163058`. If you do not know it yet, use a fake ID and
  follow [Fan ID](#fan-id).
- **MQTT topic prefix** — the base topic of the Ramses ESP gateway, for
  example `RAMSES/GATEWAY`. The integration discovers the gateway on
  `<prefix>/+` and then exchanges packets on `<prefix>/<gateway>/rx` and
  `<prefix>/<gateway>/tx`.

## Fan ID

If you don't know the ID of the 15RF remote then use a fake ID (e.g. `29:123456`).
Tail the `packet.log` file in the Home Assistant config directory, and press the
`auto` button on the remote a couple of times. The resulting log entries should
look something like this:

```text
2026-09-11T17:29:09.534250+02:00 081  I --- 29:123456 29:654321 --:------ 22F1 003 000404
```

The remote's ID in this example is `29:123456`.

## Auto-discovery

1. Install and configure the integration. The `remote ID` it asks for is the 15RF remote's ID.
1. Turn the fan off and on again
1. The fan will be discovered by a startup message (042F) it sends out
1. The state of the humidity sensor (part of the fan) will be requested (12A0), and will be set up in HA if it responds
1. The CO₂ sensor/remote will be discovered as soon as it sends a vent demand message (31E0) to the above fan (might take a while)

## Reconfiguring

If the remote ID or MQTT topic prefix is wrong, open the integration's menu in
`Settings > Devices & services` and choose **Reconfigure**. The other discovered
IDs are kept and the entry reloads after the change.

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

Replace the entity IDs with the ones in your installation. The timed presets
(`high_15m`, `high_30m` and `high_60m`) are sent to the fan, but the integration
does not track when the timer ends; the preset follows the next state the fan
reports.

## Data updates

The integration is push-based: the gateway publishes Ramses packets and the
integration reacts to them. The fan state (`31D9`) and vent demand (`31E0`) are
broadcast every 5 minutes, and device info (`10E0`) every 24 hours. The fan's
humidity sensor (`12A0`) is not broadcast, so it is polled every 5 minutes.
Entities are unavailable until the packet they read has arrived. If the MQTT
connection is lost, all entities become unavailable and the loss is logged once;
they recover when the connection returns. A configured fan gets 30 minutes to
answer the requests sent when the entry starts, and raises a repair issue if it
stays silent.

## Known limitations

- A working 15RF remote is required to send commands. Pairing a fake remote is
  not implemented yet.
- Timed high modes (`22F3`) are sent, but the integration does not track when
  the timer ends; the preset follows the next state the fan reports.
- A `042F` power-up message is accepted from any source. A neighbouring Orcon
  unit that powers up at the same time could be adopted as this fan.
- Only MQTT transport is supported; USB is on the TODO list.
- The integration writes `/config/packet.log` (rolled over at 10 MB) as a
  debugging aid. It is not a stable interface.

## Remove

1. Open `Settings > Devices & services`, select **Orcon MVS-15** and choose
   **Delete**.
2. If you installed it through HACS, remove the custom repository there as
   well.
3. The integration does not create configuration files. You can delete
   `/config/packet.log` if you no longer need the packet log.

## Protocol

The integration speaks the Ramses II protocol over MQTT. The frame format,
supported codes, discovery flows and retry behaviour are documented in
[docs/protocol.md](docs/protocol.md).

## Troubleshooting

### The fan stopped responding

When the fan ID is known, the integration asks the fan for its state at startup.
If no packet arrives from the fan within 30 minutes, Home Assistant shows a
repair issue under **Settings > System > Repairs**. The issue is deleted
automatically as soon as the fan is heard again. Check that the fan has power
and that the Ramses ESP gateway is within RF range, then power-cycle the fan so
it announces itself. The watchdog pauses while the MQTT connection is down,
because an unreachable gateway says nothing about the RF link.

### Debug logging

Enable debug logging by adding the following snippet to `configuration.yaml`

```
logger:
  logs:
    custom_components.orcon_mvs15: debug
```
