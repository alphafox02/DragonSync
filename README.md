# DragonSync (Community Edition)

A lightweight gateway that turns WarDragon’s drone detections into **Cursor on Target (CoT)** for TAK/ATAK, and (optionally) publishes per‑drone telemetry to **Lattice** as well as to **MQTT** for **Home Assistant**. This README focuses on the **WarDragon** kit where everything (drivers, sniffers, ZMQ monitor) is already set up—so you mostly just configure and run **DragonSync (Community Edition)**. A companion ATAK plugin (**WarDragon**) can use the read‑only API for richer UI, but it does **not** replace DragonSync’s CoT output.

DragonSync can also ingest **ADS‑B / UAT (978 MHz)** aircraft data from a local `readsb` instance and convert that into CoT alongside your drone detections.

---

## Table of Contents

- [Features](#features)
- [Requirements](#requirements)
- [TL;DR](#tldr)
- [New data fields and attribution](#new-data-fields-and-attribution)
- [MQTT resilience](#mqtt-resilience)
- [Quick testing](#quick-testing)
- [FAA RID Enrichment & Logging](#faa-rid-enrichment--logging)
- [How it Works (on WarDragon)](#how-it-works-on-wardragon)
- [Quick Start (WarDragon)](#quick-start-wardragon)
- [HTTP API (Read-Only)](#http-api-read-only)
- [ADS-B / 978 Integration](#ads-b--978-integration)
- [Configuration](#configuration)
- [Signal Alerts (Optional)](#signal-alerts-optional)
- [Kismet Ingest (Optional)](#kismet-ingest-optional)
- [Home Assistant (MQTT)](#home-assistant-mqtt)
- [Static GPS (if no live GPS)](#static-gps-if-no-live-gps)
- [TAK / ATAK Output](#tak--atak-output)
- [Lattice (optional)](#lattice-optional)
- [Tips & Troubleshooting](#tips--troubleshooting)
- [License](#license)

### Documentation

- [Configuration Reference](docs/config-reference.md) — Full `config.ini` settings
- [MQTT Payload Schema](docs/mqtt-schema.md) — JSON field reference for MQTT consumers
- [ADS-B Setup Guide](docs/adsb-setup.md) — Detailed readsb integration

---

## Features  

- **Remote ID Drone Detection:**
   Uses [droneid-go](https://github.com/alphafox02/droneid-go) to detect WiFi and Bluetooth Remote ID signals. BLE capture via Sniffle (thanks @bkerler). Some kits also support ESP32-based WiFi Remote ID capture.
- **DJI DroneID Detection:**
   Uses [Antsdr_DJI](https://github.com/alphafox02/antsdr_dji_droneid) to detect DJI DroneID signals.  
- **ADS‑B / UAT (978) Integration (optional):**  
   Can subscribe to a local [readsb](https://github.com/wiedehopf/readsb) HTTP API (`/?all_with_pos`) and convert aircraft tracks into CoT, including NACp/NACv‑derived CE/LE, squawk, category, and more.
- **System Status Monitoring:**  
   `wardragon_monitor.py` gathers hardware status (via `lm-sensors`), GPS location, and serial number.  
- **CoT Generation:**  
   Converts system, drone, and (optionally) aircraft data into CoT messages.  
- **ZMQ Support:**  
   Uses ZMQ for communication between components.  
- **TAK/ATAK Integration:**  
   Supports multicast for ATAK or direct TAK server connections.  
- **Read‑only HTTP API (optional):**  
   Exposes status, tracks, and sanitized config for the WarDragon ATAK companion app.  

---

## Requirements  

### **Pre-installed on WarDragon Pro:**  
If running DragonSync on the WarDragon Pro kit, all dependencies are pre-configured, including hardware-specific sensors and GPS modules. Future WarDragon Pro images will also include `readsb` prebuilt for easier ADS‑B integration.

### **For Other Systems:**  
If you install DragonSync elsewhere, ensure the following:  

- **Python 3.x**  
- **lm-sensors**: Install via:  
   ```bash
   sudo apt update && sudo apt install lm-sensors
   ```  
- **gpsd** (GPS Daemon):  
   ```bash
   sudo apt install gpsd gpsd-clients
   ```  
- **USB GPS Module**: Ensure a working GPS connected to the system.  
- Other necessary Python packages (listed in the `requirements.txt` or as dependencies).  
- (Optional) **readsb** if you plan to use ADS‑B / 978 integration.

---

## TL;DR

- WarDragon already runs the sniffers and the system monitor that feed ZMQ.
- You only need to edit **`config.ini`** in the DragonSync repo, then run `dragonsync.py`.
- Optional: enable MQTT + Home Assistant and/or Lattice export.
- Optional: enable ADS‑B / 978 via a local `readsb` instance.
- Optional: enable the **read‑only API** for the WarDragon ATAK companion app.
- When a drone times out, DragonSync marks it **offline** in HA, preserving last‑known position in history.

---

## New data fields and attribution

- Per‑drone MQTT payloads now include:
  - `observed_at`: kit system time (seconds since epoch) when the packet was processed.
  - `rid_timestamp`: the airframe’s own timestamp from the RID message (may be relative/non‑UTC on some sources).
  - `seen_by`: kit identifier (e.g., `wardragon-<serial>` from wardragon_monitor’s `serial_number`).
  - Legacy `timestamp` remains for compatibility.
- System MQTT attrs (`wardragon/system/attrs`) include GPS status:
  - `gps_fix` (bool), `time_source` (e.g., `gpsd`, `static`, `unknown`), `gpsd_time_utc` when available.
- Home Assistant discovery: pilot/home trackers are only created when HA discovery is enabled. Without HA, only drone payloads (aggregate/per‑drone) and system attrs are published.

## MQTT resilience

MQTT startup uses async connect and automatic retries. If the broker is down at boot, DragonSync still runs (CoT etc.) and will connect once the broker comes up.

## Quick testing

- Run wardragon_monitor plus the simulator (`tests/test_drone_generator.py`) to see `seen_by` flip to `wardragon-<serial>` after the first status message.
- Check `wardragon/system/attrs` for `gps_fix`/`time_source`. Without HA, pilot/home MQTT trackers are not created; data is still present in drone payloads.

---

## FAA RID Enrichment & Logging

- FAA RID lookups are bundled as a submodule (`faa-rid-lookup`). Dragon telemetry is enriched with RID make/model/source in CoT and MQTT. FAA API fallback is **off by default**; enable by setting `rid_api_enabled = true` in `config.ini` if you want online lookups to fill misses.
- ZMQ logger (`utils/zmq_logger_for_kml.py`) can add RID fields and log to CSV or SQLite; see `utils/README.md` for flags (`--rid-enabled`, `--rid-api`, `--sqlite`, rotation/retention).
- Offline viewer for SQLite logs: `python utils/log_viewer.py --db drone_log.sqlite --port 5001` (map + filters, offline-safe). Details in `utils/README.md`.

## How it Works (on WarDragon)

```
Sniffers (WiFi RID / BLE RID / DJI) --> ZMQ 4224
WarDragon Monitor (GPS/system)      --> ZMQ 4225
ADS-B / UAT via readsb (optional)   --> HTTP /?all_with_pos

FPV energy scan (optional)          --> ZMQ 4226

ZMQ 4224 + ZMQ 4225 + ZMQ 4226 + (HTTP) --> DragonSync --> CoT (multicast/TAK)
                                              \-> MQTT (aggregate + per-drone)
                                              \-> Lattice (optional)
                                              \-> HTTP API (WarDragon ATAK companion)
```

- **ZMQ 4224**: stream of decoded Remote ID / DJI frames.
- **ZMQ 4225**: WarDragon system/GPS info from `wardragon_monitor.py`.
- **ZMQ 4226**: FPV energy/confirm alerts from `fpv_energy_scan.py` (optional).
- **readsb HTTP API**: aircraft list from local SDR(s), if enabled.
- **DragonSync** merges streams, rate‑limits, and outputs:
  - **CoT** to ATAK/WinTAK via **multicast** _or_ **TAK server** (TCP/UDP, optional TLS).
  - **MQTT** (per‑drone JSON + HA discovery) for dashboards and a live map in Home Assistant.
  - **Lattice** export for Anduril Lattice, if configured.
  - **HTTP API** (read‑only) for the WarDragon ATAK companion plugin.

---

## Quick Start (WarDragon)

1) **Clone/update DragonSync** on the WarDragon (sniffers/monitor are already there):
```bash
git clone https://github.com/alphafox02/DragonSync
cd DragonSync
pip3 install -r requirements.txt
```

2) **Edit `config.ini`** (see example below). Most defaults work out‑of‑the‑box on the kit.

3) **Run it**:
```bash
python3 dragonsync.py -c config.ini
```

4) (Optional) **Enable systemd service** so it starts on boot:
```bash
sudo systemctl enable dragonsync.service
sudo systemctl start dragonsync.service
journalctl -u dragonsync.service -f   # tail logs
```

> The WarDragon kit already includes sniffers and the ZMQ monitor; you do **not** need to run those manually unless you customized the setup.

---

## HTTP API (Read‑Only)

The API is intended for the **WarDragon ATAK companion plugin** and exposes data that ATAK alone doesn’t show well (health, detailed track metadata, config view).

**Endpoints**

- `GET /status` — system health + kit ID
- `GET /drones` — drone + aircraft tracks (when enabled)
- `GET /signals` — signal detections (FPV alerts, optional)
- `GET /config` — sanitized config
- `GET /update/check` — git update check (read‑only)

**Config**

```ini
api_enabled = true
api_host = 0.0.0.0
api_port = 8088
```

> This API does **not** replace CoT; ATAK still receives CoT via multicast/TAK server.

---

## ADS-B / 978 Integration

DragonSync can ingest aircraft data from a local `readsb` instance via HTTP and convert it to CoT.

**Quick config:**
```ini
[SETTINGS]
adsb_enabled = true
adsb_json_url = http://127.0.0.1:8080/?all_with_pos
```

For detailed setup instructions including readsb configuration and SDR considerations, see **[ADS-B Setup Guide](docs/adsb-setup.md)**.

---

## Configuration

Edit `config.ini` to configure DragonSync. Here's a minimal example for multicast CoT:

```ini
[SETTINGS]
# ZMQ inputs (WarDragon defaults)
zmq_host = 127.0.0.1
zmq_port = 4224
zmq_status_port = 4225

# Multicast CoT to ATAK
enable_multicast = true
tak_multicast_addr = 239.2.3.1
tak_multicast_port = 6969
```

For Home Assistant integration, add:

```ini
# MQTT / Home Assistant
mqtt_enabled = true
mqtt_host = 127.0.0.1
mqtt_port = 1883
mqtt_per_drone_enabled = true
mqtt_ha_enabled = true
```

For the complete settings reference including TAK server TLS, Lattice, ADS-B, and all MQTT options, see **[Configuration Reference](docs/config-reference.md)**.

---

## Signal Alerts (Optional)

DragonSync can ingest **signal alerts** (currently FPV energy/confirm from the WarDragon FPV scan) and emit CoT spot reports. These are **not** drone tracks; they show as near‑kit alerts and are exposed via `GET /signals` for the ATAK plugin.

To publish signal alerts via MQTT, set `mqtt_enabled=true` and `mqtt_signals_enabled=true`. Alerts are then published to `wardragon/signals`. For Home Assistant, also set `mqtt_ha_signal_tracker=true` to create a per‑kit "Signal Alert" device_tracker.

**Enable**

```ini
fpv_enabled = true
fpv_zmq_host = 127.0.0.1
fpv_zmq_port = 4226
fpv_stale = 60
fpv_radius_m = 15
fpv_rate_limit = 2.0
fpv_max_signals = 200
fpv_confirm_only = true
```

**Notes**

- Source data comes from the **wardragon-fpv-detect** repo (e.g., `scripts/fpv_energy_scan.py`) and is published over XPUB ZMQ.
- `fpv_radius_m` controls how far the alert dot is offset from the kit location.
- By default, only `confirm` alerts are ingested. Set `fpv_confirm_only = false` to include `energy`.

---

## Kismet Ingest (Optional)

DragonSync can optionally ingest **Wi‑Fi / Bluetooth** device locations from Kismet and emit CoT. This is **off by default** and **allow‑list only**.

**Requirements**

- Kismet running with REST API enabled (default: `http://127.0.0.1:2501`)
- Python package: `python-kismet-rest`
- Kismet API tokens: use a **readonly** key for queries, or **admin** for datasource control. Keys are created in the Kismet web UI. Set the token in `kismet_apikey`.

**Enable**

```ini
kismet_enabled = true
kismet_host = http://127.0.0.1:2501
kismet_apikey =
```

**Allow‑list (required)**

Create or edit `kismet_targets.txt` (repo root). One MAC per line:

```
# Example
AA:BB:CC:DD:EE:FF
```

If the file is missing or empty, **no Kismet CoT is sent**. This prevents ATAK from being flooded with unrelated devices.

**Notes**
- For ATAK on the same LAN/VPN, multicast is easiest (`enable_multicast=true`). In ATAK, add a Network feed for the same group/port.
- For a TAK server, fill `tak_host`, `tak_port`, and `tak_protocol`. Add TLS fields if required by your server.
- For **Home Assistant**, set `mqtt_enabled=true`, `mqtt_per_drone_enabled=true`, and `mqtt_ha_enabled=true`. DragonSync will auto‑create entities.
- For ADS‑B / 978, set `adsb_enabled=true` and ensure `adsb_json_url` points at your readsb API (`/?all_with_pos` is recommended).

---

## Home Assistant (MQTT)

### Broker
On the same machine as HA:
```bash
sudo apt install -y mosquitto mosquitto-clients
sudo systemctl enable --now mosquitto
# Optional user:
# sudo mosquitto_passwd -c /etc/mosquitto/passwd dragonsync
# and in /etc/mosquitto/conf.d/local.conf:
#   allow_anonymous false
#   password_file /etc/mosquitto/passwd
#   listener 1883 0.0.0.0
# sudo systemctl restart mosquitto
```

### Entities created by DragonSync
- **Device trackers**: `drone-<id>` (main dot), `pilot-<id-tail>`, `home-<id-tail>` (if pilot/home known).
- **Sensors**: lat/lon/alt/speed/vspeed/course/AGL/RSSI/freq_mhz/etc.
- **Signals (optional)**: if `mqtt_signals_enabled=true`, publishes alerts to `wardragon/signals`.
- **HA signal dot (optional)**: set `mqtt_ha_signal_tracker=true` to create a per‑kit “Signal Alert” device_tracker that jumps to the latest alert from that kit.

**Behavior on timeout**: when a drone stops updating for `inactivity_timeout`, DragonSync marks the trackers **offline** (hidden on the map) but **keeps last‑known location in HA history**.

**Verify MQTT traffic**
```bash
mosquitto_sub -h 127.0.0.1 -t 'homeassistant/#' -v
mosquitto_sub -h 127.0.0.1 -t 'wardragon/#' -v
```

### MQTT Payload Schema

For the complete JSON field reference for drones, signals, aircraft, and system status, see **[MQTT Payload Schema](docs/mqtt-schema.md)**.

---

## Static GPS (if no live GPS)

If the kit doesn’t have GPS lock (or you’re indoors), set a fixed location with `gps.ini` next to `dragonsync.py`:

```ini
[gps]
# If use_static_gps is true, use the values below as fixed position
use_static_gps = true
static_lat = 39.1234
static_lon = -77.5678
static_alt = 220
```

`wardragon_monitor.py` will use GPSD if available; otherwise it falls back to `gps.ini`.

---

## TAK / ATAK Output

### Multicast (no server)
- Use `enable_multicast=true` with the group/port above.
- In ATAK: add a “Network” multicast feed to the same address/port.
- Ensure your network allows multicast (IGMP snooping/firewall rules).

### TAK Server (unicast)
- Set `tak_host`, `tak_port`, `tak_protocol` (`tcp` or `udp`).
- For TLS servers, use **one** of:
  - `tak_tls_p12` + `tak_tls_p12_pass`, or
  - `tak_tls_certfile` + `tak_tls_keyfile` (+ optional `tak_tls_cafile`).
- You can use `tak_tls_skip_verify=true` for testing self‑signed certs (turn off in production).

### CoT Icons and UA Type
DragonSync uses the **UA Type** field from Remote ID to determine the CoT icon displayed in ATAK:

| UA Type | Description | CoT Type |
|---------|-------------|----------|
| 1 | Aeroplane (Fixed wing) | `a-f-A-f` (fixed-wing icon) |
| 2 | Helicopter / Multirotor | `a-u-A-M-H-R` (rotorcraft icon) |
| 3-4 | Gyroplane / VTOL | `a-u-A-M-H-R` (rotorcraft icon) |
| Other | Various | `a-u-A-M-H-R` (default rotorcraft) |

**Note:** The UA Type is broadcast by the drone's Remote ID transmitter and cannot be changed by DragonSync. If a quadcopter appears with a fixed-wing icon in ATAK, the RID transmitter was misconfigured by the manufacturer or operator to report the wrong UA Type.

---

## Lattice (optional)

Enable with `lattice_enabled=true` and set either `lattice_base_url` or `lattice_endpoint` plus `lattice_token`.  
`lattice_drone_rate`/`lattice_wd_rate` control update rates (Hz).

---

## Tips & Troubleshooting

- **No dots in ATAK (multicast)**: same VLAN/VPN, Wireshark `udp.port==6969`, check switch IGMP snooping.
- **No entities in HA**: ensure `mqtt_enabled=true`, `mqtt_per_drone_enabled=true`, `mqtt_ha_enabled=true`. Watch `homeassistant/#` for discovery messages.
- **Template warnings in HA**: DragonSync uses resilient templates (e.g., `| float(0)`), so you should not see float/None errors. If you customized templates, prefer `| float(0)`.
- **Entities don’t disappear**: your DragonSync `DroneManager` should call `mark_inactive(drone_id)` on timeout (the WarDragon repo includes this). That sets HA trackers to **offline** while preserving history.
- **TAK TLS**: verify `.p12` path/password or PEM paths; try `tak_tls_skip_verify=true` for dev.
- **OpenSSL 3 / legacy .p12**: older PKCS#12 files using RC2 may fail to load; convert to PEM or enable the legacy provider.
- **ADS-B issues**: verify `readsb` is running and that `curl http://127.0.0.1:8080/?all_with_pos` returns JSON with an `aircraft` array.

---

## License

Apache License 2.0 © 2025 cemaxecuter

See the `LICENSE` file in this repository for full text of the Apache License, Version 2.0.
