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
import time
import math
import logging
import xml.sax.saxutils
from typing import Optional
from lxml import etree

logger = logging.getLogger(__name__)

# Map our UA_TYPE_MAPPING indices (0–15) to CoT event types for drones
# Fallback to rotary‑wing VTOL if unknown or not in map
UA_COT_TYPE_MAP = {
    1: 'a-f-A-f',       # Aeroplane / fixed wing
    2: 'a-u-A-M-H-R',   # Helicopter / multirotor
    3: 'a-u-A-M-H-R',   # Gyroplane (treat as rotorcraft)
    4: 'a-u-A-M-H-R',   # VTOL
    5: 'a-f-A-f',       # Ornithopter (treat as fixed wing)
    6: 'a-f-A-f',       # Glider
    7: 'b-m-p-s-m',     # Kite (surface dot)
    8: 'b-m-p-s-m',     # Free balloon
    9: 'b-m-p-s-m',     # Captive balloon
    10: 'b-m-p-s-m',    # Airship
    11: 'b-m-p-s-m',    # Parachute
    12: 'b-m-p-s-m',    # Rocket
    13: 'b-m-p-s-m',    # Tethered powered aircraft
    14: 'b-m-p-s-m',    # Ground obstacle
    15: 'b-m-p-s-m',    # Other
}

class Drone:
    """Represents a drone and its telemetry data."""

    def __init__(
        self,
        id: str,
        lat: float,
        lon: float,
        speed: float,
        vspeed: float,
        alt: float,
        height: float,
        pilot_lat: float,
        pilot_lon: float,
        description: str,
        mac: str,
        rssi: int,
        home_lat: float = 0.0,
        home_lon: float = 0.0,
        id_type: str = "",
        ua_type: Optional[int] = None,
        ua_type_name: str = "",
        operator_id_type: str = "",
        operator_id: str = "",
        op_status: str = "",
        height_type: str = "",
        ew_dir: str = "",
        direction: Optional[float] = None,
        speed_multiplier: Optional[float] = None,
        pressure_altitude: Optional[float] = None,
        vertical_accuracy: str = "",
        horizontal_accuracy: str = "",
        baro_accuracy: str = "",
        speed_accuracy: str = "",
        timestamp: str = "",
        rid_timestamp: str = "",
        observed_at: Optional[float] = None,
        timestamp_accuracy: str = "",
        index: int = 0,
        runtime: int = 0,
        caa_id: str = "",
        freq: Optional[float] = None,
        seen_by: Optional[str] = None,
    ):
        self.id = id
        self.id_type = id_type
        self.ua_type = ua_type
        self.ua_type_name = ua_type_name

        # Remote ID extras
        self.operator_id_type = operator_id_type
        self.operator_id = operator_id
        self.op_status = op_status
        self.height_type = height_type
        self.ew_dir = ew_dir
        self.direction = direction
        self.speed_multiplier = speed_multiplier
        self.pressure_altitude = pressure_altitude
        self.vertical_accuracy = vertical_accuracy
        self.horizontal_accuracy = horizontal_accuracy
        self.baro_accuracy = baro_accuracy
        self.speed_accuracy = speed_accuracy
        self.timestamp = timestamp
        self.rid_timestamp = rid_timestamp or timestamp
        self.observed_at = observed_at
        self.timestamp_accuracy = timestamp_accuracy
        self.seen_by: Optional[str] = seen_by

        # store previous position for fallback bearing calculation
        self.prev_lat: Optional[float] = None
        self.prev_lon: Optional[float] = None

        self.index = index
        self.runtime = runtime
        self.mac = mac
        self.rssi = rssi
        self.lat = lat
        self.lon = lon
        self.speed = speed
        self.vspeed = vspeed
        self.alt = alt
        self.height = height
        self.pilot_lat = pilot_lat
        self.pilot_lon = pilot_lon
        self.home_lat = home_lat
        self.home_lon = home_lon
        self.description = description

        self.last_update_time = time.time()
        self.last_sent_time = 0.0
        self.last_sent_lat = lat
        self.last_sent_lon = lon
        self.caa_id = caa_id
        self.last_keepalive_time = 0.0
        self.freq: Optional[float] = freq

        # FAA Remote ID lookup cache (per-drone, in-memory only)
        self.rid_tracking: Optional[str] = None
        self.rid_status: Optional[str] = None
        self.rid_make: Optional[str] = None
        self.rid_model: Optional[str] = None
        self.rid_source: Optional[str] = None
        self.rid_lookup_attempted: bool = False
        self.rid_lookup_success: bool = False
        self.rid_lookup_pending: bool = False

    def update(
        self,
        lat: float,
        lon: float,
        speed: float,
        vspeed: float,
        alt: float,
        height: float,
        pilot_lat: float,
        pilot_lon: float,
        description: str,
        mac: str,
        rssi: int,
        home_lat: float = 0.0,
        home_lon: float = 0.0,
        id_type: str = "",
        ua_type: Optional[int] = None,
        ua_type_name: str = "",
        operator_id_type: str = "",
        operator_id: str = "",
        op_status: str = "",
        height_type: str = "",
        ew_dir: str = "",
        direction: Optional[float] = None,
        speed_multiplier: Optional[float] = None,
        pressure_altitude: Optional[float] = None,
        vertical_accuracy: str = "",
        horizontal_accuracy: str = "",
        baro_accuracy: str = "",
        speed_accuracy: str = "",
        timestamp: str = "",
        rid_timestamp: str = "",
        observed_at: Optional[float] = None,
        timestamp_accuracy: str = "",
        index: int = 0,
        runtime: int = 0,
        caa_id: str = "",
        freq: Optional[float] = None,
        seen_by: Optional[str] = None,
    ):
        """Updates the drone's telemetry data, computes fallback bearing if needed."""
        # remember previous location
        self.prev_lat = self.lat
        self.prev_lon = self.lon

        self.lat = lat
        self.lon = lon
        self.speed = speed
        self.vspeed = vspeed
        self.alt = alt
        self.height = height
        self.pilot_lat = pilot_lat
        self.pilot_lon = pilot_lon
        self.home_lat = home_lat
        self.home_lon = home_lon
        self.description = description
        self.mac = mac
        self.rssi = rssi
        self.index = index
        self.runtime = runtime
        self.id_type = id_type

        if ua_type is not None:
            self.ua_type = ua_type
        if ua_type_name:
            self.ua_type_name = ua_type_name

        # update Remote ID extras
        if operator_id_type:
            self.operator_id_type = operator_id_type
        if operator_id:
            self.operator_id = operator_id
        if op_status:
            self.op_status = op_status
        if height_type:
            self.height_type = height_type
        if ew_dir:
            self.ew_dir = ew_dir
        if direction is not None:
            self.direction = direction
        if speed_multiplier is not None:
            self.speed_multiplier = speed_multiplier
        if pressure_altitude is not None:
            self.pressure_altitude = pressure_altitude
        if vertical_accuracy:
            self.vertical_accuracy = vertical_accuracy
        if horizontal_accuracy:
            self.horizontal_accuracy = horizontal_accuracy
        if baro_accuracy:
            self.baro_accuracy = baro_accuracy
        if speed_accuracy:
            self.speed_accuracy = speed_accuracy
        if timestamp:
            self.timestamp = timestamp
        if rid_timestamp:
            self.rid_timestamp = rid_timestamp
        if observed_at is not None:
            self.observed_at = observed_at
        if timestamp_accuracy:
            self.timestamp_accuracy = timestamp_accuracy

        if caa_id:
            self.caa_id = caa_id
        if freq is not None:
            self.freq = freq

        if seen_by is not None:
            self.seen_by = seen_by

        self.last_update_time = time.time()

        # fallback bearing calculation if no heading provided
        if self.direction is None and self.prev_lat is not None:
            lat1 = math.radians(self.prev_lat)
            lon1 = math.radians(self.prev_lon)
            lat2 = math.radians(self.lat)
            lon2 = math.radians(self.lon)
            delta_lon = lon2 - lon1

            x = math.sin(delta_lon) * math.cos(lat2)
            y = (math.cos(lat1) * math.sin(lat2) -
                 math.sin(lat1) * math.cos(lat2) * math.cos(delta_lon))
            theta = math.atan2(x, y)
            self.direction = (math.degrees(theta) + 360) % 360

    @staticmethod
    def _fmt_freq_mhz(freq: Optional[float]) -> Optional[float]:
        """Return frequency in MHz (rounded). If value looks like Hz, convert to MHz."""
        if freq is None or not isinstance(freq, (int, float)) or math.isnan(freq) or math.isinf(freq):
            return None
        f = float(freq)
        if f > 1e5:
            f = f / 1e6
        return round(f, 3)

    def to_cot_xml(self, stale_offset: Optional[float] = None) -> bytes:
        """Converts the drone's telemetry data to a CoT XML message, including a <track>."""
        from utils.cot_builder import build_drone_cot

        if stale_offset is None:
            stale_offset = 600.0  # 10 minutes default

        # Add cot_type attribute for the builder (pick CoT type by UA index)
        self.cot_type = UA_COT_TYPE_MAP.get(self.ua_type, 'a-u-A-M-H-R')

        xml_bytes = build_drone_cot(self, stale_offset)
        logger.debug("CoT XML for drone '%s':\n%s", self.id, xml_bytes.decode('utf-8'))
        return xml_bytes

    def to_dict(self) -> dict:
        """Return a JSON-safe representation for API export."""
        return {
            "id": self.id,
            "id_type": self.id_type,
            "ua_type": self.ua_type,
            "ua_type_name": self.ua_type_name,
            "operator_id_type": self.operator_id_type,
            "operator_id": self.operator_id,
            "op_status": self.op_status,
            "height_type": self.height_type,
            "ew_dir": self.ew_dir,
            "direction": self.direction,
            "speed_multiplier": self.speed_multiplier,
            "pressure_altitude": self.pressure_altitude,
            "vertical_accuracy": self.vertical_accuracy,
            "horizontal_accuracy": self.horizontal_accuracy,
            "baro_accuracy": self.baro_accuracy,
            "speed_accuracy": self.speed_accuracy,
            "timestamp": self.timestamp,
            "rid_timestamp": self.rid_timestamp,
            "observed_at": self.observed_at,
            "timestamp_accuracy": self.timestamp_accuracy,
            "seen_by": self.seen_by,
            "lat": self.lat,
            "lon": self.lon,
            "alt": self.alt,
            "height": self.height,
            "speed": self.speed,
            "vspeed": self.vspeed,
            "pilot_lat": self.pilot_lat,
            "pilot_lon": self.pilot_lon,
            "home_lat": self.home_lat,
            "home_lon": self.home_lon,
            "description": self.description,
            "mac": self.mac,
            "rssi": self.rssi,
            "index": self.index,
            "runtime": self.runtime,
            "caa_id": self.caa_id,
            "freq": self._fmt_freq_mhz(self.freq),
            "rid": {
                "tracking": self.rid_tracking,
                "status": self.rid_status,
                "make": self.rid_make,
                "model": self.rid_model,
                "source": self.rid_source,
                "lookup_attempted": self.rid_lookup_attempted,
                "lookup_success": self.rid_lookup_success,
            },
            "last_update_time": self.last_update_time,
            "track_type": "drone",
        }

    def to_pilot_cot_xml(self, stale_offset: Optional[float] = None) -> bytes:
        """Generates a CoT XML message for the pilot location.

        Returns empty bytes when UID is 'drone-alert' (pilot not decoded from OcuSync)."""
        from utils.cot_builder import build_pilot_cot

        if stale_offset is None:
            stale_offset = 600.0  # 10 minutes default

        xml_bytes = build_pilot_cot(self, stale_offset)
        if xml_bytes:
            logger.debug("CoT XML for pilot '%s':\n%s", self.id, xml_bytes.decode('utf-8'))
        return xml_bytes

    def to_home_cot_xml(self, stale_offset: Optional[float] = None) -> bytes:
        """Generates a CoT XML message for the home location.

        Returns empty bytes when UID is 'drone-alert' (home not decoded from OcuSync)."""
        from utils.cot_builder import build_home_cot

        if stale_offset is None:
            stale_offset = 600.0  # 10 minutes default

        xml_bytes = build_home_cot(self, stale_offset)
        if xml_bytes:
            logger.debug("CoT XML for home '%s':\n%s", self.id, xml_bytes.decode('utf-8'))
        return xml_bytes

    def apply_rid_lookup_result(self, lookup: dict) -> None:
        """Cache FAA RID lookup results on the drone to avoid repeat queries."""
        self.rid_lookup_attempted = True
        self.rid_lookup_success = bool(lookup.get("found", False))

        if not self.rid_lookup_success:
            return

        self.rid_tracking = lookup.get("rid_tracking")
        self.rid_status = lookup.get("status")
        self.rid_make = lookup.get("make")
        self.rid_model = lookup.get("model")
        self.rid_source = lookup.get("source")
