# DragonSync (Community Edition)

A lightweight gateway that turns WarDragon’s drone detections into **Cursor on Target (CoT)** for TAK/ATAK, and (optionally) publishes per‑drone telemetry to **Lattice** as well as to **MQTT** for **Home Assistant**. This README focuses on the **WarDragon** kit where everything (drivers, sniffers, ZMQ monitor) is already set up—so you mostly just configure and run **DragonSync (Community Edition)**.

DragonSync can also ingest **ADS‑B / UAT (978 MHz)** aircraft data from a local `readsb` instance and convert that into CoT alongside your drone detections.

---

## Features  

- **Remote ID Drone Detection:**  
   Uses [DroneID](https://github.com/alphafox02/DroneID) to detect Bluetooth Remote ID signals. Thanks to @bkerler for this fantastic tool. WiFi Remote ID is currently handled by an ESP32.
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

ZMQ 4224 + ZMQ 4225 + (HTTP) --> DragonSync --> CoT (multicast/TAK)
                                              \-> MQTT (aggregate + per-drone)
                                              \-> Lattice (optional)
```

- **ZMQ 4224**: stream of decoded Remote ID / DJI frames.
- **ZMQ 4225**: WarDragon system/GPS info from `wardragon_monitor.py`.
- **readsb HTTP API**: aircraft list from local SDR(s), if enabled.
- **DragonSync** merges streams, rate‑limits, and outputs:
  - **CoT** to ATAK/WinTAK via **multicast** _or_ **TAK server** (TCP/UDP, optional TLS).
  - **MQTT** (per‑drone JSON + HA discovery) for dashboards and a live map in Home Assistant.
  - **Lattice** export for Anduril Lattice, if configured.

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

## ADS‑B / 978 Integration (Experimental)

DragonSync can ingest aircraft data from a local `readsb` instance via HTTP. This is currently a **multi‑step and somewhat manual process**, and there are trade‑offs with SDR usage:

- You can dedicate a **separate SDR** to ADS‑B / 978.
- Or temporarily **stop the drone routine on the AntSDR** and repurpose its SDR path for ADS‑B.

At the moment, only one of these SDR‑driven roles can use the same RF front‑end at once (e.g., AntSDR focusing on DJI vs ADS‑B). A future WarDragon Pro image will make this smoother, but the flow below works today.

### 1. Start `readsb` (Pluto / AntSDR example)

Assuming `readsb` is built/installed and you’re using the AntSDR in its Pluto‑compatible mode via SoapySDR:

```bash
sudo readsb --device-type soapysdr --soapy-device="driver=plutosdr" --freq=1090000000 --no-interactive --write-json=/run/readsb --write-json-every=1 --json-location-accuracy=2 --net-bind-address=0.0.0.0 --net-api-port=8080 --soapy-enable-agc --sdr-buffer-size=128
```

Notes:

- This example tunes **1090 MHz** for standard ADS‑B.
- For other SDRs, adjust `--device-type` and `--soapy-device` (or use native `--device-type` options like `rtlsdr`).
- `--net-api-port=8080` exposes the readsb HTTP API.
- DragonSync reads from `http://127.0.0.1:8080/?all_with_pos`.

### 2. Configure DragonSync to consume readsb

In your `config.ini`, add or update ADS‑B settings (example names shown; adjust to match your actual config):

```ini
[SETTINGS]

# ... existing settings above ...

# ADS-B / UAT aircraft ingestion (optional)
adsb_enabled = true
adsb_json_url = http://127.0.0.1:8080/?all_with_pos

# Optional altitude gates (feet). 0 = disabled.
adsb_min_alt = 0
adsb_max_alt = 0
```

DragonSync’s ADS‑B worker:

- Polls `adsb_json_url` once per `poll_interval`.
- Expects readsb‑style JSON with an `aircraft` list (which `/?all_with_pos` provides).
- Builds CoT per aircraft with:
  - position, altitude (geom/baro), speed, track
  - richer remarks (hex, callsign, squawk, reg, category, on‑ground flag)
  - CE/LE derived from NACp/NACv when available.

### 3. Considerations for 1090 vs 978 and SDR usage

- **Single SDR (AntSDR)**  
  - You can either:
    - Run DJI/FPV‑related tasks **or**
    - Run `readsb` for ADS‑B / 978
  - Switching roles means stopping one and starting the other; this is best used for **demo/experiment** modes for now.
- **Multiple SDRs**  
  - For best results (continuous drone + aircraft coverage), dedicate:
    - One SDR path to **drone detection** (DJI / RID).
    - Another SDR (RTL‑SDR, second AntSDR, etc.) to **ADS‑B / 978** with its own `readsb` instance.
  - You can run readsb with a different device selection and still point DragonSync at its API.

Future versions may support more automated orchestration, but the above is the current working approach.

---

## `config.ini` (WarDragon‑tuned example)

```ini
[SETTINGS]

# ZMQ inputs (WarDragon defaults)
zmq_host = 127.0.0.1
zmq_port = 4224          # Drone telemetry stream
zmq_status_port = 4225   # WarDragon monitor (GPS, system)

# TAK Server output (optional). If blank, TAK server is disabled.
tak_host =
tak_port =
tak_protocol =           # "tcp" or "udp"
tak_tls_p12 =
tak_tls_p12_pass =
tak_tls_skip_verify = true

# Multicast CoT to ATAK (simple zero‑server option)
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

# Needed for HA auto‑discovery (per‑drone topics)
per_drone_enabled = true
per_drone_base = wardragon/drone
ha_enabled = true
ha_prefix = homeassistant
ha_device_base = wardragon_drone

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
```

**Notes**
- For ATAK on the same LAN/VPN, multicast is easiest (`enable_multicast=true`). In ATAK, add a Network feed for the same group/port.
- For a TAK server, fill `tak_host`, `tak_port`, and `tak_protocol`. Add TLS fields if required by your server.
- For **Home Assistant**, set `mqtt_enabled=true`, `per_drone_enabled=true`, and `ha_enabled=true`. DragonSync will auto‑create entities.
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

**Behavior on timeout**: when a drone stops updating for `inactivity_timeout`, DragonSync marks the trackers **offline** (hidden on the map) but **keeps last‑known location in HA history**.

**Verify MQTT traffic**
```bash
mosquitto_sub -h 127.0.0.1 -t 'homeassistant/#' -v
mosquitto_sub -h 127.0.0.1 -t 'wardragon/#' -v
```

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
- For TLS servers, set `tak_tls_p12` and `tak_tls_p12_pass`.
- You can use `tak_tls_skip_verify=true` for testing self‑signed certs (turn off in production).

---

## Lattice (optional)

Enable with `lattice_enabled=true` and set either `lattice_base_url` or `lattice_endpoint` plus `lattice_token`.  
`lattice_drone_rate`/`lattice_wd_rate` control update rates (Hz).

---

## Tips & Troubleshooting

- **No dots in ATAK (multicast)**: same VLAN/VPN, Wireshark `udp.port==6969`, check switch IGMP snooping.
- **No entities in HA**: ensure `mqtt_enabled=true`, `per_drone_enabled=true`, `ha_enabled=true`. Watch `homeassistant/#` for discovery messages.
- **Template warnings in HA**: DragonSync uses resilient templates (e.g., `| float(0)`), so you should not see float/None errors. If you customized templates, prefer `| float(0)`.
- **Entities don’t disappear**: your DragonSync `DroneManager` should call `mark_inactive(drone_id)` on timeout (the WarDragon repo includes this). That sets HA trackers to **offline** while preserving history.
- **TAK TLS**: verify `.p12` path/password; try `tak_tls_skip_verify=true` for dev.
- **ADS-B issues**: verify `readsb` is running and that `curl http://127.0.0.1:8080/?all_with_pos` returns JSON with an `aircraft` array.

---

## License

Apache License 2.0 © 2025 cemaxecuter

See the `LICENSE` file in this repository for full text of the Apache License, Version 2.0.
