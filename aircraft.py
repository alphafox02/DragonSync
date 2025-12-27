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
"""

import time
import json
import logging
import datetime
import xml.sax.saxutils
from typing import Dict, Any, List, Optional, Callable, Union
from urllib.request import urlopen, URLError

from lxml import etree

logger = logging.getLogger(__name__)


class ADSBTracker:
    """
    Minimal per-target tracker for ADS-B:
    - builds stable UIDs from hex
    - rate-limits CoT to avoid spamming TAK
    """

    def __init__(self, rate_limit: float, stale: float, uid_prefix: str):
        self.rate_limit = max(rate_limit, 0.5)
        self.stale = max(stale, 5.0)
        self.uid_prefix = uid_prefix
        self.last_sent: Dict[str, float] = {}

    def make_uid(self, craft: Dict[str, Any]) -> Optional[str]:
        icao = (craft.get("hex") or "").strip().lower()
        if not icao:
            return None
        return f"{self.uid_prefix}{icao}"

    def should_send(self, uid: str) -> bool:
        now = time.time()
        last = self.last_sent.get(uid, 0.0)
        if now - last >= self.rate_limit:
            self.last_sent[uid] = now
            return True
        return False

    def craft_to_cot(self, craft: Dict[str, Any], seen_by: Optional[str] = None) -> Optional[bytes]:
        """
        Map a single aircraft from readsb / dump1090-style JSON into a CoT event.

        Fields we care about (if present):
          - hex, flight, lat, lon, alt_geom, alt_baro, gs (kt), track (deg)
          - squawk, category, reg, onground / OnGround, nac_p / NACp, nac_v / NACv
        """
        lat = craft.get("lat")
        lon = craft.get("lon")
        if lat is None or lon is None:
            return None

        uid = self.make_uid(craft)
        if not uid:
            return None

        # Prefer geometric altitude, fall back to barometric, else 0
        alt = craft.get("alt_geom")
        if alt is None:
            alt = craft.get("alt_baro", 0)

        # Identity-ish stuff
        flight = (craft.get("flight") or "").strip()
        hex_id = (craft.get("hex") or "").strip().upper()
        callsign = uid
        squawk = craft.get("squawk")
        # readsb can add reg if using db-file / db-file-lt, but it's optional
        reg = craft.get("reg") or craft.get("r")
        category = craft.get("category") or craft.get("cat")

        # Kinematics
        gs = float(craft.get("gs") or 0.0)        # knots
        track = float(craft.get("track") or 0.0)  # degrees

        # Ground / air state
        # readsb: "onground": 1/0; other sources might use "OnGround": True/False
        on_ground = bool(
            craft.get("onground") or craft.get("OnGround") or False
        )

        # Position quality (NACp / NACv -> CE / LE), if present
        nac_p = craft.get("NACp", craft.get("nac_p"))
        nac_v = craft.get("NACv", craft.get("nac_v", nac_p))

        # Defaults (roughly what you had before)
        ce_val = 35.0
        le_val = 999999.0

        if nac_p is not None:
            try:
                nac_p_f = float(nac_p)
                nac_v_f = float(nac_v) if nac_v is not None else nac_p_f
                # Inspired by common ADS-B handling: slightly different
                # constant when on the ground vs airborne.
                ground_const = 51.56 if on_ground else 56.57
                ce_val = nac_p_f + ground_const
                le_val = nac_v_f + 12.5
            except (TypeError, ValueError):
                # fall back to defaults if parsing fails
                ce_val = 35.0
                le_val = 999999.0

        now = datetime.datetime.utcnow()
        t = now.strftime("%Y-%m-%dT%H:%M:%S.%fZ")
        stale = (now + datetime.timedelta(seconds=self.stale)).strftime(
            "%Y-%m-%dT%H:%M:%S.%fZ"
        )

        # Simple/default air track for now; we can refine later.
        cot_type = "a-f-A"

        event = etree.Element(
            "event",
            version="2.0",
            uid=uid,
            type=cot_type,
            time=t,
            start=t,
            stale=stale,
            how="m-g",
        )

        etree.SubElement(
            event,
            "point",
            lat=str(lat),
            lon=str(lon),
            hae=str(float(alt)),
            ce=str(float(ce_val)),
            le=str(float(le_val)),
        )

        detail = etree.SubElement(event, "detail")
        etree.SubElement(detail, "contact", callsign=callsign)

        # Include <track> so TAK draws heading
        track_el = etree.SubElement(
            detail,
            "track",
            course=str(track),
            speed=str(gs),
        )

        # If we know it's on the ground, we can hint at that via slope.
        if on_ground:
            track_el.set("slope", "0")

        display_id = flight or hex_id
        # Build richer remarks but keep it compact
        remark_parts = [
            "ADS-B",
            f"hex={hex_id}" if hex_id else None,
            f"flight={display_id}" if display_id else None,
            f"alt={alt}ft",
            f"gs={gs}kt",
            f"track={track}",
        ]

        if squawk:
            remark_parts.append(f"squawk={squawk}")
        if reg:
            remark_parts.append(f"reg={reg}")
        if category:
            remark_parts.append(f"cat={category}")
        if on_ground:
            remark_parts.append("onground=1")

        # You can flip this to "src=readsb" if you want to be explicit
        remark_parts.append("src=adsb")
        if seen_by:
            remark_parts.append(f"SeenBy: {seen_by}")

        remarks = " ".join(p for p in remark_parts if p)
        etree.SubElement(detail, "remarks").text = xml.sax.saxutils.escape(remarks)

        xml_bytes = etree.tostring(
            event,
            pretty_print=False,
            xml_declaration=True,
            encoding="UTF-8",
        )
        return xml_bytes

    def craft_to_dict(
        self,
        craft: Dict[str, Any],
        seen_by: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """Build a JSON-safe aircraft dict for API export."""
        lat = craft.get("lat")
        lon = craft.get("lon")
        if lat is None or lon is None:
            return None
        uid = self.make_uid(craft)
        if not uid:
            return None
        alt = craft.get("alt_geom")
        if alt is None:
            alt = craft.get("alt_baro", 0)
        gs = float(craft.get("gs") or 0.0)
        track = float(craft.get("track") or 0.0)
        flight = (craft.get("flight") or "").strip()
        callsign = uid
        squawk = craft.get("squawk")
        reg = craft.get("reg") or craft.get("r")
        category = craft.get("category") or craft.get("cat")
        on_ground = bool(craft.get("onground") or craft.get("OnGround") or False)
        nac_p = craft.get("NACp", craft.get("nac_p"))
        nac_v = craft.get("NACv", craft.get("nac_v", nac_p))
        return {
            "id": uid,
            "track_type": "aircraft",
            "callsign": callsign,
            "hex": (craft.get("hex") or "").upper(),
            "lat": lat,
            "lon": lon,
            "alt": alt,
            "ground_speed": gs,
            "track": track,
            "squawk": squawk,
            "reg": reg,
            "category": category,
            "flight": flight or None,
            "on_ground": on_ground,
            "nac_p": nac_p,
            "nac_v": nac_v,
            "last_update_time": time.time(),
            "source": "adsb",
            "seen_by": seen_by,
        }


def _load_aircraft(json_url: str) -> List[Dict[str, Any]]:
    """
    Load aircraft list from file:// or http(s)://.
    Safe against transient read/JSON errors.
    """
    if json_url.startswith("file://"):
        path = json_url[7:]
        with open(path, "r") as f:
            data = json.load(f)
    else:
        # http/https
        with urlopen(json_url, timeout=2) as resp:
            data = json.load(resp)

    ac_list = data.get("aircraft", [])
    if isinstance(ac_list, list):
        return ac_list
    return []


def adsb_worker_loop(
    json_url: str,
    cot_messenger,
    uid_prefix: str = "adsb-",
    rate_limit: float = 3.0,
    stale: float = 15.0,
    min_alt: int = 0,
    max_alt: int = 0,
    poll_interval: float = 1.0,
    stop_event=None,
    aircraft_cache: Optional[dict] = None,
    seen_by: Optional[Union[str, Callable[[], Optional[str]]]] = None,
    cache_ttl: Optional[float] = 120.0,
):
    """
    Background worker:
      - periodically loads aircraft JSON (readsb / dump1090 style)
      - builds CoT for each aircraft
      - sends via shared CotMessenger

    Design goals:
      - If file is missing: log occasionally, keep running.
      - If JSON is mid-write / corrupt: skip this cycle, no crash.
      - Respects a stop_event for clean shutdown.
    """
    tracker = ADSBTracker(rate_limit=rate_limit, stale=stale, uid_prefix=uid_prefix)
    logger.info(f"ADS-B worker started for {json_url}")

    last_missing_log = 0.0
    missing_log_interval = 30.0  # seconds

    while True:
        if stop_event is not None and stop_event.is_set():
            logger.info("ADS-B worker stopping (stop_event set).")
            break

        try:
            aircraft_list = _load_aircraft(json_url)
        except FileNotFoundError:
            now = time.time()
            if now - last_missing_log > missing_log_interval:
                logger.warning(
                    f"ADS-B: {json_url} not found; waiting for JSON output."
                )
                last_missing_log = now
            time.sleep(poll_interval)
            continue
        except (json.JSONDecodeError, URLError) as e:
            # Likely mid-write or transient; don't spam logs.
            logger.debug(f"ADS-B: transient read/parse error from {json_url}: {e}")
            time.sleep(poll_interval)
            continue
        except Exception as e:
            logger.exception(f"ADS-B: unexpected error reading {json_url}: {e}")
            time.sleep(poll_interval)
            continue

        if callable(seen_by):
            try:
                current_seen_by = seen_by()
            except Exception:
                current_seen_by = None
        else:
            current_seen_by = seen_by

        for craft in aircraft_list:
            lat = craft.get("lat")
            lon = craft.get("lon")
            if lat is None or lon is None:
                continue

            alt = craft.get("alt_geom") or craft.get("alt_baro")
            if min_alt and (alt is None or alt < min_alt):
                continue
            if max_alt and alt is not None and alt > max_alt:
                continue

            uid = tracker.make_uid(craft)
            if not uid or not tracker.should_send(uid):
                continue

            cot = tracker.craft_to_cot(craft, seen_by=current_seen_by)
            if cot:
                try:
                    cot_messenger.send_cot(cot)
                except Exception as e:
                    logger.exception(f"ADS-B: failed to send CoT for {uid}: {e}")
            # optional API cache
            if aircraft_cache is not None:
                try:
                    dto = tracker.craft_to_dict(craft, seen_by=current_seen_by)
                    if dto:
                        aircraft_cache[dto["id"]] = dto
                except Exception:
                    pass

        if aircraft_cache is not None and cache_ttl is not None and cache_ttl > 0:
            now = time.time()
            for key, dto in list(aircraft_cache.items()):
                try:
                    last = dto.get("last_update_time")
                    if last is None or (now - float(last)) > cache_ttl:
                        aircraft_cache.pop(key, None)
                except Exception:
                    aircraft_cache.pop(key, None)

        time.sleep(poll_interval)

    logger.info("ADS-B worker exited cleanly.")
