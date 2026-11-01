# Ramses II protocol notes

This document describes the Ramses II subset used by `orcon_mvs15`: the MQTT
envelope, the frame layout, the supported codes and the discovery/retry
behaviour. It is not a complete Ramses II specification. For the wider protocol,
see [ramses_rf](https://github.com/zxdavb/ramses_rf) and the
[Ramses protocol wiki](https://github.com/zxdavb/ramses_protocol/wiki).

The packet terminology used here is defined in
[`custom_components/orcon_mvs15/README.naming.md`](../custom_components/orcon_mvs15/README.naming.md):
message → envelope → frame → packet → payload.

## Scope

The integration targets the `MVS-15` simple ventilator family. `MVx-xx` is the
model name the units are sold under (the fan's `xxx` suffix names the fitted
humidity or CO₂ option, for example `MVS-15RH CO2B`); `VMx-xx` is Orcon's
internal name. Other Orcon systems, such as the heat-recovery (WTW) units that
a gateway may also hear, share the transport, but they are out of scope for
now: their additional codes are not decoded, and their packets are ignored
unless they come from a device of the config entry (`042F` is the exception,
see below).

## MQTT transport

The integration uses a base topic, `RAMSES/GATEWAY` by default.

| Topic | Direction | Purpose |
|---|---|---|
| `<base>/+` | subscribe | Gateway discovery. The last topic segment is treated as the gateway Ramses ID. |
| `<base>/<gateway>/rx` | subscribe | Frames received by the gateway. |
| `<base>/<gateway>/tx` | publish | Frames the gateway should transmit. |
| `<base>/<gateway>/info/version` | subscribe | Gateway firmware version. |

Receive payload:

```json
{"ts": "2026-09-11T17:29:09.534250+02:00", "msg": "081  I --- 29:123456 29:654321 --:------ 22F1 003 000404"}
```

Publish payload:

```json
{"msg": "I  --- 18:149960 29:224547 --:------ 12A0 001 00"}
```

The timestamp is added by the gateway. The integration does not add a `ts` field
when publishing.

## Frame layout

```text
081  I --- 29:123456 29:654321 --:------ 22F1 003 000404
│    │ │   │          │          │         │    │   └─ data (hex, 2 chars per byte)
│    │ │   │          │          │         │    └───── length in bytes
│    │ │   │          │          │         └────────── code
│    │ │   │          │          └──────────────────── announce ID
│    │ │   │          └─────────────────────────────── destination ID
│    │ │   └────────────────────────────────────────── source ID
│    │ └────────────────────────────────────────────── frame type
│    └──────────────────────────────────────────────── separator
└───────────────────────────────────────────────────── signal strength
```

Fields:

| Field | Meaning |
|---|---|
| Signal strength | Signed RSSI in dBm. The wire value is positive (`081`); the integration negates it for display (`-81 dBm`). Frames published by this integration have signal strength `0`. |
| Type | `RQ` request, `RP` response, `I` information/command. |
| Source / destination / announce | Ramses device IDs, or `--:------` for “none”. |
| Code | Four hex characters. |
| Length | Data length in bytes. The data field contains twice as many hex characters. |
| Data | Hex payload. |

A device ID has the form `xx:yyyyyy`, where `xx` is the device type and `yyyyyy`
is the decimal device number. A 24-bit hex device value can be converted with:

```text
device_type = (value & 0xFC0000) >> 18
device_id   = value & 0x03FFFF
```

`FFFFFF` means “all ones”. The integration currently renders it as nine spaces;
that behaviour is unverified and should not be changed without protocol evidence.

## Supported codes

| Code | Description | Used | Fan | CO₂ | RF | Broadcast | Requestable | Notes |
|---|---|---|---|---|---|---|---|---|
| `042F` | Power cycle counter | Yes | Yes | No | No | Power-up | No | Sent on fan power-up; not requestable. |
| `10E0` | Device info | Yes | Yes | Yes | No | 24 h | Yes | Manufacturer, product, firmware, serial dates, description. |
| `10E1` | Device ID | No | Yes | Yes | No | — | Yes | 24-bit device identifier. |
| `1060` | Battery state | No | No | No | No | — | No | Occasionally received from another Orcon system; not used by the 15RF wireless remote. |
| `1298` | CO₂ sensor | Yes | No | Yes | No | 10 m | Yes | CO₂ concentration in ppm. |
| `12A0` | Indoor humidity | Yes | Yes | No | No | — | Yes | Not announced; polled by the integration. |
| `1FC9` | RF bind | No | ? | ? | ? | — | No | Pairing is work in progress. |
| `22F1` | Fan mode | Yes | Yes | No | No | — | Yes | 3-byte fan mode. |
| `22F3` | Fan mode with timer | Yes | Yes | No | No | — | No | 7-byte timed fan mode. |
| `31D9` | Fan state | Yes | Yes | No | No | 5 m | Yes | Current mode plus fault flag. |
| `31E0` | Vent demand | Yes | No | Yes | No | 5 m | Yes | CO₂ room sensor vent demand. |

### Percentages

Several codes encode a percentage as a half-percent byte:

```text
0x00..0xC8  ->  0..100 %
0xFE, 0xFF  ->  unavailable
```

`0xC8` is 200 decimal, so the helper divides by two. Values above 200 are
treated as “no value”.

## Code details

Offsets below are zero-based indices into the **data hex string**, not bytes.

### `042F` — power cycle counter

* Length: 6 bytes.
* `data[2:6]` — first counter.
* `data[6:10]` — second counter.
* `data[0:2]` — unknown.
* Not requestable; sent by the fan on power-up.
* The session uses `ann_id` as the fan ID when it is present, and falls back to
  the sender in `src_id` otherwise. This keeps discovery working for units that
  do not fill in `ann_id`.

Example from `startup-emu.sh`:

```text
I --- --:------ --:------ 29:224547 042F 006 00004C004C00
```

### `10E0` — device info

* Length: 1 byte (status request) or at least 29 bytes.
* Broadcast every 24 hours; also requestable.

| Data slice | Field |
|---|---|
| `[2:6]` | Manufacturer group (`0001` HVAC, `0002` CH/DHW) |
| `[6:8]` | Manufacturer sub-ID (`C8` for Orcon) |
| `[8:10]` | Product ID (`26` fan, `51` wired CO₂ room sensor, `5F` newer fan; see below) |
| `[10:12]` | Software version ID (hex) |
| `[12:14]` | List version ID |
| `[14:16]` | OEM code / unknown (the current decoder labels this both `sz_oem_code` and `unknown`) |
| `[16:18]` | Additional version A |
| `[18:20]` | Additional version B |
| `[20:28]` | Date 2 |
| `[28:36]` | Date 1 |
| `[36:]` | Description, NUL-terminated ASCII |

Dates are 8 hex characters. The decoder reads:

```text
year  = int(value[4:8], 16)
month = int(value[2:4], 16)
day   = int(value[0:2], 16) & 0b11111  # top 3 bits are day-of-week
```

`FFFFFFFF` means “no date”.

The integration updates the Home Assistant device registry from this packet:
`sw_version` and `model_id`. It accepts three product IDs:

| Product ID | Internal name | Role |
|---|---|---|
| `26` | `VMC-15RP01` | Fan, sold as `MVS-15xxx` |
| `51` | `VMS-15CM17` | Wired CO₂ room sensor, sold as `CO2 ruimtesensor 15RF` |
| `5F` | `VMC-15RPS34` | Newer fan, same packets as the MVS-15 |

Product `27` (seen from `29:167925`, `VMN-15LF01`) belongs to another Orcon
system and is not accepted.

### `10E1` — device ID

* Length: 1 byte (request) or 4 bytes.
* The 4-byte payload is a 24-bit device value converted with the formula above.

### `1060` — battery state

* Length: 1 byte (request) or 6 bytes.
* `data[2:4]` — battery level, using the half-percent encoding.
* `data[4:6]` — `00` means low battery.
* Not used by the 15RF remote.
* A 1-byte status request carries no battery state; the decoder only exposes
  `level` and `low` for a 6-byte payload.

### `1298` — CO₂

* Length: 1 byte (request) or 3 bytes.
* The whole 3-byte payload is the CO₂ concentration in ppm.

Example:

```text
044 RP --- 29:224547 18:149960 --:------ 1298 003 0001CD
```

`0x01CD` = 461 ppm.

### `12A0` — indoor humidity

* Length: 1 byte (request) or 2 bytes.
* The whole 2-byte payload is relative humidity in percent.
* This code is not broadcast; the integration polls it.

Example:

```text
044 RP --- 29:224547 18:149960 --:------ 12A0 002 002F
```

`0x2F` = 47 %.

### `1FC9` — RF bind

* Length: a multiple of 6 bytes.
* `data[0:2]` — zone index.
* `data[2:6]` — command.
* `data[6:]` — device ID.
* Pairing is work in progress; the integration does not send it yet.

### `22F1` — fan mode

* Length: 1 byte (request) or 3 bytes.
* The whole 3-byte payload is matched against this table:

| Preset | Data |
|---|---|
| `auto` | `000404` |
| `low` | `000104` |
| `medium` | `000204` |
| `high` | `000304` |
| `away` | `000004` |
| `high_15m` | `00020F03040000` — sent as `22F3` |
| `high_30m` | `00021E03040000` — sent as `22F3` |
| `high_60m` | `00023C03040000` — sent as `22F3` |

These identifiers are also the fan entity's `preset_mode` values; the frontend
shows the translated display names from `strings.json`.

The timed entries are 7 bytes, so `Code22f1.set()` changes the code to `22F3`
when the payload length is 7.

### `22F3` — fan mode with timer

* Length: 7 bytes.
* Same mode names as `22F1`; the timer duration is encoded in the payload
  (`0F` = 15, `1E` = 30, `3C` = 60).
* The integration does not track when the timer expires; the fan’s later `31D9`
  state is the source of truth.

### `31D9` — fan state

* Length: 1 byte (request) or 3 bytes.
* `data[2:4]` — bitmap; bit `0x80` means fault.
* `data[4:6]` — mode:

| Value | Preset |
|---|---|
| `00` | `away` |
| `01` | `low` |
| `02` | `medium` |
| `03` | `high` |
| `04` | `auto` |

The session sets `discovered_fan_id` from `src_id` when this packet is received.

### `31E0` — vent demand

* Length: 1 byte (request) or 8 bytes.
* `data[4:6]` — vent demand percentage, using the half-percent encoding.
* `data[12:14]` — unknown; observed values include `64`, `1E` and `AA`.
* The remaining bytes are not decoded.

## Requests, commands and retries

A status request (`Code.get()`) is:

```text
RQ, data = "00" (length 1)
expected response: RP, same code, source and destination swapped
```

A fan-mode command (`Code22f1.set()`) is:

```text
I, data = <mode payload>
code = 22F1 for 3-byte data, 22F3 for 7-byte data
expected response: I, code 31D9, from the fan
```

Retry defaults:

* `max_retries = 2`
* `timeout = 2` seconds

The session keeps outstanding packets in a queue and matches responses by
type, code, source and destination. A packet must be queued **before** it is
published; otherwise a response that arrives immediately can miss the queue and
trigger an unnecessary retry.

Frames with signal strength `0` are treated as frames sent by this integration
and are ignored, except for `042F`, which is used for local testing.

## Discovery flows

### Gateway

1. Subscribe to `<base>/+`.
2. The first message’s final topic segment becomes the gateway ID.
3. Subscribe to `<base>/<gateway>/rx` and `<base>/<gateway>/info/version`.

Step 2 times out after 10 seconds by default; the resulting `MQTTException`
makes Home Assistant retry entry setup instead of leaving it pending.

### Fan

1. The fan broadcasts `042F` on power-up.
2. The session takes `ann_id` as the fan ID, or `src_id` when the broadcast has
   no `ann_id`.
3. Entity creation calls `init_fan()`, which requests `10E0`, `12A0` and `31D9`.
4. `31D9` updates the fan mode and fault state.

The current filter accepts `042F` from any source, so a neighbouring Orcon can be
adopted. This is a known risk; ownership verification is an open design question.

### Humidity sensor

1. The fan replies to `12A0` with its humidity.
2. The session uses `src_id` as the humidity device ID and creates the sensor on
   the fan device.
3. The session polls `12A0` every 5 minutes, starting when the fan ID is known,
   so a lost first response does not stop later polls.

### Wired CO₂ room sensor

1. The sensor sends `31E0` (vent demand) to the fan.
2. If no CO₂ ID is configured and the packet is an 8-byte `I` frame addressed to
   the fan, the session takes `src_id` as the CO₂ ID.
3. Entity creation calls `init_co2()`, which requests `10E0`, `1298` and `31E0`.

## Local test injection

`startup-emu.sh` publishes a synthetic `042F` frame to
`RAMSES/GATEWAY/18:149960/cmd/cmd`:

```text
 I --- --:------ --:------ 29:224547 042F 006 00004C004C00
```

This is a manual debugging path, not part of the integration’s normal transport.

## Known limitations

* No ownership check for `042F` discovery.
* No pairing/binding flow (`1FC9`) yet; commands use the configured remote ID as
  the source.
* Timed fan modes (`22F3`) are not tracked to completion.
* Packet logging is always enabled and writes to `/config/packet.log`.
* The `FFFFFF` device ID conversion is unverified.
