"""
MIT License

Copyright (c) 2024 cemaxecuter

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software are
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
"""

import datetime
import xml.sax.saxutils
from lxml import etree
from typing import Optional
import time
import logging

logger = logging.getLogger(__name__)

class SystemStatus:
    """Represents system status data, now including external GPS speed & track."""

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
        zynq_temp: str = 'N/A',
        speed: float = 0.0,
        track: float = 0.0
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
        # external GPS-provided fields
        self.speed = speed
        self.track = track
        
    def to_cot_xml(self) -> bytes:
        """Converts the system status data to a CoT XML message, embedding provided speed & track."""
        current_time = datetime.datetime.utcnow()
        stale_time = current_time + datetime.timedelta(minutes=10)

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
            event,
            'point',
            lat=str(self.lat),
            lon=str(self.lon),
            hae=str(self.alt),
            ce='35.0',
            le='999999'
        )

        detail = etree.SubElement(event, 'detail')
        etree.SubElement(detail, 'contact', endpoint='', phone='', callsign=self.id)
        etree.SubElement(detail, 'precisionlocation', geopointsrc='gps', altsrc='gps')

        remarks_text = (
            f"CPU Usage: {self.cpu_usage}%, "
            f"Memory Total: {self.memory_total:.2f} MB, Memory Available: {self.memory_available:.2f} MB, "
            f"Disk Total: {self.disk_total:.2f} MB, Disk Used: {self.disk_used:.2f} MB, "
            f"Temperature: {self.temperature}°C, "
            f"Uptime: {self.uptime} seconds, "
            f"Pluto Temp: {self.pluto_temp}°C, "
            f"Zynq Temp: {self.zynq_temp}°C"
        )
        etree.SubElement(detail, 'remarks').text = xml.sax.saxutils.escape(remarks_text)
        etree.SubElement(detail, 'color', argb='-256')

        # embed GPS-provided track & speed
        etree.SubElement(
            detail,
            'track',
            course=f"{self.track:.1f}",
            speed=f"{self.speed:.2f}"
        )

        cot_xml_bytes = etree.tostring(
            event,
            pretty_print=True,
            xml_declaration=True,
            encoding='UTF-8'
        )

        # Debug logging
        logger.debug("SystemStatus CoT XML for '%s':\n%s", self.id, cot_xml_bytes.decode('utf-8'))

        return cot_xml_bytes
