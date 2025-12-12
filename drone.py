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
        now = datetime.datetime.utcnow()
        if stale_offset is not None:
            stale = now + datetime.timedelta(seconds=stale_offset)
        else:
            stale = now + datetime.timedelta(minutes=10)

        # pick CoT type by UA index, fallback to rotary‑wing VTOL
        cot_type = UA_COT_TYPE_MAP.get(self.ua_type, 'a-u-A-M-H-R')

        event = etree.Element(
            'event',
            version='2.0',
            uid=self.id,
            type=cot_type,
            time=now.strftime('%Y-%m-%dT%H:%M:%S.%fZ'),
            start=now.strftime('%Y-%m-%dT%H:%M:%S.%fZ'),
            stale=stale.strftime('%Y-%m-%dT%H:%M:%S.%fZ'),
            how='m-g'
        )

        etree.SubElement(
            event,
            'point',
            lat=str(self.lat),
            lon=str(self.lon),
            hae=str(self.alt),
            ce='35.0',
            le='999999'
        )

        detail = etree.SubElement(event, 'detail')
        etree.SubElement(detail, 'contact', callsign=self.id)
        etree.SubElement(detail, 'precisionlocation', geopointsrc='gps', altsrc='gps')

        # include <track> so ATAK will draw a track
        etree.SubElement(
            detail,
            'track',
            course=str(self.direction or 0.0),
            speed=str(self.speed or 0.0)
        )

        remarks = (
            f"MAC: {self.mac}, RSSI: {self.rssi}dBm; "
            f"ID Type: {self.id_type}; UA Type: {self.ua_type_name} "
            f"({self.ua_type}); "
            f"Operator ID: [{self.operator_id_type}: {self.operator_id}]; "
            f"Speed: {self.speed} m/s; Vert Speed: {self.vspeed} m/s; "
            f"Altitude: {self.alt} m; AGL: {self.height} m; "
            f"Course: {self.direction}°; "
            f"Index: {self.index}; Runtime: {self.runtime}s"
        )

        # Always try to add frequency (DJI usually supplies it)
        fmhz = self._fmt_freq_mhz(self.freq)
        if fmhz is not None:
            remarks += f"; Freq: ~{fmhz} MHz"

        # Alert reason
        if self.id == "drone-alert":
            remarks += "; Alert: Unknown DJI OcuSync format (Encrypted/Partial)"

        # FAA RID lookup enrichment (if available)
        if self.rid_make or self.rid_model:
            rid_label = f"{self.rid_make or ''} {self.rid_model or ''}".strip()
            if rid_label:
                remarks += f"; RID: {rid_label}"
        if self.rid_source:
            remarks += f"; RID Source: {self.rid_source}"
        if self.seen_by:
            remarks += f"; SeenBy: {self.seen_by}"
        if self.observed_at:
            obs_dt = datetime.datetime.utcfromtimestamp(self.observed_at)
            remarks += f"; ObservedAt: {obs_dt.isoformat()}Z"
        if self.rid_timestamp:
            remarks += f"; RID_TS: {self.rid_timestamp}"

        etree.SubElement(detail, 'remarks').text = xml.sax.saxutils.escape(remarks)
        etree.SubElement(detail, 'color', argb='-256')
        # dropped <usericon> so icon derives from event type

        # Structured RID block for ATAK details/raw views
        rid = etree.SubElement(detail, 'rid')
        if self.rid_make:
            rid.set('make', self.rid_make)
        if self.rid_model:
            rid.set('model', self.rid_model)
        if self.rid_source:
            rid.set('source', self.rid_source)

        xml_bytes = etree.tostring(event, pretty_print=True,
                                   xml_declaration=True, encoding='UTF-8')
        logger.debug("CoT XML for drone '%s':\n%s", self.id, xml_bytes.decode('utf-8'))
        return xml_bytes

    def to_pilot_cot_xml(self, stale_offset: Optional[float] = None) -> bytes:
        """Generates a CoT XML message for the pilot location.

        Returns empty bytes when UID is 'drone-alert' (pilot not decoded from OcuSync)."""
        # --- NEW: suppress when alert (no pilot from OcuSync) ---
        if self.id == "drone-alert":
            logger.debug("Skipping pilot CoT for 'drone-alert' (no pilot decoded).")
            return b""

        now = datetime.datetime.utcnow()
        if stale_offset is not None:
            stale = now + datetime.timedelta(seconds=stale_offset)
        else:
            stale = now + datetime.timedelta(minutes=10)

        base_id = self.id
        if base_id.startswith("drone-"):
            base_id = base_id[len("drone-"):]
        uid = f"pilot-{base_id}"

        event = etree.Element(
            'event',
            version='2.0',
            uid=uid,
            type='b-m-p-s-m',
            time=now.strftime('%Y-%m-%dT%H:%M:%S.%fZ'),
            start=now.strftime('%Y-%m-%dT%H:%M:%S.%fZ'),
            stale=stale.strftime('%Y-%m-%dT%H:%M:%S.%fZ'),
            how='m-g'
        )
        etree.SubElement(
            event,
            'point',
            lat=str(self.pilot_lat),
            lon=str(self.pilot_lon),
            hae=str(self.alt),
            ce='35.0',
            le='999999'
        )

        detail = etree.SubElement(event, 'detail')
        callsign = f"pilot-{base_id}"
        etree.SubElement(detail, 'contact', callsign=callsign)
        etree.SubElement(detail, 'precisionlocation', geopointsrc='gps', altsrc='gps')
        etree.SubElement(
            detail,
            'usericon',
            iconsetpath='com.atakmap.android.maps.public/Civilian/Person.png'
        )
        pilot_remarks = f"Pilot location for drone {self.id}"
        if self.seen_by:
            pilot_remarks += f"; SeenBy: {self.seen_by}"
        if self.observed_at:
            obs_dt = datetime.datetime.utcfromtimestamp(self.observed_at)
            pilot_remarks += f"; ObservedAt: {obs_dt.isoformat()}Z"
        etree.SubElement(detail, 'remarks').text = xml.sax.saxutils.escape(pilot_remarks)

        xml_bytes = etree.tostring(event, pretty_print=True,
                                   xml_declaration=True, encoding='UTF-8')
        logger.debug("CoT XML for pilot '%s':\n%s", self.id, xml_bytes.decode('utf-8'))
        return xml_bytes

    def to_home_cot_xml(self, stale_offset: Optional[float] = None) -> bytes:
        """Generates a CoT XML message for the home location.

        Returns empty bytes when UID is 'drone-alert' (home not decoded from OcuSync)."""
        # --- NEW: suppress when alert (no home from OcuSync) ---
        if self.id == "drone-alert":
            logger.debug("Skipping home CoT for 'drone-alert' (no home decoded).")
            return b""

        now = datetime.datetime.utcnow()
        if stale_offset is not None:
            stale = now + datetime.timedelta(seconds=stale_offset)
        else:
            stale = now + datetime.timedelta(minutes=10)

        base_id = self.id
        if base_id.startswith("drone-"):
            base_id = base_id[len("drone-"):]
        uid = f"home-{base_id}"

        event = etree.Element(
            'event',
            version='2.0',
            uid=uid,
            type='b-m-p-s-m',
            time=now.strftime('%Y-%m-%dT%H:%M:%S.%fZ'),
            start=now.strftime('%Y-%m-%dT%H:%M:%S.%fZ'),
            stale=stale.strftime('%Y-%m-%dT%H:%M:%S.%fZ'),
            how='m-g'
        )
        etree.SubElement(
            event,
            'point',
            lat=str(self.home_lat),
            lon=str(self.home_lon),
            hae=str(self.alt),
            ce='35.0',
            le='999999'
        )

        detail = etree.SubElement(event, 'detail')
        callsign = f"home-{base_id}"
        etree.SubElement(detail, 'contact', callsign=callsign)
        etree.SubElement(detail, 'precisionlocation', geopointsrc='gps', altsrc='gps')
        etree.SubElement(
            detail,
            'usericon',
            iconsetpath='com.atakmap.android.maps.public/Civilian/House.png'
        )
        home_remarks = f"Home location for drone {self.id}"
        if self.seen_by:
            home_remarks += f"; SeenBy: {self.seen_by}"
        if self.observed_at:
            obs_dt = datetime.datetime.utcfromtimestamp(self.observed_at)
            home_remarks += f"; ObservedAt: {obs_dt.isoformat()}Z"
        etree.SubElement(detail, 'remarks').text = xml.sax.saxutils.escape(home_remarks)

        xml_bytes = etree.tostring(event, pretty_print=True,
                                   xml_declaration=True, encoding='UTF-8')
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
