#!/usr/bin/env python3
"""
Copyright 2025 cemaxecuter

Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at

    http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the License for the specific language governing permissions and
limitations under the License.

Optional Kismet ingest.

Polls the Kismet REST API for Wi-Fi / Bluetooth devices and emits CoT messages
via the provided CotMessenger. Designed to be lightweight and self-contained;
if the kismet_rest dependency is missing or the API is unreachable, it will log
and keep going without impacting the rest of the app.
"""

import datetime
import logging
import threading
import time
import xml.etree.ElementTree as ET
from typing import Any, Dict, Optional, Tuple

try:
    import kismet_rest  # type: ignore
except Exception:  # pragma: no cover - optional dependency
    kismet_rest = None  # type: ignore

logger = logging.getLogger(__name__)

# Default PHYs of interest
DEFAULT_PHYS = {"IEEE802.11", "BLUETOOTH"}


def _pick(dicts, *keys):
    """Return the first non-None value for any of the candidate keys."""
    for d in dicts:
        if not isinstance(d, dict):
            continue
        for k in keys:
            if k in d and d[k] is not None:
                return d[k]
    return None


def _extract_location(dev: Dict[str, Any]) -> Optional[Tuple[float, float, float]]:
    """Try to pull lat/lon/alt from common Kismet location fields."""
    loc = dev.get("kismet.common.location") or {}
    base = dev.get("kismet.device.base", {}) or {}

    def _from_point(point, alt=None, swap=False):
        """Convert a Kismet geopoint (lon, lat[, alt]) to lat/lon/alt."""
        if not isinstance(point, (list, tuple)) or len(point) < 2:
            return None
        try:
            lon = float(point[0])
            lat = float(point[1])
            if swap:
                lat, lon = lon, lat
            alt_val = alt if alt is not None else (float(point[2]) if len(point) >= 3 else 0.0)
            return float(lat), float(lon), float(alt_val)
        except Exception:
            return None

    def _parse_candidate(val):
        """Handle the variety of location shapes Kismet emits."""
        if isinstance(val, dict):
            if "kismet.common.location.geopoint" in val:
                return _from_point(val.get("kismet.common.location.geopoint"), val.get("kismet.common.location.alt"))
            for key in (
                "kismet.common.location.last_loc",
                "kismet.common.location.avg_loc",
                "kismet.common.location.last",
                "kismet.common.location.avg_loc",
                "kismet.common.location.min_loc",
                "kismet.common.location.max_loc",
            ):
                if key in val:
                    res = _parse_candidate(val.get(key))
                    if res:
                        return res
            return None
        if isinstance(val, (list, tuple)) and len(val) >= 2:
            return _from_point(val)
        return None

    candidates = [
        loc,
        loc.get("kismet.common.location.last_loc"),
        loc.get("kismet.common.location.avg_loc"),
        dev.get("kismet.common.location.last_loc"),
        dev.get("kismet.common.location.avg_loc"),
        dev.get("kismet.common.location.last"),
        dev.get("kismet.common.location.avg_loc"),
        dev.get("kismet.device.base.location"),
        base.get("kismet.device.base.location"),
        base.get("kismet.common.location"),
        base.get("kismet.common.location.last_loc"),
        base.get("kismet.common.location.avg_loc"),
        base.get("kismet.common.location.last"),
    ]

    # Dot11 devices sometimes stash location under the last beaconed SSID record
    last_beacon = dev.get("dot11.device.last_beaconed_ssid_record") or {}
    candidates.append(last_beacon.get("dot11.advertisedssid.location"))
    # Or in the advertised_ssid_map list
    advertised_list = dev.get("dot11.device.advertised_ssid_map")
    if isinstance(advertised_list, list):
        for ssid in advertised_list:
            if isinstance(ssid, dict) and ssid.get("dot11.advertisedssid.location"):
                candidates.append(ssid.get("dot11.advertisedssid.location"))

    for c in candidates:
        res = _parse_candidate(c)
        if res:
            return res
    return None


def _normalize_device(dev: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """
    Extract the small subset we need from a Kismet device dict.
    Returns None if we can't get lat/lon.
    """
    base = dev.get("kismet.device.base", {}) or {}
    dicts = [base, dev]

    mac = _pick(dicts, "macaddr", "kismet.device.base.macaddr")
    phy = _pick(dicts, "phyname", "kismet.device.base.phyname")
    if not phy:
        # Fallback based on device family
        if dev.get("dot11.device") is not None:
            phy = "IEEE802.11"
        elif dev.get("bluetooth.device") is not None:
            phy = "BLUETOOTH"
    name = _pick(dicts, "name", "commonname", "kismet.device.base.name", "kismet.device.base.commonname")
    manuf = _pick(dicts, "manuf", "kismet.device.base.manuf")
    last_time = _pick(dicts, "last_time", "kismet.device.base.last_time") or 0

    channel = _pick(dicts, "channel", "kismet.device.base.channel")
    freq = _pick(dicts, "frequency", "kismet.device.base.frequency")

    sig = _pick(dicts, "last_signal", "signal", "kismet.device.base.signal.last_signal")
    if isinstance(sig, dict):  # some signal fields are dicts with last_signal
        sig = sig.get("last_signal") or sig.get("last_signal_dbm")

    loc = _extract_location(dev)
    if not loc:
        return None
    lat, lon, alt = loc

    uid_base = mac or _pick(dicts, "key", "kismet.device.base.key") or "unknown"
    uid_prefix = "kismet-wifi" if phy == "IEEE802.11" else "kismet-bt"
    uid = f"{uid_prefix}-{uid_base}"

    return {
        "uid": uid,
        "phy": phy or "unknown",
        "mac": mac,
        "name": name,
        "manuf": manuf,
        "lat": lat,
        "lon": lon,
        "alt": alt,
        "channel": channel,
        "freq": freq,
        "signal": sig,
        "last_time": float(last_time) if last_time else 0.0,
    }


def _device_to_cot(d: Dict[str, Any], stale_s: float = 120.0) -> bytes:
    """Build a minimal CoT event for a Kismet device."""
    now = datetime.datetime.utcnow()
    t = now.strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    stale = (now + datetime.timedelta(seconds=stale_s)).strftime("%Y-%m-%dT%H:%M:%S.%fZ")

    callsign = d.get("name") or d.get("manuf") or d.get("mac") or d["uid"]
    remarks_parts = [
        f"phy={d.get('phy')}",
        f"mac={d.get('mac')}" if d.get("mac") else None,
        f"chan={d.get('channel')}" if d.get("channel") else None,
        f"freq={d.get('freq')}" if d.get("freq") else None,
        f"rssi={d.get('signal')}" if d.get("signal") is not None else None,
        f"manuf={d.get('manuf')}" if d.get("manuf") else None,
        "src=kismet",
    ]
    remarks = " ".join(p for p in remarks_parts if p)

    event = ET.Element(
        "event",
        version="2.0",
        uid=d["uid"],
        type="b-m-p-s-m",
        time=t,
        start=t,
        stale=stale,
        how="m-g",
    )
    ET.SubElement(
        event,
        "point",
        lat=str(d["lat"]),
        lon=str(d["lon"]),
        hae=str(float(d.get("alt", 0.0) or 0.0)),
        ce=str(35.0),
        le=str(999999.0),
    )
    detail = ET.SubElement(event, "detail")
    ET.SubElement(detail, "contact", callsign=str(callsign))
    ET.SubElement(detail, "remarks").text = remarks
    return ET.tostring(event, encoding="UTF-8", xml_declaration=True)


def start_kismet_worker(
    *,
    host: str,
    apikey: Optional[str],
    cot_messenger: Any,
    phys: Optional[set] = None,
    poll_interval: float = 5.0,
    min_send_interval: float = 5.0,
) -> Tuple[Optional[threading.Thread], Optional[threading.Event]]:
    """
    Start a background polling loop for Kismet devices.

    Returns (thread, stop_event). If kismet_rest is missing or setup fails,
    returns (None, None) after logging a warning.
    """
    if kismet_rest is None:
        logger.warning("Kismet enabled but python-kismet-rest not installed; skipping Kismet ingest.")
        return None, None

    stop_event = threading.Event()
    allowed_phys = phys or DEFAULT_PHYS
    last_sent: Dict[str, float] = {}
    logged_sample = False

    def worker():
        nonlocal allowed_phys, logged_sample
        last_ts = 0
        devices = None
        while not stop_event.is_set():
            polled = sent = skipped_no_loc = skipped_phy = 0
            try:
                if devices is None:
                    devices = kismet_rest.Devices(host_uri=host, apikey=apikey)
                    logger.info("Kismet ingest connected to %s", host)
            except Exception as e:
                logger.warning("Kismet ingest setup failed (%s); retrying in 5s", e)
                devices = None
                time.sleep(5)
                continue

            try:
                for dev in devices.all(ts=last_ts):
                    if stop_event.is_set():
                        break
                    polled += 1
                    norm = _normalize_device(dev)
                    if not norm:
                        skipped_no_loc += 1
                        if not logged_sample:
                            logger.debug(
                                "Kismet skip: no location; keys=%s",
                                list(dev.keys()),
                            )
                        continue
                    if norm["phy"] not in allowed_phys:
                        skipped_phy += 1
                        if not logged_sample:
                            logger.debug("Kismet skip: phy %s not in %s", norm["phy"], allowed_phys)
                        continue
                    last_ts = max(last_ts, norm.get("last_time", last_ts))
                    uid = norm["uid"]
                    now = time.time()
                    last = last_sent.get(uid, 0.0)
                    if now - last < min_send_interval:
                        continue
                    cot = _device_to_cot(norm)
                    cot_messenger.send_cot(cot)
                    last_sent[uid] = now
                    sent += 1
                    if not logged_sample:
                        logger.debug("Kismet send sample: uid=%s phy=%s mac=%s lat=%s lon=%s", uid, norm.get("phy"), norm.get("mac"), norm.get("lat"), norm.get("lon"))
                        logged_sample = True
            except Exception as e:
                logger.warning("Kismet ingest error: %s; sleeping %.1fs", e, poll_interval)
            finally:
                if polled or sent or skipped_no_loc or skipped_phy:
                    logger.debug(
                        "Kismet poll stats: polled=%d sent=%d skipped_no_loc=%d skipped_phy=%d allowed_phys=%s",
                        polled,
                        sent,
                        skipped_no_loc,
                        skipped_phy,
                        allowed_phys,
                    )
            time.sleep(poll_interval)

    thread = threading.Thread(target=worker, name="kismet-worker", daemon=True)
    thread.start()
    return thread, stop_event
