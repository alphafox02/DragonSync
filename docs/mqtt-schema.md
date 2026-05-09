# MQTT Payload Schema

**Canonical reference for the JSON schemas and topic structure DragonSync publishes to MQTT.**

This document is the single source of truth for the MQTT wire format. Operator-facing setup guides (broker config, Home Assistant discovery, automations) live in [WarDragon docs → MQTT & HA Integration](https://github.com/alphafox02/WarDragon/blob/main/docs/integration/mqtt-homeassistant.md) and link back here for field details.

All payloads are produced by `sinks/mqtt_sink.py`. When in doubt, the code is authoritative.

---

## Topic Structure

Every topic DragonSync may publish. `<id>` is the drone ID (e.g. `drone-F6Q8D244C00CL2KF`). `<seen_by>` is the WarDragon kit ID, slugified.

| Topic | Retained | Purpose |
|-------|----------|---------|
| `wardragon/service/availability` | yes | LWT — `online` while DragonSync runs, `offline` on shutdown/crash |
| `wardragon/drones` | configurable | Aggregate drone state (all detected drones) |
| `wardragon/drone/<id>` | configurable | Per-drone state — same JSON as aggregate |
| `wardragon/drone/<id>/availability` | yes | `online`/`offline` for the drone tracker |
| `wardragon/drone/<id>/state` | yes | HA `device_tracker` textual state (`None` initially) |
| `wardragon/drone/<id>/pilot_attrs` | yes | Pilot location attributes (small JSON) |
| `wardragon/drone/<id>/pilot_state` | yes | HA pilot tracker textual state |
| `wardragon/drone/<id>/pilot_availability` | yes | `online` when pilot location is known |
| `wardragon/drone/<id>/home_attrs` | yes | Home location attributes (small JSON) |
| `wardragon/drone/<id>/home_state` | yes | HA home tracker textual state |
| `wardragon/drone/<id>/home_availability` | yes | `online` when home location is known |
| `wardragon/aircraft` | no | ADS-B aircraft state (high-volume; not retained) |
| `wardragon/signals` | configurable | Aggregate FPV/RF signal alerts |
| `wardragon/signals/<seen_by>` | configurable | Per-sensor signal feed (only with `mqtt_ha_signal_tracker = true`) |
| `wardragon/signals/<seen_by>/state` | configurable | HA signal tracker textual state |
| `wardragon/signals/<seen_by>/availability` | yes | `online` whenever a signal arrives |
| `wardragon/signals/availability` | yes | Marks signals offline at shutdown |
| `wardragon/system/attrs` | no | WarDragon kit telemetry |
| `wardragon/system/state` | no | Kit textual state |
| `wardragon/system/availability` | yes | `online` while kit telemetry is publishing |
| `homeassistant/sensor/<unique_id>/config` | yes | HA sensor discovery configs (when `mqtt_ha_enabled = true`) |
| `homeassistant/device_tracker/<unique_id>/config` | yes | HA device_tracker discovery configs |

Availability topics carry the literal string `online` or `offline` (no JSON).

---

## Drone Payload

Published to **`wardragon/drones`** (aggregate, one message per drone update) and **`wardragon/drone/<id>`** (per-drone, latest state). **Identical JSON on both topics.** Source: `_drone_to_state` in `sinks/mqtt_sink.py`.

| Field | Type | Always present | Notes |
|-------|------|-----------------|-------|
| **Identity** ||||
| `id` | string | yes | Drone identifier (e.g. `drone-F6Q8D244C00CL2KF`, `drone-AABBCCDDEEFF` for BLE MAC, `drone-alert` for unknown OcuSync) |
| `id_type` | string | yes (may be empty) | RID ID type (e.g. `Serial Number (ANSI/CTA-2063-A)`, `CAA Assigned Registration ID`) |
| `description` | string | yes (may be empty) | Self-reported description. For DJI: `DJI O4 (Decrypted)`, `DJI Encrypted (O4)`, `DJI Mini 5 (O4)`, `DJI Mini 2 (O2)`, etc. For BLE/WiFi RID: operator-programmed self-ID text |
| `mac` | string | yes (may be empty) | Transmitter MAC. Empty for OcuSync (RF-only) |
| `caa_id` | string | yes (may be empty) | Civil Aviation Authority registration ID (CAA Assigned RID) |
| `track_type` | string | yes | Always `"drone"` |
| **Position** ||||
| `lat` | float | yes | Latitude (degrees). `0.0` when no fix |
| `lon` | float | yes | Longitude (degrees) |
| `latitude` | float | yes | Mirror of `lat` for HA `device_tracker` |
| `longitude` | float | yes | Mirror of `lon` for HA `device_tracker` |
| `alt` | float | yes | Altitude HAE / geodetic (meters) |
| `height` | float | yes | Height AGL (meters) |
| `pressure_altitude` | float \| null | no | When present in RID |
| `height_type` | string | yes (may be empty) | RID height reference type |
| **Kinematics** ||||
| `speed` | float | yes | Ground speed (m/s) |
| `vspeed` | float | yes | Vertical speed (m/s) |
| `speed_multiplier` | float \| null | no | RID speed multiplier flag |
| `direction` | float | yes | Heading / course (degrees, 0–360) |
| **Pilot & Home** ||||
| `pilot_lat` | float | yes | Pilot latitude. `0.0` when not detected |
| `pilot_lon` | float | yes | Pilot longitude |
| `home_lat` | float | yes | Home/takeoff latitude. `0.0` when not detected |
| `home_lon` | float | yes | Home/takeoff longitude |
| **UA Type** ||||
| `ua_type` | int \| null | no | UA category code (0–15 per ASTM F3411) |
| `ua_type_name` | string | yes (may be empty) | Human-readable UA category, e.g. `Helicopter or Multirotor` |
| `op_status` | string | yes (may be empty) | RID operational status flag |
| `ew_dir` | string | yes (may be empty) | RID E/W direction segment flag |
| **Operator** ||||
| `operator_id` | string | yes (may be empty) | Operator/pilot ID from RID Operator ID Message |
| `operator_id_type` | string | yes (may be empty) | Operator ID type |
| **FAA RID Lookup** ||||
| `rid_make` | string \| null | no | Manufacturer from FAA RID lookup |
| `rid_model` | string \| null | no | Model from FAA RID lookup |
| `rid_status` | string \| null | no | Registration status |
| `rid_tracking` | string \| null | no | Tracking ID |
| `rid_source` | string \| null | no | Lookup source (e.g. `local-cache`, `faa-api`) |
| `rid_lookup_attempted` | bool | yes | Whether lookup was attempted |
| `rid_lookup_success` | bool | yes | Whether lookup succeeded |
| **Accuracy (RID spec strings)** ||||
| `horizontal_accuracy` | string | yes (may be empty) | Horizontal accuracy category, e.g. `<1m`, `<3m` |
| `vertical_accuracy` | string | yes (may be empty) | |
| `baro_accuracy` | string | yes (may be empty) | |
| `speed_accuracy` | string | yes (may be empty) | |
| `timestamp_accuracy` | string | yes (may be empty) | |
| `gps_accuracy` | float | yes | Numeric form of `horizontal_accuracy` (meters), for HA |
| **Timestamps** ||||
| `timestamp` | string | yes (may be empty) | RID timestamp (legacy field) |
| `rid_timestamp` | string | yes | Mirrors `timestamp` if no separate value |
| `observed_at` | float \| null | no | Kit system time (Unix epoch seconds) when received |
| `last_update_time` | float \| null | no | Internal last-update timestamp |
| **Radio** ||||
| `rssi` | float | yes | Signal strength (dBm) |
| `freq` | float \| null | no | Detection frequency (raw — Hz or MHz depending on source) |
| `freq_mhz` | float \| null | no | Always MHz, normalised from `freq` |
| `transport` | string | yes (may be empty) | Link layer (`WiFi-Beacon`, `WiFi-NAN`, `BT5-LR-Extended`, `ISM-FHSS`, etc.). Empty for OcuSync — receiver doesn't tag link layer |
| **Metadata** ||||
| `index` | int | yes | RID page index (BT/WiFi only) |
| `runtime` | int | yes | RID runtime counter (seconds) |
| `seen_by` | string \| null | no | WarDragon kit ID (e.g. `wardragon-G6PA14100J63`) |

### Notes

- `latitude`/`longitude` duplicate `lat`/`lon` for HA `device_tracker` map placement.
- Fields marked **"yes (may be empty)"** are always in the JSON dict but may be `""`, `0`, or `0.0` when the source didn't provide a value. Fields marked **"no"** may be omitted or `null`.
- Accuracy fields use the RID-spec category strings (e.g. `<1m`, `<3m`, `<10m`).

### Example payload

DJI O4 detection from dji-receiver:

```json
{
  "id": "drone-F6Q8D244C00CL2KF",
  "description": "DJI O4 (Decrypted)",
  "track_type": "drone",
  "lat": 27.8002846,
  "lon": -82.6686196,
  "latitude": 27.8002846,
  "longitude": -82.6686196,
  "gps_accuracy": 0.0,
  "alt": 65531.0,
  "height": 0.0,
  "speed": 0.0,
  "vspeed": 0.0,
  "direction": 270.0,
  "rssi": -117.0,
  "pilot_lat": 27.8003992,
  "pilot_lon": -82.668568,
  "home_lat": 27.8002961,
  "home_lon": -82.6685738,
  "mac": "",
  "id_type": "Serial Number (ANSI/CTA-2063-A)",
  "ua_type": 0,
  "ua_type_name": "",
  "caa_id": "",
  "operator_id_type": "",
  "operator_id": "",
  "freq": 5756.5,
  "freq_mhz": 5756.5,
  "transport": "",
  "seen_by": "wardragon-G6PA14100J63",
  "rid_lookup_attempted": false,
  "rid_lookup_success": false
}
```

---

## Pilot / Home Attribute Payloads

Published to **`wardragon/drone/<id>/pilot_attrs`** and **`wardragon/drone/<id>/home_attrs`**. Small payloads sized for HA `device_tracker` consumption.

```json
{
  "latitude": 27.8003992,
  "longitude": -82.668568,
  "gps_accuracy": 0.0
}
```

---

## Signal Payload

FPV / RF signal detections published to **`wardragon/signals`**. Source: `_signal_to_state`.

| Field | Type | Notes |
|-------|------|-------|
| `uid` | string | Stable detection UID |
| `signal_type` | string | e.g. `fpv`, `analog-video`, `digital-fhss` |
| `source` | string \| null | Source identifier (e.g. SDR name) |
| `callsign` | string \| null | Display name |
| `description` | string \| null | Free-text description |
| `center_hz` | float \| null | Centre frequency (Hz) |
| `bandwidth_hz` | float \| null | Bandwidth (Hz) |
| `pal` | float \| null | PAL detection confidence |
| `ntsc` | float \| null | NTSC detection confidence |
| `rssi` | float \| null | Signal strength (dBm) |
| `sensor_lat` | float \| null | Sensor latitude |
| `sensor_lon` | float \| null | Sensor longitude |
| `sensor_alt` | float \| null | Sensor altitude |
| `lat` | float | Detection latitude (sensor by default) |
| `lon` | float | Detection longitude |
| `latitude` | float | Mirror of `lat` |
| `longitude` | float | Mirror of `lon` |
| `alt` | float | Detection altitude |
| `radius_m` | float | Uncertainty radius (meters) |
| `gps_accuracy` | float | Mirror of `radius_m` for HA |
| `seen_by` | string \| null | WarDragon kit ID |
| `observed_at` | float \| null | Unix epoch seconds |

---

## Aircraft Payload

ADS-B aircraft published to **`wardragon/aircraft`** (when `mqtt_aircraft_enabled = true`). Source: `_aircraft_to_state`. **Not retained** (high-volume).

| Field | Type | Notes |
|-------|------|-------|
| `icao` | string | ICAO 24-bit hex (uppercase) |
| `callsign` | string | Flight number/callsign |
| `registration` | string | Tail number |
| `lat` | float | Latitude |
| `lon` | float | Longitude |
| `latitude` | float | Mirror of `lat` |
| `longitude` | float | Mirror of `lon` |
| `alt` | float | Altitude (feet, geometric preferred, falls back to barometric) |
| `altitude_ft` | float | Mirror of `alt` |
| `speed` | float | Ground speed (knots) |
| `speed_kt` | float | Mirror of `speed` |
| `track` | float | True track (degrees) |
| `heading` | float | Mirror of `track` |
| `vertical_rate` | float \| null | Barometric vertical rate (ft/min) |
| `squawk` | string | Mode A squawk code |
| `category` | string | ADS-B emitter category |
| `on_ground` | bool | Ground state |
| `nac_p` | float \| null | NACp (positional accuracy) |
| `nac_v` | float \| null | NACv (velocity accuracy) |
| `rssi` | float \| null | Receiver signal strength (dBFS from readsb) |
| `seen_by` | string \| null | WarDragon kit ID |
| `track_type` | string | Always `"aircraft"` |

---

## System (Kit) Payload

WarDragon kit telemetry published to **`wardragon/system/attrs`**. Source: `publish_system`.

| Field | Type | Notes |
|-------|------|-------|
| `id` | string | Kit ID (e.g. `wardragon-G6PA14100J63`) |
| `latitude` | float | Kit GPS latitude |
| `longitude` | float | Kit GPS longitude |
| `hae` | float | Kit altitude HAE (meters) |
| `cpu_usage` | float | CPU percent |
| `memory_total_mb` | float | Total RAM (MB) |
| `memory_available_mb` | float | Available RAM (MB) |
| `disk_total_mb` | float | Total disk (MB) |
| `disk_used_mb` | float | Used disk (MB) |
| `temperature_c` | float | Mainboard temperature (°C) |
| `uptime_s` | float | System uptime (seconds) |
| `pluto_temp_c` | float \| null | DragonSDR PlutoSDR temperature (°C) |
| `zynq_temp_c` | float \| null | DragonSDR Zynq SoC temperature (°C) |
| `speed_mps` | float | Kit ground speed (GPS) |
| `track_deg` | float | Kit course (degrees) |
| `gps_fix` | bool | GPS fix valid |
| `time_source` | string \| null | e.g. `gpsd`, `system` |
| `gpsd_time_utc` | string \| null | UTC time from gpsd |
| `updated` | int | Unix epoch seconds when published |

---

## Related

- [Operator setup guide (WarDragon docs)](https://github.com/alphafox02/WarDragon/blob/main/docs/integration/mqtt-homeassistant.md) — broker config, HA auto-discovery, automation examples, troubleshooting.
- `sinks/mqtt_sink.py` — implementation; the source of truth if this doc ever drifts.
