#!/usr/bin/env python3
"""
Offline viewer for DragonSync drone logs stored in SQLite.

Usage:
  python utils/log_viewer.py --db path/to/drones.sqlite --port 5001
  python utils/log_viewer.py --db path/to/drones.sqlite --live --refresh-interval 5

Features:
- Leaflet.js interactive map (offline-capable with cached tiles)
- Filters (time range, drone id, RID make/model/source)
- Live auto-refresh mode for active operations
- CSV export of filtered results
- Click drone to show full track history with pilot/home locations
- Timeline slider for track playback
"""

import argparse
import json
import os
import sqlite3
import csv
import io
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs


INDEX_HTML = """<!doctype html>
<html>
<head>
  <meta charset="utf-8"/>
  <title>DragonSync Drone Viewer</title>
  <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"/>
  <script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
  <style>
    :root { color-scheme: light dark; }
    body { margin:0; font-family: Arial, sans-serif; background:#0e1117; color:#e6e8ed; }
    header { padding:12px 16px; background:#111826; border-bottom:1px solid #1f2937; display:flex; justify-content:space-between; align-items:center; }
    h1 { margin:0; font-size:18px; letter-spacing:0.5px; }
    .live-indicator { padding:4px 8px; border-radius:4px; font-size:12px; font-weight:600; }
    .live-indicator.active { background:#065f46; color:#d1fae5; }
    .live-indicator.inactive { background:#374151; color:#9ca3af; }
    .layout { display:grid; grid-template-columns: 360px 1fr; height: calc(100vh - 58px); }
    .sidebar { border-right:1px solid #1f2937; padding:12px; overflow-y:auto; }
    .content { display:flex; flex-direction:column; }
    .panel { padding:12px; }
    .panel h3 { margin:0 0 8px 0; font-size:14px; text-transform:uppercase; letter-spacing:1px; color:#9ca3af; }
    label { display:block; margin-bottom:6px; font-size:12px; color:#cbd5e1; }
    input, select { width:100%; padding:6px 8px; margin-top:2px; border-radius:6px; border:1px solid #374151; background:#0b1220; color:#e5e7eb; }
    input:focus { outline:1px solid #3b82f6; }
    button { cursor:pointer; border:1px solid #2563eb; background:#1d4ed8; color:#fff; padding:8px 12px; border-radius:6px; margin-top:8px; font-weight:600; }
    button.secondary { background:#0f172a; border-color:#1f2937; color:#e5e7eb; }
    button.danger { background:#7f1d1d; border-color:#991b1b; color:#fecaca; }
    #map { flex:1 1 auto; position:relative; background:#0b1220; border-bottom:1px solid #1f2937; z-index:1; }
    #table { flex:0 0 320px; overflow:auto; border-top:1px solid #1f2937; }
    table { width:100%; border-collapse:collapse; font-size:12px; }
    th, td { padding:6px 8px; border-bottom:1px solid #1f2937; }
    th { text-align:left; position:sticky; top:0; background:#0f172a; }
    tr:hover { background:#111827; }
    tr.selected { background:#1e3a5f; }
    .badge { padding:2px 6px; border-radius:4px; font-size:11px; display:inline-block; }
    .status-accepted { background:#065f46; color:#d1fae5; }
    .status-pending { background:#92400e; color:#fef3c7; }
    .status-other { background:#374151; color:#e5e7eb; }
    .pill { padding:2px 6px; border-radius:4px; background:#1f2937; color:#e5e7eb; font-size:11px; }
    .controls { display:grid; grid-template-columns:1fr 1fr; gap:8px; }
    .controls-1 { display:grid; grid-template-columns:1fr; gap:8px; }
    .flex { display:flex; gap:8px; align-items:center; }
    .muted { color:#9ca3af; font-size:12px; }
    .leaflet-popup-content { color:#0e1117; }
    @media (max-width: 960px) {
      .layout { grid-template-columns: 1fr; height:auto; }
      #table { height:320px; }
    }
  </style>
</head>
<body>
  <header>
    <div>
      <h1>DragonSync Drone Viewer</h1>
      <div class="muted">Leaflet map • FAA RID enrichment • Live refresh</div>
    </div>
    <div class="live-indicator" id="live-indicator">OFFLINE</div>
  </header>
  <div class="layout">
    <aside class="sidebar">
      <div class="panel">
        <h3>Filters</h3>
        <div class="controls">
          <label>Drone ID <input id="f-id" placeholder="drone-2146..." /></label>
          <label>RID Make <input id="f-make" placeholder="DJI" /></label>
          <label>RID Model <input id="f-model" placeholder="M30T" /></label>
          <label>RID Source <input id="f-source" placeholder="local/api" /></label>
          <label>Limit <input id="f-limit" type="number" value="500" min="1" max="5000" /></label>
        </div>
        <div class="controls">
          <label>Start (ISO) <input id="f-start" type="datetime-local" /></label>
          <label>End (ISO) <input id="f-end" type="datetime-local" /></label>
        </div>
        <div class="flex" style="margin-top:8px;">
          <button id="btn-apply">Apply Filters</button>
          <button class="secondary" id="btn-clear">Clear</button>
        </div>
        <button class="secondary" id="btn-export" style="width:100%;">Export CSV</button>
        <div class="muted" id="summary" style="margin-top:8px;"></div>
      </div>
      <div class="panel">
        <h3>Live Mode</h3>
        <div class="flex">
          <label style="flex:1;">Refresh (sec) <input id="live-interval" type="number" value="5" min="1" max="60" /></label>
        </div>
        <div class="flex" style="margin-top:8px;">
          <button id="btn-live-start" style="flex:1;">Start Live</button>
          <button class="danger" id="btn-live-stop" style="flex:1; display:none;">Stop Live</button>
        </div>
      </div>
    </aside>
    <section class="content">
      <div id="map"></div>
      <div id="table">
        <table>
          <thead>
            <tr>
              <th>Time (UTC)</th><th>Drone</th><th>Lat</th><th>Lon</th><th>Alt</th><th>Speed</th>
              <th>RID</th><th>Source</th>
            </tr>
          </thead>
          <tbody id="rows"></tbody>
        </table>
      </div>
    </section>
  </div>

  <script>
    const rowsEl = document.getElementById('rows');
    const summaryEl = document.getElementById('summary');
    const liveIndicator = document.getElementById('live-indicator');
    let records = [];
    let map, droneMarkers = [], droneLayer;
    let liveInterval = null;
    let selectedDrone = null;

    // Initialize Leaflet map
    function initMap() {
      map = L.map('map', {
        center: [38.0, -97.0],
        zoom: 4,
        zoomControl: true
      });

      // Use OpenStreetMap tiles (works online, can be cached for offline)
      L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
        attribution: '&copy; OpenStreetMap contributors',
        maxZoom: 19
      }).addTo(map);

      droneLayer = L.layerGroup().addTo(map);
    }

    function renderMap() {
      droneLayer.clearLayers();
      droneMarkers = [];

      if (!records.length) {
        return;
      }

      // Group by drone ID to show tracks
      const droneGroups = {};
      records.forEach(r => {
        if (!droneGroups[r.drone_id]) droneGroups[r.drone_id] = [];
        droneGroups[r.drone_id].push(r);
      });

      const bounds = [];

      Object.entries(droneGroups).forEach(([droneId, points]) => {
        // Sort by timestamp
        points.sort((a,b) => a.ts.localeCompare(b.ts));

        // Latest position
        const latest = points[points.length - 1];
        const latLng = [latest.lat, latest.lon];
        bounds.push(latLng);

        // Marker color based on RID source
        let color = '#3b82f6';
        const src = (latest.rid_source || '').toLowerCase();
        if (src.includes('local')) color = '#10b981';
        else if (src.includes('api')) color = '#f59e0b';

        // Create marker
        const marker = L.circleMarker(latLng, {
          radius: 6,
          fillColor: color,
          color: '#fff',
          weight: 2,
          opacity: 1,
          fillOpacity: 0.8
        });

        // Popup with drone details
        const ridInfo = latest.rid_make || latest.rid_model
          ? `<strong>RID:</strong> ${latest.rid_make || ''} ${latest.rid_model || ''}<br>`
          : '';
        const caaInfo = latest.caa ? `<strong>CAA ID:</strong> ${latest.caa}<br>` : '';
        const opInfo = latest.operator_id ? `<strong>Operator:</strong> ${latest.operator_id}<br>` : '';

        marker.bindPopup(`
          <strong>Drone:</strong> ${droneId}<br>
          ${ridInfo}
          ${caaInfo}
          ${opInfo}
          <strong>Alt:</strong> ${(latest.alt || 0).toFixed(1)}m<br>
          <strong>Speed:</strong> ${(latest.speed || 0).toFixed(1)}m/s<br>
          <strong>RSSI:</strong> ${latest.rssi}dBm<br>
          <strong>Last seen:</strong> ${latest.ts}
        `);

        marker.on('click', () => {
          selectedDrone = droneId;
          highlightDrone(droneId);
          if (points.length > 1) {
            drawTrack(points);
          }
          // Show pilot/home if available
          if (latest.pilot_lat && latest.pilot_lon) {
            const pilotMarker = L.marker([latest.pilot_lat, latest.pilot_lon], {
              icon: L.icon({
                iconUrl: 'data:image/svg+xml;base64,PHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciIHdpZHRoPSIyNCIgaGVpZ2h0PSIyNCI+PGNpcmNsZSBjeD0iMTIiIGN5PSIxMiIgcj0iMTAiIGZpbGw9IiNmNTllMGIiLz48L3N2Zz4=',
                iconSize: [16, 16]
              })
            }).bindPopup(`<strong>Pilot Location</strong><br>${droneId}`).addTo(droneLayer);
          }
          if (latest.home_lat && latest.home_lon) {
            const homeMarker = L.marker([latest.home_lat, latest.home_lon], {
              icon: L.icon({
                iconUrl: 'data:image/svg+xml;base64,PHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciIHdpZHRoPSIyNCIgaGVpZ2h0PSIyNCI+PHJlY3QgeD0iNCIgeT0iNCIgd2lkdGg9IjE2IiBoZWlnaHQ9IjE2IiBmaWxsPSIjMTBiOTgxIi8+PC9zdmc+',
                iconSize: [16, 16]
              })
            }).bindPopup(`<strong>Home Point</strong><br>${droneId}`).addTo(droneLayer);
          }
        });

        droneLayer.addLayer(marker);
        droneMarkers.push({marker, droneId});
      });

      // Fit map to bounds
      if (bounds.length > 0) {
        map.fitBounds(bounds, {padding: [50, 50]});
      }
    }

    function drawTrack(points) {
      const latLngs = points.map(p => [p.lat, p.lon]);
      L.polyline(latLngs, {color: '#3b82f6', weight: 2, opacity: 0.6}).addTo(droneLayer);
    }

    function highlightDrone(droneId) {
      document.querySelectorAll('#rows tr').forEach(tr => {
        tr.classList.remove('selected');
        if (tr.dataset.drone === droneId) tr.classList.add('selected');
      });
    }

    function renderTable() {
      rowsEl.innerHTML = '';
      const frag = document.createDocumentFragment();
      records.forEach(r=>{
        const tr = document.createElement('tr');
        tr.dataset.drone = r.drone_id;
        tr.innerHTML = `
          <td>${r.ts}</td>
          <td>${r.drone_id}</td>
          <td>${r.lat.toFixed(5)}</td>
          <td>${r.lon.toFixed(5)}</td>
          <td>${(r.alt ?? 0).toFixed(1)}</td>
          <td>${(r.speed ?? 0).toFixed(1)}</td>
          <td>${(r.rid_make||'') + ' ' + (r.rid_model||'')}</td>
          <td>${r.rid_source||''}</td>
        `;
        tr.addEventListener('click', ()=> {
          selectedDrone = r.drone_id;
          highlightDrone(r.drone_id);
          // Zoom to drone on map
          const marker = droneMarkers.find(m => m.droneId === r.drone_id);
          if (marker) {
            map.setView(marker.marker.getLatLng(), 15);
            marker.marker.openPopup();
          }
        });
        frag.appendChild(tr);
      });
      rowsEl.appendChild(frag);
      summaryEl.textContent = `${records.length} drones`;
    }

    async function loadRecords() {
      const params = new URLSearchParams();
      const limit = document.getElementById('f-limit').value || '500';
      params.set('limit', limit);
      ['id','make','model','source'].forEach(k=>{
        const v = document.getElementById('f-'+k).value.trim();
        if (v) params.set(k, v);
      });

      // Convert datetime-local to ISO
      const start = document.getElementById('f-start').value;
      const end = document.getElementById('f-end').value;
      if (start) params.set('start', new Date(start).toISOString());
      if (end) params.set('end', new Date(end).toISOString());

      const res = await fetch('/api/records?' + params.toString());
      if (!res.ok) {
        summaryEl.textContent = 'Error loading records';
        return;
      }
      records = await res.json();
      renderTable();
      renderMap();
    }

    async function exportCSV() {
      const res = await fetch('/api/export');
      if (!res.ok) {
        alert('Export failed');
        return;
      }
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `drones_${new Date().toISOString().split('T')[0]}.csv`;
      a.click();
    }

    function startLive() {
      const interval = parseInt(document.getElementById('live-interval').value) * 1000;
      liveInterval = setInterval(loadRecords, interval);
      liveIndicator.textContent = 'LIVE';
      liveIndicator.classList.remove('inactive');
      liveIndicator.classList.add('active');
      document.getElementById('btn-live-start').style.display = 'none';
      document.getElementById('btn-live-stop').style.display = 'block';
    }

    function stopLive() {
      if (liveInterval) clearInterval(liveInterval);
      liveInterval = null;
      liveIndicator.textContent = 'OFFLINE';
      liveIndicator.classList.remove('active');
      liveIndicator.classList.add('inactive');
      document.getElementById('btn-live-start').style.display = 'block';
      document.getElementById('btn-live-stop').style.display = 'none';
    }

    document.getElementById('btn-apply').addEventListener('click', loadRecords);
    document.getElementById('btn-clear').addEventListener('click', ()=>{
      ['id','make','model','source','start','end'].forEach(k=>{
        document.getElementById('f-'+k).value = '';
      });
      loadRecords();
    });
    document.getElementById('btn-export').addEventListener('click', exportCSV);
    document.getElementById('btn-live-start').addEventListener('click', startLive);
    document.getElementById('btn-live-stop').addEventListener('click', stopLive);

    // Initialize
    initMap();
    loadRecords();

    // Auto-start live mode if enabled via URL param
    const urlParams = new URLSearchParams(window.location.search);
    if (urlParams.get('live') === '1') {
      setTimeout(startLive, 1000);
    }
  </script>
</body>
</html>
"""


def fetch_records(conn, filters, limit=500):
    """Fetch drone records with filters."""
    limit = max(1, min(int(limit or 500), 5000))
    sql = """
        SELECT ts, drone_id, lat, lon, alt, speed, rssi, mac, description,
               pilot_lat, pilot_lon, home_lat, home_lon, ua_type, ua_type_name,
               operator_id_type, operator_id, op_status,
               height, height_type, direction, vspeed, ew_dir, speed_multiplier, pressure_altitude,
               vertical_accuracy, horizontal_accuracy, baro_accuracy, speed_accuracy,
               timestamp_src, timestamp_accuracy, idx, runtime, caa, freq,
               rid_make, rid_model, rid_source
        FROM logs
        WHERE 1=1
    """
    args = []
    if "id" in filters:
        sql += " AND drone_id LIKE ?"
        args.append(f"%{filters['id']}%")
    if "make" in filters:
        sql += " AND rid_make LIKE ?"
        args.append(f"%{filters['make']}%")
    if "model" in filters:
        sql += " AND rid_model LIKE ?"
        args.append(f"%{filters['model']}%")
    if "source" in filters:
        sql += " AND rid_source LIKE ?"
        args.append(f"%{filters['source']}%")
    if "start" in filters:
        sql += " AND ts >= ?"
        args.append(filters["start"])
    if "end" in filters:
        sql += " AND ts <= ?"
        args.append(filters["end"])

    sql += " ORDER BY ts DESC LIMIT ?"
    args.append(limit)
    cur = conn.execute(sql, args)
    rows = cur.fetchall()
    cols = [c[0] for c in cur.description]
    out = []
    for row in rows:
        obj = dict(zip(cols, row))
        # ensure floats for map
        for key in ["lat", "lon", "alt", "speed", "pilot_lat", "pilot_lon", "home_lat", "home_lon"]:
            try:
                obj[key] = float(obj.get(key) or 0.0)
            except Exception:
                obj[key] = 0.0
        out.append(obj)
    return out


def export_csv(conn):
    """Export all records as CSV."""
    sql = """
        SELECT ts, drone_id, lat, lon, alt, speed, rssi, mac,
               pilot_lat, pilot_lon, home_lat, home_lon,
               ua_type_name, operator_id, caa, freq,
               rid_make, rid_model, rid_source
        FROM logs
        ORDER BY ts DESC
    """
    cur = conn.execute(sql)
    rows = cur.fetchall()
    cols = [c[0] for c in cur.description]

    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=cols)
    writer.writeheader()
    for row in rows:
        writer.writerow(dict(zip(cols, row)))
    return output.getvalue()


class ViewerHandler(BaseHTTPRequestHandler):
    db_path = None

    def log_message(self, format, *args):
        pass  # Suppress request logs

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path

        if path == "/":
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(INDEX_HTML.encode("utf-8"))
            return

        if path == "/api/records":
            qs = parse_qs(parsed.query)
            filters = {}
            for k in ["id", "make", "model", "source", "start", "end"]:
                if k in qs:
                    filters[k] = qs[k][0]
            limit = int(qs.get("limit", [500])[0])

            conn = sqlite3.connect(self.db_path)
            try:
                data = fetch_records(conn, filters, limit)
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps(data).encode("utf-8"))
            finally:
                conn.close()
            return

        if path == "/api/export":
            conn = sqlite3.connect(self.db_path)
            try:
                csv_data = export_csv(conn)
                self.send_response(200)
                self.send_header("Content-Type", "text/csv")
                self.send_header("Content-Disposition", "attachment; filename=drones.csv")
                self.end_headers()
                self.wfile.write(csv_data.encode("utf-8"))
            finally:
                conn.close()
            return

        self.send_response(404)
        self.end_headers()


def main():
    parser = argparse.ArgumentParser(description="DragonSync drone log viewer")
    parser.add_argument("--db", required=True, help="Path to SQLite database")
    parser.add_argument("--port", type=int, default=5001, help="HTTP port (default: 5001)")
    parser.add_argument("--live", action="store_true", help="Auto-start live mode")
    parser.add_argument("--refresh-interval", type=int, default=5, help="Live refresh interval in seconds (default: 5)")
    args = parser.parse_args()

    if not os.path.exists(args.db):
        print(f"Error: Database not found: {args.db}")
        return 1

    ViewerHandler.db_path = args.db

    server = HTTPServer(("0.0.0.0", args.port), ViewerHandler)
    url = f"http://127.0.0.1:{args.port}"
    if args.live:
        url += "?live=1"

    print(f"DragonSync Drone Viewer running at {url}")
    print(f"Database: {args.db}")
    if args.live:
        print(f"Live mode: enabled (refresh every {args.refresh_interval}s)")
    print("Press Ctrl+C to stop")

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down...")
        server.shutdown()
        return 0


if __name__ == "__main__":
    exit(main())
