# ADS-B / 978 Integration

DragonSync can ingest aircraft data from a local `readsb` instance via HTTP and convert it to CoT for TAK/ATAK.

> **Status:** Experimental. This is currently a multi-step and somewhat manual process.

## Overview

```
readsb (SDR → 1090/978 MHz) → HTTP API → DragonSync → CoT
```

DragonSync polls the readsb HTTP API and builds CoT messages per aircraft with:
- Position, altitude (geometric/barometric), speed, track
- Richer remarks (hex, callsign, squawk, registration, category, on-ground flag)
- CE/LE accuracy derived from NACp/NACv when available

## SDR Considerations

At the moment, only one SDR-driven role can use the same RF front-end at once:

| Configuration | Use Case |
|---------------|----------|
| **Single SDR (AntSDR)** | Either drone detection OR ADS-B, not both simultaneously |
| **Multiple SDRs** | Dedicated SDR for drones + separate SDR for ADS-B |

### Single SDR

You can either:
- Run DJI/FPV-related tasks, **or**
- Run `readsb` for ADS-B / 978

Switching roles means stopping one and starting the other. This is best used for demo/experiment modes.

### Multiple SDRs (Recommended)

For continuous drone + aircraft coverage:
- One SDR path for **drone detection** (DJI / RID)
- Another SDR (RTL-SDR, second AntSDR, etc.) for **ADS-B / 978** with its own `readsb` instance

You can run readsb with a different device selection and still point DragonSync at its API.

---

## Setup

### 1. Start readsb

#### Pluto / AntSDR Example

Using the AntSDR in Pluto-compatible mode via SoapySDR:

```bash
sudo readsb \
  --device-type soapysdr \
  --soapy-device="driver=plutosdr" \
  --freq=1090000000 \
  --no-interactive \
  --write-json=/run/readsb \
  --write-json-every=1 \
  --json-location-accuracy=2 \
  --net-bind-address=0.0.0.0 \
  --net-api-port=8080 \
  --soapy-enable-agc \
  --sdr-buffer-size=128
```

#### RTL-SDR Example

```bash
sudo readsb \
  --device-type rtlsdr \
  --freq=1090000000 \
  --no-interactive \
  --write-json=/run/readsb \
  --write-json-every=1 \
  --json-location-accuracy=2 \
  --net-bind-address=0.0.0.0 \
  --net-api-port=8080
```

#### Key Options

| Option | Description |
|--------|-------------|
| `--freq=1090000000` | 1090 MHz for standard ADS-B |
| `--freq=978000000` | 978 MHz for UAT (US only) |
| `--net-api-port=8080` | HTTP API port |
| `--device-type` | `soapysdr`, `rtlsdr`, etc. |
| `--soapy-device` | SoapySDR device string |

### 2. Verify readsb

Test the HTTP API:

```bash
curl -s http://127.0.0.1:8080/?all_with_pos | jq '.aircraft | length'
```

You should see a count of aircraft with positions. If you see `0` or an error, readsb isn't receiving data.

### 3. Configure DragonSync

Add to your `config.ini`:

```ini
[SETTINGS]

# ADS-B / UAT aircraft ingestion
adsb_enabled = true
adsb_json_url = http://127.0.0.1:8080/?all_with_pos

# Optional altitude gates (feet). 0 = disabled.
adsb_min_alt = 0
adsb_max_alt = 0
```

#### Altitude Filtering

You can filter aircraft by altitude:

```ini
# Only show aircraft below 10,000 feet
adsb_max_alt = 10000

# Only show aircraft above 1,000 feet (ignore ground traffic)
adsb_min_alt = 1000

# Both: 1,000 to 10,000 feet
adsb_min_alt = 1000
adsb_max_alt = 10000
```

Set to `0` to disable filtering.

---

## How It Works

1. DragonSync polls `adsb_json_url` once per `poll_interval`
2. Expects readsb-style JSON with an `aircraft` array
3. For each aircraft with a valid position:
   - Builds a CoT message with position, altitude, speed, track
   - Includes hex code, callsign, squawk, registration, category
   - Derives accuracy (CE/LE) from NACp/NACv when available
4. Outputs CoT via configured TAK server or multicast

### CoT Mapping

| readsb Field | CoT Element |
|--------------|-------------|
| `hex` | UID suffix |
| `lat`, `lon` | Point position |
| `alt_geom` or `alt_baro` | HAE (converted to meters) |
| `gs` | Speed (converted to m/s) |
| `track` | Course |
| `flight` | Callsign in remarks |
| `squawk` | Squawk in remarks |
| `category` | Aircraft category in remarks |
| `nac_p`, `nac_v` | CE/LE accuracy |

---

## MQTT Output

If MQTT is enabled with `aircraft_enabled = true`, aircraft are published to `wardragon/aircraft`:

```json
{
  "icao": "A12345",
  "callsign": "UAL123",
  "registration": "N12345",
  "lat": 39.1234,
  "lon": -77.5678,
  "alt": 35000,
  "speed": 450,
  "track": 270,
  "squawk": "1200",
  "category": "A3",
  "on_ground": false,
  "track_type": "aircraft"
}
```

See [mqtt-schema.md](mqtt-schema.md) for the complete field reference.

---

## Troubleshooting

| Issue | Solution |
|-------|----------|
| No aircraft in ATAK | Verify `curl http://127.0.0.1:8080/?all_with_pos` returns aircraft |
| readsb not starting | Check SDR device permissions, antenna connection |
| Only some aircraft appear | Enable `/?all_with_pos` not just `/?` which requires positions |
| High CPU usage | Increase `poll_interval` in config |

### Common readsb Issues

**Permission denied on SDR:**
```bash
# Add udev rules for RTL-SDR
sudo cp rtl-sdr.rules /etc/udev/rules.d/
sudo udevadm control --reload-rules
```

**SoapySDR device not found:**
```bash
# List available devices
SoapySDRUtil --find
```

---

## Frequency Reference

| Frequency | Service | Region |
|-----------|---------|--------|
| 1090 MHz | ADS-B (Mode S) | Worldwide |
| 978 MHz | UAT (ADS-B) | United States only |

Note: 978 MHz UAT is only used in the US below 18,000 feet. International flights and high-altitude traffic use 1090 MHz exclusively.
