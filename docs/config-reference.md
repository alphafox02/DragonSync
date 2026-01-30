# Configuration Reference

This document provides a complete reference for `config.ini` settings.

## Full Example (WarDragon-tuned)

```ini
[SETTINGS]

# ZMQ inputs (WarDragon defaults)
zmq_host = 127.0.0.1
zmq_port = 4224          # Drone telemetry stream
zmq_status_port = 4225   # WarDragon monitor (GPS, system)

# FPV signals (optional)
fpv_enabled = false
fpv_zmq_host = 127.0.0.1
fpv_zmq_port = 4226
fpv_stale = 60
fpv_radius_m = 15
fpv_rate_limit = 2.0
fpv_max_signals = 200
fpv_confirm_only = true

# TAK Server output (optional). If blank, TAK server is disabled.
tak_host =
tak_port =
tak_protocol =           # "tcp" or "udp"
tak_tls_p12 =
tak_tls_p12_pass =
tak_tls_certfile =
tak_tls_keyfile =
tak_tls_cafile =
tak_tls_skip_verify = true

# Multicast CoT to ATAK (simple zero-server option)
enable_multicast = true
tak_multicast_addr = 239.2.3.1
tak_multicast_port = 6969
tak_multicast_interface = 0.0.0.0
multicast_ttl = 1

# Runtime behavior
rate_limit = 3.0         # min seconds between sends per drone
max_drones = 30
inactivity_timeout = 60.0
enable_receive = false

# MQTT / Home Assistant (optional)
mqtt_enabled = false
mqtt_host = 127.0.0.1
mqtt_port = 1883
mqtt_topic = wardragon/drones

mqtt_username =
mqtt_password =
mqtt_tls = false
mqtt_ca_file =
mqtt_certfile =
mqtt_keyfile =
mqtt_tls_insecure = false

# Needed for HA auto-discovery (per-drone topics)
per_drone_enabled = true
per_drone_base = wardragon/drone
ha_enabled = true
ha_prefix = homeassistant
ha_device_base = wardragon_drone

# Signal alerts (optional)
mqtt_signals_enabled = false
mqtt_signals_topic = wardragon/signals
mqtt_ha_signal_tracker = false
mqtt_ha_signal_id = signal_latest

# Lattice (optional)
lattice_enabled = false
lattice_token =
# Either a full base URL:
lattice_base_url =
# or just the endpoint host (https:// will be prefixed):
lattice_endpoint =
lattice_sandbox_token =
lattice_source_name = DragonSync
lattice_drone_rate = 1.0
lattice_wd_rate = 0.2

# ADS-B / UAT (optional)
adsb_enabled = false
adsb_json_url = http://127.0.0.1:8080/?all_with_pos
adsb_min_alt = 0
adsb_max_alt = 0

# HTTP API (optional)
api_enabled = true
api_host = 0.0.0.0
api_port = 8088
```

---

## Settings Reference

### ZMQ Inputs

| Setting | Default | Description |
|---------|---------|-------------|
| `zmq_host` | `127.0.0.1` | ZMQ server host for drone telemetry |
| `zmq_port` | `4224` | ZMQ port for drone telemetry stream |
| `zmq_status_port` | `4225` | ZMQ port for WarDragon system/GPS status |

### FPV Signal Detection

| Setting | Default | Description |
|---------|---------|-------------|
| `fpv_enabled` | `false` | Enable FPV signal ingestion |
| `fpv_zmq_host` | `127.0.0.1` | ZMQ host for FPV alerts |
| `fpv_zmq_port` | `4226` | ZMQ port for FPV alerts |
| `fpv_stale` | `60` | Seconds before signal alert expires |
| `fpv_radius_m` | `15` | Offset radius for alert dot from kit |
| `fpv_rate_limit` | `2.0` | Min seconds between CoT for same signal |
| `fpv_max_signals` | `200` | Max concurrent signal alerts |
| `fpv_confirm_only` | `true` | Only ingest `confirm` alerts (not `energy`) |

### TAK Server Output

| Setting | Default | Description |
|---------|---------|-------------|
| `tak_host` | (empty) | TAK server hostname/IP. Leave blank to disable |
| `tak_port` | (empty) | TAK server port |
| `tak_protocol` | (empty) | `tcp` or `udp` |
| `tak_tls_p12` | (empty) | Path to PKCS#12 client cert |
| `tak_tls_p12_pass` | (empty) | PKCS#12 password |
| `tak_tls_certfile` | (empty) | Path to PEM certificate (alternative to p12) |
| `tak_tls_keyfile` | (empty) | Path to PEM private key |
| `tak_tls_cafile` | (empty) | Path to CA certificate for server verification |
| `tak_tls_skip_verify` | `true` | Skip TLS certificate verification (dev only) |

### Multicast CoT

| Setting | Default | Description |
|---------|---------|-------------|
| `enable_multicast` | `true` | Enable multicast CoT output |
| `tak_multicast_addr` | `239.2.3.1` | Multicast group address |
| `tak_multicast_port` | `6969` | Multicast port |
| `tak_multicast_interface` | `0.0.0.0` | Network interface to bind |
| `multicast_ttl` | `1` | Multicast TTL (hops) |

### Runtime Behavior

| Setting | Default | Description |
|---------|---------|-------------|
| `rate_limit` | `3.0` | Min seconds between CoT sends per drone |
| `max_drones` | `30` | Max concurrent drones to track |
| `inactivity_timeout` | `60.0` | Seconds before drone is marked inactive |
| `enable_receive` | `false` | Enable receiving CoT (not typically needed) |

### MQTT / Home Assistant

| Setting | Default | Description |
|---------|---------|-------------|
| `mqtt_enabled` | `false` | Master switch for MQTT output |
| `mqtt_host` | `127.0.0.1` | MQTT broker hostname/IP |
| `mqtt_port` | `1883` | MQTT broker port |
| `mqtt_topic` | `wardragon/drones` | Aggregate topic for all drone updates |
| `mqtt_username` | (empty) | MQTT username |
| `mqtt_password` | (empty) | MQTT password |
| `mqtt_tls` | `false` | Enable TLS to broker |
| `mqtt_ca_file` | (empty) | CA certificate for broker verification |
| `mqtt_certfile` | (empty) | Client certificate for mTLS |
| `mqtt_keyfile` | (empty) | Client key for mTLS |
| `mqtt_tls_insecure` | `false` | Skip TLS verification (dev only) |
| `per_drone_enabled` | `true` | Publish per-drone topics (required for HA) |
| `per_drone_base` | `wardragon/drone` | Base topic for per-drone JSON |
| `ha_enabled` | `true` | Enable Home Assistant discovery |
| `ha_prefix` | `homeassistant` | HA discovery topic prefix |
| `ha_device_base` | `wardragon_drone` | HA device ID prefix |
| `mqtt_signals_enabled` | `false` | Publish signal alerts to MQTT |
| `mqtt_signals_topic` | `wardragon/signals` | Topic for signal alerts |
| `mqtt_ha_signal_tracker` | `false` | Create per-kit HA signal tracker |
| `mqtt_ha_signal_id` | `signal_latest` | Unique ID suffix for signal entity |

**Hard-coded system topics** (not configurable):
- `wardragon/system/attrs` — kit status attributes
- `wardragon/system/availability` — kit availability
- `wardragon/service/availability` — service availability

### Lattice

| Setting | Default | Description |
|---------|---------|-------------|
| `lattice_enabled` | `false` | Enable Lattice export |
| `lattice_token` | (empty) | Lattice API token |
| `lattice_base_url` | (empty) | Full Lattice base URL |
| `lattice_endpoint` | (empty) | Lattice endpoint host (https:// prefixed) |
| `lattice_sandbox_token` | (empty) | Sandbox API token |
| `lattice_source_name` | `DragonSync` | Source name in Lattice |
| `lattice_drone_rate` | `1.0` | Drone update rate (Hz) |
| `lattice_wd_rate` | `0.2` | WarDragon status rate (Hz) |

### ADS-B / UAT

| Setting | Default | Description |
|---------|---------|-------------|
| `adsb_enabled` | `false` | Enable ADS-B ingestion |
| `adsb_json_url` | `http://127.0.0.1:8080/?all_with_pos` | readsb API URL |
| `adsb_min_alt` | `0` | Min altitude filter (feet, 0=disabled) |
| `adsb_max_alt` | `0` | Max altitude filter (feet, 0=disabled) |

### HTTP API

| Setting | Default | Description |
|---------|---------|-------------|
| `api_enabled` | `true` | Enable read-only HTTP API |
| `api_host` | `0.0.0.0` | API bind address |
| `api_port` | `8088` | API port |

---

## Minimal Configurations

### Multicast Only (Simplest)

```ini
[SETTINGS]
zmq_host = 127.0.0.1
zmq_port = 4224
zmq_status_port = 4225
enable_multicast = true
tak_multicast_addr = 239.2.3.1
tak_multicast_port = 6969
```

### TAK Server (TCP)

```ini
[SETTINGS]
zmq_host = 127.0.0.1
zmq_port = 4224
zmq_status_port = 4225
enable_multicast = false
tak_host = takserver.example.com
tak_port = 8089
tak_protocol = tcp
```

### TAK Server (TLS with P12)

```ini
[SETTINGS]
zmq_host = 127.0.0.1
zmq_port = 4224
zmq_status_port = 4225
enable_multicast = false
tak_host = takserver.example.com
tak_port = 8089
tak_protocol = tcp
tak_tls_p12 = /path/to/client.p12
tak_tls_p12_pass = yourpassword
tak_tls_skip_verify = false
```

### Home Assistant

```ini
[SETTINGS]
zmq_host = 127.0.0.1
zmq_port = 4224
zmq_status_port = 4225
enable_multicast = true
mqtt_enabled = true
mqtt_host = 127.0.0.1
mqtt_port = 1883
per_drone_enabled = true
ha_enabled = true
```
