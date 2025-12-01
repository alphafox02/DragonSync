# Utils: RID-aware logging and viewer

## ZMQ logger (RID + SQLite)

Log telemetry from the ZMQ feed, enriched with FAA RID data (local DB, optional async API fallback).

Examples:
```bash
# Basic: CSV only
python utils/zmq_logger_for_kml.py --output-csv logs/drone_log.csv

# RID enrichment + SQLite (daily rotation, keep 7 days)
python utils/zmq_logger_for_kml.py \
  --rid-enabled \
  --sqlite logs/drone_log.sqlite \
  --sqlite-rotate-daily \
  --sqlite-retain-days 7

# Enable FAA API fallback (async; won’t block logging)
python utils/zmq_logger_for_kml.py --rid-enabled --rid-api --sqlite logs/drone_log.sqlite
```

Key flags:
- `--rid-enabled` (use local FAA DB), `--rid-api` (async FAA API fallback)
- `--sqlite <path>` to log to SQLite; `--sqlite-rotate-daily` for per-day files; `--sqlite-retain-days N` to prune old rotated files
- `--output-csv` still available; you can use both CSV and SQLite together

RID columns emitted: `rid_make`, `rid_model`, `rid_source`.

## Offline viewer

Serve a small map + table UI against the SQLite log (offline-safe canvas map):
```bash
python utils/log_viewer.py --db logs/drone_log.sqlite --port 5001
```
Then open `http://127.0.0.1:5001`. Filters: drone id, RID make/model/source, time range, limit. Uses the same RID columns logged above. No external tiles required.
