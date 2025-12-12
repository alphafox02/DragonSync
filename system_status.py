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
        track: float = 0.0,
        gps_fix: bool = False,
        time_source: str = "",
        gpsd_time_utc: str = "",
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
        self.gps_fix = gps_fix
        self.time_source = time_source
        self.gpsd_time_utc = gpsd_time_utc
        
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
        if self.time_source:
            remarks_text += f"; TimeSource: {self.time_source}"
        if self.gps_fix:
            remarks_text += "; GPS Fix: true"
        if self.gpsd_time_utc:
            remarks_text += f"; GPSD UTC: {self.gpsd_time_utc}"
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
