"""
MIT License

Copyright (c) 2025 cemaxecuter

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
"""

import time
import json
import logging
import datetime
import xml.sax.saxutils
from typing import Dict, Any, List, Optional
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

    def craft_to_cot(self, craft: Dict[str, Any]) -> Optional[bytes]:
        """
        Map a single aircraft from dump1090's aircraft.json into a simple CoT event.

        Fields we care about (if present):
          - hex, flight, lat, lon, alt_geom, alt_baro, gs (kt), track (deg)
        """
        lat = craft.get("lat")
        lon = craft.get("lon")
        if lat is None or lon is None:
            return None

        uid = self.make_uid(craft)
        if not uid:
            return None

        # prefer geometric altitude, fall back to barometric, else 0
        alt = craft.get("alt_geom")
        if alt is None:
            alt = craft.get("alt_baro", 0)

        callsign = (craft.get("flight") or craft.get("hex") or uid).strip()
        gs = float(craft.get("gs") or 0.0)       # knots
        track = float(craft.get("track") or 0.0) # degrees

        now = datetime.datetime.utcnow()
        t = now.strftime("%Y-%m-%dT%H:%M:%S.%fZ")
        stale = (now + datetime.timedelta(seconds=self.stale)).strftime(
            "%Y-%m-%dT%H:%M:%S.%fZ"
        )

        # Simple/default air track. We can get fancy later.
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
            ce="35.0",
            le="999999",
        )

        detail = etree.SubElement(event, "detail")
        etree.SubElement(detail, "contact", callsign=callsign)

        # Include <track> so TAK draws heading
        etree.SubElement(
            detail,
            "track",
            course=str(track),
            speed=str(gs),
        )

        remarks = (
            f"ADS-B hex={craft.get('hex','').upper()} "
            f"cs={callsign} alt={alt}ft gs={gs}kt track={track} "
            f"src=dump1090"
        )
        etree.SubElement(detail, "remarks").text = xml.sax.saxutils.escape(remarks)

        xml_bytes = etree.tostring(
            event,
            pretty_print=False,
            xml_declaration=True,
            encoding="UTF-8",
        )
        return xml_bytes


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
):
    """
    Background worker:
      - periodically loads aircraft.json
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
                logger.warning(f"ADS-B: {json_url} not found; waiting for dump1090 output.")
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

            cot = tracker.craft_to_cot(craft)
            if not cot:
                continue

            try:
                cot_messenger.send_cot(cot)
            except Exception as e:
                logger.exception(f"ADS-B: failed to send CoT for {uid}: {e}")

        time.sleep(poll_interval)

    logger.info("ADS-B worker exited cleanly.")
