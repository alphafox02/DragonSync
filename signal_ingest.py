#!/usr/bin/env python3
"""
Copyright 2025-2026 CEMAXECUTER LLC.

Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at

    http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the License for the specific language governing permissions and
limitations under the License.
"""

import datetime
import hashlib
import logging
import math
import threading
import time
import xml.etree.ElementTree as ET
from typing import Any, Callable, Dict, Optional, Tuple

import zmq

logger = logging.getLogger(__name__)


def _now_utc() -> datetime.datetime:
    return datetime.datetime.utcnow()


def _stable_offset(seed: str, radius_m: float) -> Tuple[float, float]:
    if radius_m <= 0:
        return 0.0, 0.0
    digest = hashlib.sha1(seed.encode("utf-8")).digest()
    angle = (digest[0] / 255.0) * (2.0 * math.pi)
    distance = (digest[1] / 255.0) * radius_m
    d_north = math.cos(angle) * distance
    d_east = math.sin(angle) * distance
    return d_north, d_east


def _offset_latlon(lat: float, lon: float, radius_m: float, seed: str) -> Tuple[float, float]:
    d_north, d_east = _stable_offset(seed, radius_m)
    meters_per_deg_lat = 111320.0
    lat_rad = math.radians(lat)
    meters_per_deg_lon = 111320.0 * max(math.cos(lat_rad), 1e-6)
    return lat + (d_north / meters_per_deg_lat), lon + (d_east / meters_per_deg_lon)


def _parse_fpv_alert(message: Any) -> Optional[Dict[str, Any]]:
    if not isinstance(message, list):
        return None

    data: Dict[str, Any] = {
        "signal_type": "fpv",
        "source": "unknown",
    }

    for item in message:
        if not isinstance(item, dict):
            continue
        if "Basic ID" in item:
            basic = item["Basic ID"]
            data["alert_id"] = basic.get("id")
            data["description"] = basic.get("description")
        if "Location/Vector Message" in item:
            loc = item["Location/Vector Message"]
            data["sensor_lat"] = loc.get("latitude")
            data["sensor_lon"] = loc.get("longitude")
            data["sensor_alt"] = loc.get("geodetic_altitude")
        if "Self-ID Message" in item:
            self_id = item["Self-ID Message"]
            data["self_id"] = self_id.get("text")
        if "Frequency Message" in item:
            freq = item["Frequency Message"]
            data["frequency_hz"] = freq.get("frequency")
        if "Signal Info" in item:
            sig = item["Signal Info"]
            data["source"] = sig.get("source", data.get("source"))
            data["center_hz"] = sig.get("center_hz")
            data["bandwidth_hz"] = sig.get("bandwidth_hz")
            data["pal_conf"] = sig.get("pal_conf")
            data["ntsc_conf"] = sig.get("ntsc_conf")

    if not data.get("center_hz") and data.get("frequency_hz"):
        data["center_hz"] = data.get("frequency_hz")

    if not data.get("center_hz"):
        return None

    return data


def _build_cot(
    alert: Dict[str, Any],
    lat: float,
    lon: float,
    alt: float,
    stale_s: float,
    radius_m: float,
    seen_by: Optional[str],
) -> bytes:
    now = _now_utc()
    t = now.strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    stale = (now + datetime.timedelta(seconds=stale_s)).strftime("%Y-%m-%dT%H:%M:%S.%fZ")

    uid = alert["uid"]
    callsign = alert.get("callsign") or "FPV Signal"

    remarks_parts = ["signal=fpv"]
    if alert.get("source") is not None:
        remarks_parts.append(f"source={alert.get('source')}")
    if alert.get("center_hz") is not None:
        remarks_parts.append(f"center_hz={alert.get('center_hz')}")
    if alert.get("bandwidth_hz") is not None:
        remarks_parts.append(f"bandwidth_hz={alert.get('bandwidth_hz')}")
    if alert.get("pal_conf") is not None:
        remarks_parts.append(f"pal={alert.get('pal_conf')}")
    if alert.get("ntsc_conf") is not None:
        remarks_parts.append(f"ntsc={alert.get('ntsc_conf')}")
    if seen_by:
        remarks_parts.append(f"SeenBy: {seen_by}")
    remarks = " ".join(str(p) for p in remarks_parts if p)

    event = ET.Element(
        "event",
        version="2.0",
        uid=uid,
        type="b-m-p-s-s",
        time=t,
        start=t,
        stale=stale,
        how="m-g",
    )
    ET.SubElement(
        event,
        "point",
        lat=str(lat),
        lon=str(lon),
        hae=str(float(alt or 0.0)),
        ce=str(float(radius_m)),
        le=str(999999.0),
    )
    detail = ET.SubElement(event, "detail")
    ET.SubElement(detail, "contact", callsign=str(callsign))
    ET.SubElement(detail, "remarks").text = remarks
    return ET.tostring(event, encoding="UTF-8", xml_declaration=True)


def start_signal_worker(
    *,
    zmq_host: str,
    zmq_port: int,
    cot_messenger: Any,
    signal_manager: Any,
    stale_s: float = 30.0,
    radius_m: float = 15.0,
    min_send_interval: float = 2.0,
    confirm_only: bool = True,
    seen_by_provider: Optional[Callable[[], Optional[str]]] = None,
    system_status_provider: Optional[Callable[[], Optional[Any]]] = None,
) -> Tuple[Optional[threading.Thread], Optional[threading.Event]]:
    stop_event = threading.Event()
    last_sent: Dict[str, float] = {}

    def _get_system_location() -> Optional[Tuple[float, float, float]]:
        if system_status_provider is None:
            return None
        try:
            status = system_status_provider() if callable(system_status_provider) else system_status_provider
        except Exception:
            return None
        if not status:
            return None
        try:
            return float(status.lat), float(status.lon), float(status.alt)
        except Exception:
            return None

    def worker():
        context = zmq.Context()
        socket = context.socket(zmq.SUB)
        socket.connect(f"tcp://{zmq_host}:{zmq_port}")
        socket.setsockopt_string(zmq.SUBSCRIBE, "")
        logger.info("FPV signal ingest connected to tcp://%s:%s", zmq_host, zmq_port)

        poller = zmq.Poller()
        poller.register(socket, zmq.POLLIN)

        while not stop_event.is_set():
            try:
                socks = dict(poller.poll(timeout=500))
            except zmq.error.ZMQError as e:
                if e.errno == getattr(zmq, "ETERM", None):
                    break
                logger.warning("FPV signal poll error: %s", e)
                time.sleep(0.5)
                continue

            if socket not in socks or socks[socket] != zmq.POLLIN:
                continue

            try:
                message = socket.recv_json()
            except Exception as e:
                logger.debug("FPV signal recv failed: %s", e)
                continue

            try:
                alert = _parse_fpv_alert(message)
                if not alert:
                    continue
                if confirm_only and alert.get("source") != "confirm":
                    continue

                center_hz = alert.get("center_hz")
                try:
                    center_mhz = int(round(float(center_hz) / 1e6))
                except (TypeError, ValueError):
                    center_mhz = None
                if center_mhz is not None:
                    uid = f"fpv-alert-{center_mhz}MHz"
                else:
                    uid = alert.get("alert_id") or "fpv-alert-unknown"
                source = alert.get("source") or "unknown"
                alert_id = alert.get("alert_id")
                now = time.time()
                last = last_sent.get(uid, 0.0)
                if now - last < min_send_interval:
                    continue
                last_sent[uid] = now

                sensor_lat = alert.get("sensor_lat")
                sensor_lon = alert.get("sensor_lon")
                sensor_alt = alert.get("sensor_alt", 0.0)
                if sensor_lat is None or sensor_lon is None:
                    system_loc = _get_system_location()
                    if system_loc:
                        sensor_lat, sensor_lon, sensor_alt = system_loc
                if sensor_lat is None or sensor_lon is None:
                    continue

                try:
                    base_lat = float(sensor_lat)
                    base_lon = float(sensor_lon)
                except (TypeError, ValueError):
                    continue

                offset_lat, offset_lon = _offset_latlon(
                    base_lat,
                    base_lon,
                    radius_m,
                    uid,
                )

                seen_by = seen_by_provider() if callable(seen_by_provider) else None
                callsign = f"FPV {source}".strip()

                signal = {
                    "uid": uid,
                    "signal_type": "fpv",
                    "source": source,
                    "alert_id": alert_id,
                    "callsign": callsign,
                    "description": alert.get("description"),
                    "self_id": alert.get("self_id"),
                    "center_hz": alert.get("center_hz"),
                    "bandwidth_hz": alert.get("bandwidth_hz"),
                    "pal_conf": alert.get("pal_conf"),
                    "ntsc_conf": alert.get("ntsc_conf"),
                    "sensor_lat": base_lat,
                    "sensor_lon": base_lon,
                    "sensor_alt": float(sensor_alt or 0.0),
                    "lat": float(offset_lat),
                    "lon": float(offset_lon),
                    "alt": float(sensor_alt or 0.0),
                    "radius_m": float(radius_m),
                    "seen_by": seen_by,
                }

                if signal_manager is not None:
                    try:
                        signal_manager.add_signal(signal)
                    except Exception:
                        pass

                try:
                    cot = _build_cot(
                        signal,
                        float(offset_lat),
                        float(offset_lon),
                        float(sensor_alt or 0.0),
                        stale_s,
                        radius_m,
                        seen_by,
                    )
                    cot_messenger.send_cot(cot)
                except Exception as e:
                    logger.debug("FPV signal CoT send failed: %s", e)
            except Exception as e:
                logger.warning("FPV signal ingest error; skipping message: %s", e)

        socket.close(0)
        context.term()

    thread = threading.Thread(target=worker, name="fpv-signal-worker", daemon=True)
    thread.start()
    return thread, stop_event
