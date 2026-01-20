# Utils: Track Logging and Offline Viewer

## Track Logger (zmq_logger_for_kml.py)

**What it logs:**
- Drone tracks (Remote ID: DJI, BLE, Wi-Fi)
- Aircraft tracks (ADS-B)
- FPV signal detections (suscli/DragonOS)
- System status (GPS, health metrics)

**Output formats:**
- SQLite database (recommended, enables offline viewer)
- CSV (legacy, still supported)

**FAA Remote ID enrichment:**
- Looks up drone make/model from local FAA database
- Optional async API fallback (won't block logging)
- Adds `rid_make`, `rid_model`, `rid_source` to each record

**Examples:**

```bash
# Basic: CSV only
python utils/zmq_logger_for_kml.py --output-csv logs/tracks.csv

# SQLite with daily rotation (recommended)
python utils/zmq_logger_for_kml.py \
  --sqlite logs/tracks.sqlite \
  --sqlite-rotate-daily \
  --sqlite-retain-days 7

# Enable FAA RID enrichment
python utils/zmq_logger_for_kml.py \
  --rid-enabled \
  --sqlite logs/tracks.sqlite

# Enable FAA API fallback (async)
python utils/zmq_logger_for_kml.py \
  --rid-enabled \
  --rid-api \
  --sqlite logs/tracks.sqlite
```

**Key flags:**
- `--sqlite <path>` - Log to SQLite database (enables viewer)
- `--output-csv <path>` - Log to CSV (can use both CSV and SQLite)
- `--sqlite-rotate-daily` - Create per-day SQLite files (e.g., tracks-2026-01-19.sqlite)
- `--sqlite-retain-days N` - Auto-delete rotated files older than N days
- `--rid-enabled` - Enable FAA Remote ID lookup from local database
- `--rid-api` - Enable FAA API fallback (async, won't block)

**Database schema:**
All tracks include: timestamp, lat, lon, alt, speed, id, id_type, MAC, RSSI, freq, and FAA RID fields (make, model, source).

---

## Offline Viewer (log_viewer.py)

**What it does:**
- Web-based map + table viewer for SQLite logs
- Works offline (no external tile dependencies)
- Filter by drone ID, RID make/model/source, time range
- Display limit control (performance)

**Usage:**

```bash
# Start viewer on default port 5001
python utils/log_viewer.py --db logs/tracks.sqlite

# Custom port
python utils/log_viewer.py --db logs/tracks.sqlite --port 8080

# Rotated daily logs (viewer auto-handles)
python utils/log_viewer.py --db logs/tracks-2026-01-19.sqlite
```

Then open `http://127.0.0.1:5001` in your browser.

**Features:**
- Canvas-based offline map (no internet required)
- Real-time filters (drone ID, RID make/model/source)
- Time range selection
- Display limit (500/1000/5000/all)
- Click tracks for details

**Note:** Future versions will replace canvas map with Leaflet for better UX.
