#!/usr/bin/env python3
import argparse
import logging
import time
import zmq
import csv
import os
import sys
import threading
from queue import Queue
from pathlib import Path
from datetime import datetime
from math import radians, sin, cos, asin, sqrt

def haversine_m(lat1, lon1, lat2, lon2):
    try:
        lat1, lon1, lat2, lon2 = float(lat1), float(lon1), float(lat2), float(lon2)
    except (TypeError, ValueError):
        return 0.0
    R = 6371000.0
    dlat = radians(lat2 - lat1)
    dlon = radians(lon2 - lon1)
    a = sin(dlat/2)**2 + cos(radians(lat1))*cos(radians(lat2))*sin(dlon/2)**2
    return 2 * R * asin(sqrt(a))

def get_float(value, default=0.0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default

def parse_drone_message(message, logger):
    """
    Tolerates old/new DragonSync shapes. Returns a dict with base + extended fields.
    """
    def merge_into(dst, src):
        for k, v in src.items():
            if v is None:
                continue
            dst[k] = v

    def parse_one(obj):
        if not isinstance(obj, dict):
            return {}
        out = {}

        aux = obj.get("AUX_ADV_IND")
        if isinstance(aux, dict) and "rssi" in aux:
            out["rssi"] = aux["rssi"]
        aext = obj.get("aext")
        if isinstance(aext, dict):
            adv = aext.get("AdvA")
            if isinstance(adv, str):
                out["mac"] = adv.split()[0]

        bid = obj.get("Basic ID")
        if isinstance(bid, dict):
            id_type = bid.get("id_type")
            out["mac"]  = bid.get("MAC", out.get("mac", ""))
            out["rssi"] = bid.get("RSSI", out.get("rssi", 0.0))
            if id_type in ("Serial Number (ANSI/CTA-2063-A)", "CAA Assigned Registration ID"):
                out.setdefault("id", bid.get("id", "unknown"))
            out["id_type"] = id_type

        lvm = obj.get("Location/Vector Message")
        if isinstance(lvm, dict):
            out["lat"]    = get_float(lvm.get("latitude", 0.0))
            out["lon"]    = get_float(lvm.get("longitude", 0.0))
            out["speed"]  = get_float(lvm.get("speed", 0.0))
            out["vspeed"] = get_float(lvm.get("vert_speed", 0.0))
            out["alt"]    = get_float(lvm.get("geodetic_altitude", 0.0))
            out["height"] = get_float(lvm.get("height_agl", 0.0))
            out["direction"] = get_float(lvm.get("direction"), None)
            out["pressure_altitude"] = get_float(lvm.get("pressure_altitude"), None)
            out["vertical_accuracy"]   = lvm.get("vertical_accuracy")
            out["horizontal_accuracy"] = lvm.get("horizontal_accuracy")
            out["baro_accuracy"]       = lvm.get("baro_accuracy")
            out["speed_accuracy"]      = lvm.get("speed_accuracy")
            out["height_type"]         = lvm.get("height_type")
            out["timestamp"]           = lvm.get("timestamp")
            out["timestamp_accuracy"]  = lvm.get("timestamp_accuracy")
            out["ew_dir"]              = lvm.get("ew_dir")
            out["speed_multiplier"]    = lvm.get("speed_multiplier")

        sid = obj.get("Self-ID Message")
        if isinstance(sid, dict):
            out["description"] = sid.get("text", "")

        sysm = obj.get("System Message")
        if isinstance(sysm, dict):
            out["pilot_lat"] = get_float(sysm.get("latitude", 0.0))
            out["pilot_lon"] = get_float(sysm.get("longitude", 0.0))
            out["home_lat"]  = get_float(sysm.get("home_lat", 0.0))
            out["home_lon"]  = get_float(sysm.get("home_lon", 0.0))
            out["operator_id_type"] = sysm.get("operator_id_type")
            out["operator_id"]      = sysm.get("operator_id")
            out["op_status"]        = sysm.get("op_status")
            out["ua_type"]          = sysm.get("ua_type")
            out["ua_type_name"]     = sysm.get("ua_type_name")

        # flat extras sometimes present
        out["freq"]   = obj.get("freq", out.get("freq"))
        out["caa"]    = obj.get("caa",  out.get("caa"))
        out["index"]  = obj.get("index", out.get("index"))
        out["runtime"]= obj.get("runtime", out.get("runtime"))

        return out

    drone_info = {}
    if isinstance(message, list):
        for item in message:
            merge_into(drone_info, parse_one(item))
    elif isinstance(message, dict):
        merge_into(drone_info, parse_one(message))
    else:
        logger.error("Unexpected message format; expected dict or list.")
        return None

    if 'id' not in drone_info or not drone_info['id']:
        logger.debug("No drone ID found; skipping.")
        return None
    if not str(drone_info['id']).startswith('drone-'):
        drone_info['id'] = f"drone-{drone_info['id']}"

    # base defaults
    drone_info.setdefault('lat', 0.0)
    drone_info.setdefault('lon', 0.0)
    drone_info.setdefault('alt', 0.0)
    drone_info.setdefault('speed', 0.0)
    drone_info.setdefault('rssi', 0.0)
    drone_info.setdefault('description', "")
    drone_info.setdefault('pilot_lat', 0.0)
    drone_info.setdefault('pilot_lon', 0.0)
    drone_info.setdefault('mac', "")

    # extended defaults
    for k in [
        "home_lat","home_lon","ua_type","ua_type_name","operator_id_type","operator_id","op_status",
        "height","height_type","direction","vspeed","ew_dir","speed_multiplier","pressure_altitude",
        "vertical_accuracy","horizontal_accuracy","baro_accuracy","speed_accuracy",
        "timestamp","timestamp_accuracy","index","runtime","caa","freq"
    ]:
        drone_info.setdefault(k, "")

    return drone_info

def should_log(prev, cur, th):
    if prev is None:
        return True
    dist = haversine_m(prev["lat"], prev["lon"], cur["lat"], cur["lon"])
    if th["min_move_m"] and dist >= th["min_move_m"]:
        return True
    if th["min_alt_change"] and abs(cur["alt"] - prev["alt"]) >= th["min_alt_change"]:
        return True
    if th["min_speed_change"] and abs(cur["speed"] - prev["speed"]) >= th["min_speed_change"]:
        return True
    if th["min_log_interval"] and (cur["t"] - prev["t"]) >= th["min_log_interval"]:
        return True
    return False

def main():
    parser = argparse.ArgumentParser(description="ZMQ logger (rate-limited) with home/metadata columns.")
    parser.add_argument("--zmq-host", default="127.0.0.1")
    parser.add_argument("--zmq-port", type=int, default=4224)
    parser.add_argument("--zmq-status-port", type=int, default=None, help="ZMQ port for system status (default: disabled)")
    parser.add_argument("--include-system-location", action="store_true", help="Include system location in CSV (requires --zmq-status-port)")
    parser.add_argument("--output-csv", default=None, help="Output CSV file path. If not specified, creates timestamped file.")
    parser.add_argument("--flush-interval", type=float, default=5.0, help="Flush CSV buffer interval (seconds)")
    parser.add_argument("--rcv-hwm", type=int, default=0, help="ZMQ receive high water mark (0=unlimited)")
    parser.add_argument("--conflate", action="store_true", help="Keep only latest message (drop backlog)")

    # Per-drone throttling
    parser.add_argument("--min-log-interval", type=float, default=30.0, help="Minimum time between logs for same drone (seconds)")
    parser.add_argument("--min-move-m", type=float, default=25.0, help="Minimum movement to trigger log (meters)")
    parser.add_argument("--min-alt-change", type=float, default=5.0, help="Minimum altitude change to trigger log (meters)")
    parser.add_argument("--min-speed-change", type=float, default=1.0, help="Minimum speed change to trigger log (m/s)")

    # FAA RID lookup (local DB sync, optional API async)
    parser.add_argument("--rid-enabled", action="store_true", help="Enrich rows with FAA RID lookup (local DB).")
    parser.add_argument("--rid-api", action="store_true", help="Enable FAA API fallback (async; requires --rid-enabled).")

    parser.add_argument("--debug", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(level=logging.DEBUG if args.debug else logging.INFO,
                        format="%(asctime)s - %(levelname)s - %(message)s")
    logger = logging.getLogger(__name__)

    # Generate timestamped filename if --output-csv not specified
    if args.output_csv is None:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_csv = f"drone_log_{timestamp}.csv"
    else:
        output_csv = args.output_csv

    logger.info(f"Output CSV: {output_csv}")
    logger.info(f"Connecting to ZMQ at tcp://{args.zmq_host}:{args.zmq_port}")

    # FAA RID lookup setup (optional)
    FAA_LOOKUP_AVAILABLE = False
    lookup_serial = None
    if args.rid_enabled:
        try:
            faa_path = Path(__file__).resolve().parent.parent / "faa-rid-lookup"
            if faa_path.exists():
                sys.path.append(str(faa_path))
            from drone_serial_lookup import lookup_serial as _lookup_serial  # type: ignore
            lookup_serial = _lookup_serial
            FAA_LOOKUP_AVAILABLE = True
        except Exception as e:
            logger.warning(f"RID lookup disabled (module unavailable): {e}")
            FAA_LOOKUP_AVAILABLE = False

    rid_lookup_enabled = FAA_LOOKUP_AVAILABLE and args.rid_enabled
    rid_api_enabled = rid_lookup_enabled and args.rid_api
    rid_cache = {}
    rid_pending = set()
    rid_failure_logged = False
    rid_queue: Queue = Queue()

    def rid_worker():
        nonlocal rid_lookup_enabled, rid_failure_logged
        while True:
            item = rid_queue.get()
            if item is None:
                break
            serial = item
            try:
                res = lookup_serial(serial, use_api_fallback=True, add_to_db=True)  # type: ignore
                rid_cache[serial] = res
            except FileNotFoundError as e:
                if not rid_failure_logged:
                    logger.warning(f"RID lookup disabled (database missing?): {e}")
                    rid_failure_logged = True
                rid_lookup_enabled = False
            except Exception as e:
                if not rid_failure_logged:
                    logger.warning(f"RID lookup failed; disabling: {e}")
                    rid_failure_logged = True
                rid_lookup_enabled = False
            finally:
                rid_pending.discard(serial)

    rid_thread = None
    if rid_api_enabled:
        rid_thread = threading.Thread(target=rid_worker, daemon=True, name="rid_lookup_worker")
        rid_thread.start()

    context = zmq.Context()
    socket = context.socket(zmq.SUB)
    if args.rcv_hwm is not None:
        socket.setsockopt(zmq.RCVHWM, args.rcv_hwm)
    if args.conflate:
        socket.setsockopt(zmq.CONFLATE, 1)
    socket.connect(f"tcp://{args.zmq_host}:{args.zmq_port}")
    socket.setsockopt_string(zmq.SUBSCRIBE, "")

    # Optional status socket for system location
    status_socket = None
    if args.include_system_location and args.zmq_status_port:
        status_socket = context.socket(zmq.SUB)
        status_socket.connect(f"tcp://{args.zmq_host}:{args.zmq_status_port}")
        status_socket.setsockopt_string(zmq.SUBSCRIBE, "")
        logger.info(f"Connected to system status ZMQ at tcp://{args.zmq_host}:{args.zmq_status_port}")
    elif args.include_system_location:
        logger.warning("--include-system-location set but no --zmq-status-port provided. System location will be 0.0")

    poller = zmq.Poller()
    poller.register(socket, zmq.POLLIN)
    if status_socket:
        poller.register(status_socket, zmq.POLLIN)

    # Build headers based on whether system location is included
    headers = [
        # base
        "timestamp","drone_id","lat","lon","alt","speed","rssi","mac","description","pilot_lat","pilot_lon",
        # extended (always included now)
        "home_lat","home_lon","ua_type","ua_type_name","operator_id_type","operator_id","op_status",
        "height","height_type","direction","vspeed","ew_dir","speed_multiplier","pressure_altitude",
        "vertical_accuracy","horizontal_accuracy","baro_accuracy","speed_accuracy",
        "timestamp_src","timestamp_accuracy","index","runtime","caa","freq",
        # FAA RID enrichment (optional; blanks if not available)
        "rid_make","rid_model","rid_status","rid_tracking","rid_source"
    ]
    if args.include_system_location:
        headers.extend(["system_id","system_lat","system_lon","system_alt"])

    # Check if file exists and has content to determine if we need to write headers
    file_exists = os.path.exists(output_csv)
    file_is_empty = not file_exists or os.path.getsize(output_csv) == 0
    csv_file = open(output_csv, 'a', newline='')
    csv_writer = csv.writer(csv_file)
    if file_is_empty:
        logger.info("Writing CSV headers to new file")
        csv_writer.writerow(headers)
        csv_file.flush()  # Ensure header is written immediately

    buf = []
    last_flush = time.time()
    last_logged = {}  # drone_id -> snapshot

    # Track latest system location and ID
    system_location = {"id": "", "lat": 0.0, "lon": 0.0, "alt": 0.0}

    th = {
        "min_log_interval": max(0.0, args.min_log_interval),
        "min_move_m": max(0.0, args.min_move_m),
        "min_alt_change": max(0.0, args.min_alt_change),
        "min_speed_change": max(0.0, args.min_speed_change),
    }

    try:
        while True:
            socks = dict(poller.poll(timeout=1000))

            # Handle system status messages
            if status_socket and status_socket in socks and socks[status_socket] == zmq.POLLIN:
                try:
                    status_msg = status_socket.recv_json()
                    # Extract GPS data and serial number from wardragon_monitor format
                    if "serial_number" in status_msg:
                        system_location["id"] = status_msg.get("serial_number", "")
                    if "gps_data" in status_msg:
                        gps = status_msg["gps_data"]
                        system_location["lat"] = gps.get("latitude", 0.0) if gps.get("latitude") != "N/A" else 0.0
                        system_location["lon"] = gps.get("longitude", 0.0) if gps.get("longitude") != "N/A" else 0.0
                        system_location["alt"] = gps.get("altitude", 0.0) if gps.get("altitude") != "N/A" else 0.0
                        logger.debug(f"Updated system location: {system_location}")
                except Exception as e:
                    logger.warning(f"Status recv_json failed: {e}")

            # Handle drone telemetry messages
            if socket in socks and socks[socket] == zmq.POLLIN:
                try:
                    raw = socket.recv_json()
                except Exception as e:
                    logger.warning(f"recv_json failed: {e}")
                    continue

                parsed = parse_drone_message(raw, logger)
                if not parsed:
                    continue

                drone_id = parsed["id"]
                serial_number = drone_id[len("drone-"):] if drone_id.startswith("drone-") else drone_id
                now_ts = time.time()
                cur = {"t": now_ts, "lat": parsed["lat"], "lon": parsed["lon"], "alt": parsed["alt"], "speed": parsed["speed"]}
                prev = last_logged.get(drone_id)

                # FAA RID lookup (local sync; optional async API)
                rid_info = {}
                if rid_lookup_enabled and serial_number:
                    if serial_number in rid_cache:
                        rid_info = rid_cache[serial_number]
                    else:
                        try:
                            res = lookup_serial(serial_number, use_api_fallback=False)  # type: ignore
                            rid_cache[serial_number] = res
                            rid_info = res
                        except FileNotFoundError as e:
                            if not rid_failure_logged:
                                logger.warning(f"RID lookup disabled (database missing?): {e}")
                                rid_failure_logged = True
                            rid_lookup_enabled = False
                        except Exception as e:
                            if not rid_failure_logged:
                                logger.warning(f"RID lookup failed; disabling: {e}")
                                rid_failure_logged = True
                            rid_lookup_enabled = False

                        if rid_api_enabled and rid_lookup_enabled and not rid_info.get("found") and serial_number not in rid_pending:
                            rid_pending.add(serial_number)
                            try:
                                rid_queue.put_nowait(serial_number)
                            except Exception as qe:
                                rid_pending.discard(serial_number)
                                logger.debug(f"Failed to enqueue RID lookup: {qe}")

                if should_log(prev, cur, th):
                    row = [
                        datetime.utcnow().isoformat(),
                        drone_id,
                        parsed["lat"], parsed["lon"], parsed["alt"], parsed["speed"],
                        parsed["rssi"], parsed["mac"], parsed["description"],
                        parsed["pilot_lat"], parsed["pilot_lon"],
                        parsed["home_lat"], parsed["home_lon"], parsed["ua_type"], parsed["ua_type_name"],
                        parsed["operator_id_type"], parsed["operator_id"], parsed["op_status"],
                        parsed["height"], parsed["height_type"], parsed["direction"], parsed["vspeed"],
                        parsed["ew_dir"], parsed["speed_multiplier"], parsed["pressure_altitude"],
                        parsed["vertical_accuracy"], parsed["horizontal_accuracy"], parsed["baro_accuracy"],
                        parsed["speed_accuracy"],
                        parsed["timestamp"], parsed["timestamp_accuracy"], parsed["index"], parsed["runtime"],
                        parsed["caa"], parsed["freq"],
                        # FAA RID enrichment (blanks when not present)
                        rid_info.get("make"), rid_info.get("model"), rid_info.get("status"),
                        rid_info.get("rid_tracking"), rid_info.get("source")
                    ]
                    if args.include_system_location:
                        row.extend([system_location["id"], system_location["lat"], system_location["lon"], system_location["alt"]])
                    buf.append(row)
                    last_logged[drone_id] = cur
                    logger.debug(f"Queued log for {drone_id}")

            now = time.time()
            if (now - last_flush) >= args.flush_interval and buf:
                logger.debug(f"Flushing {len(buf)} rows")
                csv_writer.writerows(buf)
                csv_file.flush()
                buf.clear()
                last_flush = now

    except KeyboardInterrupt:
        logger.info("Interrupted by user.")
    finally:
        if buf:
            csv_writer.writerows(buf)
        csv_file.flush()
        csv_file.close()
        # Stop RID worker
        try:
            if rid_api_enabled and rid_thread and rid_thread.is_alive():
                rid_queue.put_nowait(None)
        except Exception:
            pass
        try:
            socket.close(0)
            if status_socket:
                status_socket.close(0)
        finally:
            context.term()

if __name__ == "__main__":
    main()
    
