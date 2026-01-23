# Utils: Drone Logging and Offline Viewer

## Drone Logger (drone_logger.py)

**What it logs:**
- Drone tracks from Remote ID (DJI, BLE, Wi-Fi)
- Pilot locations (when broadcast)
- Home points (when broadcast)
- System GPS location (optional, for context)

**Note:** Aircraft (ADS-B) and FPV signals are available via the DragonSync API but not logged by this tool. For multi-kit aggregation and all data types, see WarDragon Analytics (future).

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
python utils/drone_logger.py --output-csv logs/drones.csv

# SQLite with daily rotation (recommended)
python utils/drone_logger.py \
  --sqlite logs/drones.sqlite \
  --sqlite-rotate-daily \
  --sqlite-retain-days 7

# Enable FAA RID enrichment
python utils/drone_logger.py \
  --rid-enabled \
  --sqlite logs/drones.sqlite

# Enable FAA API fallback (async)
python utils/drone_logger.py \
  --rid-enabled \
  --rid-api \
  --sqlite logs/drones.sqlite

# Include system GPS location for context
python utils/drone_logger.py \
  --sqlite logs/drones.sqlite \
  --include-system-location \
  --zmq-status-port 5557
```

**Key flags:**
- `--sqlite <path>` - Log to SQLite database (enables viewer)
- `--output-csv <path>` - Log to CSV (can use both CSV and SQLite)
- `--sqlite-rotate-daily` - Create per-day SQLite files (e.g., drones-2026-01-19.sqlite)
- `--sqlite-retain-days N` - Auto-delete rotated files older than N days
- `--rid-enabled` - Enable FAA Remote ID lookup from local database
- `--rid-api` - Enable FAA API fallback (async, won't block)
- `--include-system-location` - Log system GPS for context
- `--zmq-status-port` - Status socket port (default: 5557)

**Database schema:**
Logs include: timestamp, drone_id, lat, lon, alt, speed, pilot location, home location, MAC, RSSI, freq, UA type, operator ID, and FAA RID fields (make, model, source).

---

## Offline Viewer (log_viewer.py)

**What it does:**
- Web-based map + table viewer for drone SQLite logs
- Leaflet.js interactive map (can work offline with cached tiles)
- Filter by drone ID, RID make/model/source, time range
- Live auto-refresh option for active operations
- CSV export of filtered results

**Usage:**

```bash
# Start viewer on default port 5001
python utils/log_viewer.py --db logs/drones.sqlite

# Custom port
python utils/log_viewer.py --db logs/drones.sqlite --port 8080

# Live mode (auto-refresh every 5 seconds)
python utils/log_viewer.py --db logs/drones.sqlite --live --refresh-interval 5

# Rotated daily logs (viewer auto-handles)
python utils/log_viewer.py --db logs/drones-2026-01-19.sqlite
```

Then open `http://127.0.0.1:5001` in your browser.

**Features:**
- Leaflet.js map with zoom, pan, layer controls
- Offline-capable (uses cached tiles when available)
- Real-time filters (drone ID, RID make/model/source)
- Time range selection with better date picker
- Display limit (500/1000/5000/all)
- Click drone → show full track history with timeline
- CSV export button for filtered results
- Optional live mode with auto-refresh
- Show pilot and home locations on map

**Map tile options:**
- Online: OpenStreetMap tiles (default, requires internet)
- Offline: Cached tiles from previous sessions
- Hybrid: Falls back to offline tiles when internet unavailable
