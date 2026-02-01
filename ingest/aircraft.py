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
        self._last_cleanup = 0.0
        self._cleanup_interval = 300.0  # cleanup every 5 minutes
        self._entry_ttl = 600.0  # remove entries older than 10 minutes

    def make_uid(self, craft: Dict[str, Any]) -> Optional[str]:
        icao = (craft.get("hex") or "").strip().lower()
        if not icao:
            return None
        return f"{self.uid_prefix}{icao}"

    def _cleanup_last_sent(self):
        """Remove stale entries from last_sent to prevent unbounded growth."""
        now = time.time()
        if now - self._last_cleanup < self._cleanup_interval:
            return
        self._last_cleanup = now
        cutoff = now - self._entry_ttl
        stale = [k for k, v in self.last_sent.items() if v < cutoff]
        for k in stale:
            del self.last_sent[k]

    def should_send(self, uid: str) -> bool:
        self._cleanup_last_sent()  # periodic cleanup to prevent memory leak
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
        from utils.cot_builder import build_adsb_cot

        lat = craft.get("lat")
        lon = craft.get("lon")
        if lat is None or lon is None:
            return None

        uid = self.make_uid(craft)
        if not uid:
            return None

        return build_adsb_cot(craft, uid, seen_by, self.stale)

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
            "rssi": craft.get("rssi"),  # Signal strength from readsb (dBFS)
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
    extra_sinks: Optional[List] = None,
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

            alt = craft.get("alt_geom")
            if alt is None:
                alt = craft.get("alt_baro")
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

            # Publish to extra sinks (e.g., MQTT)
            if extra_sinks:
                craft_with_seen_by = dict(craft)
                craft_with_seen_by["seen_by"] = current_seen_by
                for sink in extra_sinks:
                    try:
                        if hasattr(sink, "publish_aircraft"):
                            sink.publish_aircraft(craft_with_seen_by)
                    except Exception as e:
                        logger.warning(f"ADS-B: sink publish_aircraft failed for {uid}: {e}")

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
