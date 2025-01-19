"""
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
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
"""


import datetime
import xml.sax.saxutils
from lxml import etree
from typing import Optional
import time

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

    def to_cot_xml(self) -> bytes:
        """Converts the system status data to a CoT XML message."""
        current_time = datetime.datetime.utcnow()
        stale_time = current_time + datetime.timedelta(minutes=10)

        event = etree.Element(
            'event',
            version='2.0',
            uid=self.id,
            type='b-m-p-s-m',
            time=current_time.strftime('%Y-%m-%dT%H:%M:%S.%fZ'),
            start=current_time.strftime('%Y-%m-%dT%H:%M:%S.%fZ'),
            stale=stale_time.strftime('%Y-%m-%dT%H:%M:%S.%fZ'),
            how='m-g'
        )

        point = etree.SubElement(
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

        # Format remarks with system statistics
        remarks_text = (
            f"CPU Usage: {self.cpu_usage}%, "
            f"Memory Total: {self.memory_total:.2f} MB, Memory Available: {self.memory_available:.2f} MB, "
            f"Disk Total: {self.disk_total:.2f} MB, Disk Used: {self.disk_used:.2f} MB, "
            f"Temperature: {self.temperature}°C, "
            f"Uptime: {self.uptime} seconds"
        )

        # Escape special characters in remarks
        remarks_text = xml.sax.saxutils.escape(remarks_text)

        etree.SubElement(detail, 'remarks').text = remarks_text

        etree.SubElement(detail, 'color', argb='-256')

        # Include usericon
        etree.SubElement(
            detail,
            'usericon',
            iconsetpath='34ae1613-9645-4222-a9d2-e5f243dea2865/Military/Ground_Vehicle.png'  # Use appropriate icon
        )

        cot_xml_bytes = etree.tostring(event, pretty_print=True, xml_declaration=True, encoding='UTF-8')

        # --- Debug Logging ---
        # Only prints if the logger is set to DEBUG (e.g. by --debug in your main script)
        logger.debug("SystemStatus CoT XML for '%s':\n%s", self.id, cot_xml_bytes.decode('utf-8'))

        return cot_xml_bytes
