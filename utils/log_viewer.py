#!/usr/bin/env python3
"""
Offline viewer for DragonSync ZMQ logs stored in SQLite.

Usage:
  python utils/log_viewer.py --db path/to/drone_log.sqlite --port 5001

Features:
- Filters (time range, drone id, RID make/model/source)
  - Limit results (default 500)
  - Map view (canvas-based, offline-safe) + table view
  - Uses the SQLite log produced by utils/zmq_logger_for_kml.py (--sqlite)
"""

import argparse
import json
import os
import sqlite3
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs


INDEX_HTML = """<!doctype html>
<html>
<head>
  <meta charset="utf-8"/>
  <title>DragonSync Log Viewer</title>
  <style>
    :root { color-scheme: light dark; }
    body { margin:0; font-family: Arial, sans-serif; background:#0e1117; color:#e6e8ed; }
    header { padding:12px 16px; background:#111826; border-bottom:1px solid #1f2937; }
    h1 { margin:0; font-size:18px; letter-spacing:0.5px; }
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
    #map { flex:1 1 auto; position:relative; background:#0b1220; border-bottom:1px solid #1f2937; }
    #map canvas { width:100%; height:100%; display:block; }
    #legend { position:absolute; top:10px; right:10px; background:#111826cc; padding:8px 10px; border-radius:8px; font-size:12px; }
    #table { flex:0 0 320px; overflow:auto; border-top:1px solid #1f2937; }
    table { width:100%; border-collapse:collapse; font-size:12px; }
    th, td { padding:6px 8px; border-bottom:1px solid #1f2937; }
    th { text-align:left; position:sticky; top:0; background:#0f172a; }
    tr:hover { background:#111827; }
    .badge { padding:2px 6px; border-radius:4px; font-size:11px; display:inline-block; }
    .status-accepted { background:#065f46; color:#d1fae5; }
    .status-pending { background:#92400e; color:#fef3c7; }
    .status-other { background:#374151; color:#e5e7eb; }
    .pill { padding:2px 6px; border-radius:4px; background:#1f2937; color:#e5e7eb; font-size:11px; }
    .controls { display:grid; grid-template-columns:1fr 1fr; gap:8px; }
    .controls-1 { display:grid; grid-template-columns:1fr; gap:8px; }
    .flex { display:flex; gap:8px; align-items:center; }
    .muted { color:#9ca3af; font-size:12px; }
    @media (max-width: 960px) {
      .layout { grid-template-columns: 1fr; height:auto; }
      #table { height:320px; }
    }
  </style>
</head>
<body>
  <header>
    <h1>DragonSync Log Viewer</h1>
    <div class="muted">Filter and explore RID-enriched detections (offline-safe).</div>
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
          <label>Start (ISO) <input id="f-start" placeholder="2025-02-13T00:00:00Z" /></label>
          <label>End (ISO) <input id="f-end" placeholder="2025-02-13T23:59:59Z" /></label>
        </div>
        <div class="flex" style="margin-top:8px;">
          <button id="btn-apply">Apply Filters</button>
          <button class="secondary" id="btn-clear">Clear</button>
        </div>
        <div class="muted" id="summary"></div>
      </div>
    </aside>
    <section class="content">
      <div id="map"><canvas id="mapCanvas"></canvas><div id="legend"></div></div>
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
    const canvas = document.getElementById('mapCanvas');
    const ctx = canvas.getContext('2d');
    const legendEl = document.getElementById('legend');
    let records = [];

    function fitCanvas() {
      const rect = canvas.parentElement.getBoundingClientRect();
      const dpr = window.devicePixelRatio || 1;
      canvas.width = rect.width * dpr;
      canvas.height = rect.height * dpr;
      canvas.style.width = rect.width + 'px';
      canvas.style.height = rect.height + 'px';
      ctx.scale(dpr, dpr);
    }

    window.addEventListener('resize', () => {
      ctx.setTransform(1,0,0,1,0,0);
      fitCanvas();
      drawMap();
    });

    function mercator(lat, lon) {
      const rad = Math.PI / 180;
      const x = lon * rad;
      const y = Math.log(Math.tan(Math.PI/4 + lat*rad/2));
      return {x, y};
    }

    function drawMap() {
      if (!records.length) {
        ctx.clearRect(0,0,canvas.width, canvas.height);
        ctx.fillStyle = '#1f2937';
        ctx.fillRect(0,0,canvas.width, canvas.height);
        ctx.fillStyle = '#9ca3af';
        ctx.fillText('No data', 12, 18);
        legendEl.innerHTML = '';
        return;
      }

      const pts = records.map(r => {
        const p = mercator(r.lat, r.lon);
        return {...p, source:r.rid_source, rid: r.rid_make || ''};
      });
      let minX = Math.min(...pts.map(p=>p.x));
      let maxX = Math.max(...pts.map(p=>p.x));
      let minY = Math.min(...pts.map(p=>p.y));
      let maxY = Math.max(...pts.map(p=>p.y));
      const pad = 0.05;
      if (maxX === minX) { maxX += pad; minX -= pad; }
      if (maxY === minY) { maxY += pad; minY -= pad; }

      const w = canvas.width / (window.devicePixelRatio||1);
      const h = canvas.height / (window.devicePixelRatio||1);

      ctx.clearRect(0,0,canvas.width, canvas.height);
      ctx.fillStyle = '#0b1220';
      ctx.fillRect(0,0,canvas.width, canvas.height);

      ctx.strokeStyle = '#1f2937';
      for (let i=0;i<5;i++){
        const x = w * i/4;
        const y = h * i/4;
        ctx.beginPath(); ctx.moveTo(x,0); ctx.lineTo(x,h); ctx.stroke();
        ctx.beginPath(); ctx.moveTo(0,y); ctx.lineTo(w,y); ctx.stroke();
      }

      function colorFor(source){
        if(!source) return '#9ca3af';
        const s=source.toLowerCase();
        if (s.includes('local')) return '#10b981';
        if (s.includes('api')) return '#f59e0b';
        return '#93c5fd';
      }

      ctx.fillStyle = '#2563eb';
      pts.forEach(p=>{
        const nx = (p.x - minX)/(maxX-minX);
        const ny = (p.y - minY)/(maxY-minY);
        const x = nx * w;
        const y = h - ny * h;
        ctx.beginPath();
        ctx.fillStyle = colorFor(p.source);
        ctx.arc(x,y,4,0,Math.PI*2);
        ctx.fill();
      });

      legendEl.innerHTML = '<div><span class="badge status-accepted">local</span> <span class="badge status-pending">api</span> <span class="badge status-other">other</span></div>';
    }

    function renderTable() {
      rowsEl.innerHTML = '';
      const frag = document.createDocumentFragment();
      records.forEach(r=>{
        const tr = document.createElement('tr');
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
        frag.appendChild(tr);
      });
      rowsEl.appendChild(frag);
      summaryEl.textContent = `${records.length} rows`;
    }

    async function loadRecords() {
      const params = new URLSearchParams();
      const limit = document.getElementById('f-limit').value || '500';
      params.set('limit', limit);
      ['id','make','model','source','start','end'].forEach(k=>{
        const v = document.getElementById('f-'+k).value.trim();
        if (v) params.set(k, v);
      });
      const res = await fetch('/api/records?' + params.toString());
      if (!res.ok) {
        alert('Failed to fetch records');
        return;
      }
      records = await res.json();
      ctx.setTransform(1,0,0,1,0,0);
      fitCanvas();
      drawMap();
      renderTable();
    }

    document.getElementById('btn-apply').addEventListener('click', loadRecords);
    document.getElementById('btn-clear').addEventListener('click', ()=>{
      ['id','make','model','source','start','end'].forEach(k=>document.getElementById('f-'+k).value='');
      document.getElementById('f-limit').value='500';
      loadRecords();
    });

    fitCanvas();
    loadRecords();
  </script>
</body>
</html>
"""


def parse_filters(query):
    filters = {}
    for key in ["id", "make", "model", "source", "start", "end", "limit"]:
        if key in query and query[key]:
            filters[key] = query[key][0]
    return filters


def fetch_records(conn, filters, default_limit=500):
    limit = int(filters.get("limit", default_limit) or default_limit)
    limit = max(1, min(limit, 5000))
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
        for key in ["lat", "lon", "alt", "speed"]:
            try:
                obj[key] = float(obj.get(key) or 0.0)
            except Exception:
                obj[key] = 0.0
        out.append(obj)
    return out


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == "/":
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(INDEX_HTML.encode("utf-8"))
            return
        elif parsed.path == "/api/records":
            query = parse_qs(parsed.query)
            filters = parse_filters(query)
            try:
                records = fetch_records(self.server.conn, filters)
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps(records).encode("utf-8"))
            except Exception as e:
                self.send_response(500)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"error": str(e)}).encode("utf-8"))
            return
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, format, *args):
        return


def main():
    parser = argparse.ArgumentParser(description="Serve a simple offline viewer for SQLite logs.")
    parser.add_argument("--db", required=True, help="Path to SQLite log created by zmq_logger_for_kml.py")
    parser.add_argument("--host", default="127.0.0.1", help="Host/interface to bind (default: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=5001, help="Port to serve on (default: 5001)")
    args = parser.parse_args()

    if not os.path.exists(args.db):
        raise SystemExit(f"SQLite file not found: {args.db}")

    conn = sqlite3.connect(args.db, check_same_thread=False)

    class LogHTTPServer(HTTPServer):
        def __init__(self, server_address, RequestHandlerClass):
            super().__init__(server_address, RequestHandlerClass)
            self.conn = conn

    print(f"Serving log viewer at http://{args.host}:{args.port} (db: {args.db})")
    httpd = LogHTTPServer((args.host, args.port), Handler)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        conn.close()


if __name__ == "__main__":
    main()
