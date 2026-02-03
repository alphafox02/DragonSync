# MQTT Payload Schema

This document describes the JSON payloads published by DragonSync to MQTT.

## Drone Payload

Each drone update published to the aggregate topic (`wardragon/drones`) or per-drone topic (`wardragon/drone/<id>`) contains the following JSON fields:

| Field | Type | Description |
|-------|------|-------------|
| **Identity** |||
| `id` | string | Drone identifier (Serial Number or session ID) |
| `id_type` | string | ID type (e.g., "Serial Number (ANSI/CTA-2063-A)") |
| `description` | string | Human-readable description |
| `mac` | string | MAC address of transmitter |
| `caa_id` | string | Civil Aviation Authority registration ID |
| `track_type` | string | Always `"drone"` for drone payloads |
| **Position** |||
| `lat` | float | Latitude (degrees) |
| `lon` | float | Longitude (degrees) |
| `latitude` | float | Latitude (HA device_tracker compatibility) |
| `longitude` | float | Longitude (HA device_tracker compatibility) |
| `alt` | float | Altitude MSL (meters) |
| `height` | float | Height AGL (meters) |
| `pressure_altitude` | float/null | Pressure altitude if available |
| `height_type` | string | Height reference type |
| **Kinematics** |||
| `speed` | float | Ground speed (m/s) |
| `vspeed` | float | Vertical speed (m/s) |
| `speed_multiplier` | float/null | Speed multiplier from RID |
| `direction` | float | Course/heading (degrees) |
| **Pilot & Home** |||
| `pilot_lat` | float | Pilot latitude |
| `pilot_lon` | float | Pilot longitude |
| `home_lat` | float | Home/takeoff latitude |
| `home_lon` | float | Home/takeoff longitude |
| **Aircraft Type** |||
| `ua_type` | int/null | UA type code (1=fixed-wing, 2=multirotor, etc.) |
| `ua_type_name` | string | Human-readable UA type |
| `op_status` | string | Operational status |
| `ew_dir` | string | East/West direction segment |
| **Operator** |||
| `operator_id` | string | Operator/pilot ID |
| `operator_id_type` | string | Operator ID type |
| **RID Lookup** |||
| `rid_make` | string/null | Manufacturer from FAA RID lookup |
| `rid_model` | string/null | Model from FAA RID lookup |
| `rid_status` | string/null | Registration status |
| `rid_tracking` | string/null | FAA tracking number |
| `rid_source` | string/null | Lookup source (e.g., "faa_db") |
| `rid_lookup_attempted` | bool | Whether lookup was attempted |
| `rid_lookup_success` | bool | Whether lookup succeeded |
| **Accuracy (RID spec)** |||
| `horizontal_accuracy` | string | Horizontal accuracy category |
| `vertical_accuracy` | string | Vertical accuracy category |
| `baro_accuracy` | string | Barometric accuracy category |
| `speed_accuracy` | string | Speed accuracy category |
| `timestamp_accuracy` | string | Timestamp accuracy category |
| `gps_accuracy` | float | Numeric accuracy for HA (meters) |
| **Timestamps** |||
| `timestamp` | string | Legacy timestamp field |
| `rid_timestamp` | string | Timestamp from RID message |
| `observed_at` | float/null | Kit system time (epoch seconds) |
| `last_update_time` | float/null | Last internal update time |
| **Radio** |||
| `rssi` | float | Signal strength (dBm) |
| `freq` | float/null | Frequency (raw, Hz or MHz) |
| `freq_mhz` | float/null | Frequency (normalized to MHz) |
| **Metadata** |||
| `index` | int | Message index |
| `runtime` | int | Drone runtime (seconds) |
| `seen_by` | string/null | Kit identifier (e.g., `wardragon-<serial>`) |

### Notes

- `latitude`/`longitude` duplicate `lat`/`lon` for Home Assistant device_tracker compatibility.
- `gps_accuracy` is the numeric form of `horizontal_accuracy` for HA map circles.
- Accuracy fields are strings from the RID spec (e.g., `"<1m"`, `"<3m"`, `"<10m"`).
- Fields may be `null`, `""`, or `0` when data is unavailable from the source.

## Signal Payload

Signal alerts (FPV detections) published to `wardragon/signals`:

| Field | Type | Description |
|-------|------|-------------|
| `uid` | string | Unique signal identifier |
| `signal_type` | string | Signal type (e.g., "fpv") |
| `source` | string | Detection source |
| `callsign` | string | Signal callsign if available |
| `description` | string | Human-readable description |
| `center_hz` | float/null | Center frequency (Hz) |
| `bandwidth_hz` | float/null | Signal bandwidth (Hz) |
| `pal` | float/null | PAL confidence score |
| `ntsc` | float/null | NTSC confidence score |
| `rssi` | float/null | Signal strength (dBm) |
| `sensor_lat` | float/null | Sensor latitude |
| `sensor_lon` | float/null | Sensor longitude |
| `sensor_alt` | float/null | Sensor altitude |
| `lat` | float | Alert latitude |
| `lon` | float | Alert longitude |
| `alt` | float | Alert altitude |
| `latitude` | float | HA compatibility |
| `longitude` | float | HA compatibility |
| `radius_m` | float | Uncertainty radius (meters) |
| `gps_accuracy` | float | Same as radius_m for HA |
| `seen_by` | string/null | Kit identifier |
| `observed_at` | float/null | Detection time (epoch) |

## Aircraft Payload

ADS-B aircraft published to `wardragon/aircraft` (when enabled):

| Field | Type | Description |
|-------|------|-------------|
| `icao` | string | ICAO hex code (uppercase) |
| `callsign` | string | Flight callsign |
| `registration` | string | Aircraft registration |
| `lat` | float | Latitude |
| `lon` | float | Longitude |
| `latitude` | float | HA compatibility |
| `longitude` | float | HA compatibility |
| `alt` | float | Altitude (feet) |
| `altitude_ft` | float | Same as alt |
| `speed` | float | Ground speed (knots) |
| `speed_kt` | float | Same as speed |
| `track` | float | True track (degrees) |
| `heading` | float | Same as track |
| `vertical_rate` | float/null | Climb/descent rate |
| `squawk` | string | Transponder squawk code |
| `category` | string | Aircraft category |
| `on_ground` | bool | Whether aircraft is on ground |
| `nac_p` | float/null | NACp accuracy value |
| `nac_v` | float/null | NACv accuracy value |
| `rssi` | float/null | Signal strength (dBFS from readsb) |
| `seen_by` | string/null | Kit identifier |
| `track_type` | string | Always `"aircraft"` |

## System Payload

Kit status published to `wardragon/system/attrs`:

| Field | Type | Description |
|-------|------|-------------|
| `id` | string | Kit identifier |
| `latitude` | float | Kit latitude |
| `longitude` | float | Kit longitude |
| `hae` | float | Height above ellipsoid |
| `cpu_usage` | float | CPU usage percentage |
| `memory_total_mb` | float | Total RAM (MB) |
| `memory_available_mb` | float | Available RAM (MB) |
| `disk_total_mb` | float | Total disk (MB) |
| `disk_used_mb` | float | Used disk (MB) |
| `temperature_c` | float | System temperature (°C) |
| `uptime_s` | float | System uptime (seconds) |
| `pluto_temp_c` | float/null | Pluto SDR temperature |
| `zynq_temp_c` | float/null | Zynq temperature |
| `speed_mps` | float | Ground speed (m/s) |
| `track_deg` | float | Course (degrees) |
| `gps_fix` | bool | GPS fix status |
| `time_source` | string/null | Time source (gpsd, static, unknown) |
| `gpsd_time_utc` | string/null | GPS time if available |
| `updated` | int | Last update (epoch) |

## Topics Summary

| Topic | Description | Retain |
|-------|-------------|--------|
| `wardragon/drones` | Aggregate drone stream | Configurable |
| `wardragon/drone/<id>` | Per-drone state | Configurable |
| `wardragon/drone/<id>/availability` | Drone online/offline | Yes |
| `wardragon/drone/<id>/pilot_attrs` | Pilot location attrs | Yes |
| `wardragon/drone/<id>/home_attrs` | Home location attrs | Yes |
| `wardragon/signals` | Signal alerts | Configurable |
| `wardragon/aircraft` | ADS-B aircraft | No |
| `wardragon/system/attrs` | Kit status | No |
| `wardragon/system/availability` | Kit online/offline | Yes |
| `wardragon/service/availability` | Service online/offline | Yes |
