MIT License

Copyright (c) 2024 cemaxecuter

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
LIABILITY, WHETHER IN AN ACTION OF TORT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.


import datetime
import xml.sax.saxutils
from lxml import etree
from typing import Optional
import time
import logging
import math

logger = logging.getLogger(__name__)


def haversine(lat1_deg: float, lon1_deg: float, lat2_deg: float, lon2_deg: float) -> float:
    """Return distance in meters between two WGS84 points."""
    EARTH_RADIUS = 6_371_000.0
    lat1 = math.radians(lat1_deg)
    lon1 = math.radians(lon1_deg)
    lat2 = math.radians(lat2_deg)
    lon2 = math.radians(lon2_deg)

    delta_lat = lat2 - lat1
    delta_lon = lon2 - lon1

    a = (
        math.sin(delta_lat / 2) ** 2
        + math.cos(lat1) * math.cos(lat2) * math.sin(delta_lon / 2) ** 2
    )
    return EARTH_RADIUS * 2 * math.asin(math.sqrt(a))


def initial_bearing(lat1_deg: float, lon1_deg: float, lat2_deg: float, lon2_deg: float) -> float:
    """Return initial bearing in degrees from point1 → point2."""
    lat1 = math.radians(lat1_deg)
    lat2 = math.radians(lat2_deg)
    delta_lon = math.radians(lon2_deg - lon1_deg)

    y = math.sin(delta_lon) * math.cos(lat2)
    x = (
        math.cos(lat1) * math.sin(lat2)
        - math.sin(lat1) * math.cos(lat2) * math.cos(delta_lon)
    )
    bearing_rad = math.atan2(y, x)
    return (math.degrees(bearing_rad) + 360) % 360


class SystemStatus:
    """Represents system status data."""

    def __init__(
        self,
        serial_number: str,
        lat: float,
        lon: float,
        alt: float,
        cpu_usage: float = 0.0,
        memory_total: float = 0.0,
        memory_available: float = 0.0,
        disk_total: float = 0.0,
        disk_used: float = 0.0,
        temperature: float = 0.0,
        uptime: float = 0.0,
        pluto_temp: str = 'N/A',
        zynq_temp: str = 'N/A'
    ):
        self.id = f"wardragon-{serial_number}"
        self.lat = lat
        self.lon = lon
        self.alt = alt
        self.cpu_usage = cpu_usage
        self.memory_total = memory_total
        self.memory_available = memory_available
        self.disk_total = disk_total
        self.disk_used = disk_used
        self.temperature = temperature
        self.uptime = uptime
        self.last_update_time = time.time()
        self.pluto_temp = pluto_temp
        self.zynq_temp = zynq_temp
        # state for track estimation
        self.last_lat: Optional[float] = None
        self.last_lon: Optional[float] = None
        self.last_time: Optional[float] = None

    def to_cot_xml(self) -> bytes:
        """Converts the system status data to a CoT XML message, adding track if available."""
        current_time = datetime.datetime.utcnow()
        stale_time = current_time + datetime.timedelta(minutes=10)

        # compute track & speed
        now_ts = time.time()
        track_speed = None
        if self.last_time is not None and now_ts > self.last_time:
            distance_m = haversine(self.last_lat, self.last_lon, self.lat, self.lon)
            elapsed = now_ts - self.last_time
            if elapsed > 0:
                speed_m_s = distance_m / elapsed
                course_deg = initial_bearing(self.last_lat, self.last_lon, self.lat, self.lon)
                track_speed = (course_deg, speed_m_s)

        # update last fix
        self.last_lat = self.lat
        self.last_lon = self.lon
        self.last_time = now_ts

        # build CoT
        event = etree.Element(
            'event',
            version='2.0',
            uid=self.id,
            type='a-f-G-E-S',
            time=current_time.strftime('%Y-%m-%dT%H:%M:%S.%fZ'),
            start=current_time.strftime('%Y-%m-%dT%H:%M:%S.%fZ'),
            stale=stale_time.strftime('%Y-%m-%dT%H:%M:%S.%fZ'),
            how='m-g'
        )

        etree.SubElement(
            etree.SubElement(event, 'point'),
            'point',
            lat=str(self.lat), lon=str(self.lon), hae=str(self.alt), ce='35.0', le='999999'
        )
        detail = etree.SubElement(event, 'detail')
        etree.SubElement(detail, 'contact', endpoint='', phone='', callsign=self.id)
        etree.SubElement(detail, 'precisionlocation', geopointsrc='gps', altsrc='gps')

        remarks = (
            f"CPU Usage: {self.cpu_usage}%, "
            f"Memory Total: {self.memory_total:.2f} MB, Memory Available: {self.memory_available:.2f} MB, "
            f"Disk Total: {self.disk_total:.2f} MB, Disk Used: {self.disk_used:.2f} MB, "
            f"Temperature: {self.temperature}°C, Uptime: {self.uptime} s, "
            f"Pluto Temp: {self.pluto_temp}°C, Zynq Temp: {self.zynq_temp}°C"
        )
        xml.sax.saxutils.escape(remarks)
        etree.SubElement(detail, 'remarks').text = remarks
        etree.SubElement(detail, 'color', argb='-256')

        # insert track element if calculated
        if track_speed is not None:
            course_deg, speed_m_s = track_speed
            etree.SubElement(
                detail,
                'track',
                course=f"{course_deg:.1f}",
                speed=f"{speed_m_s:.2f}"
            )

        cot_bytes = etree.tostring(
            event,
            pretty_print=True,
            xml_declaration=True,
            encoding='UTF-8'
        )
        logger.debug("CoT XML for %s:\n%s", self.id, cot_bytes.decode())
        return cot_bytes
