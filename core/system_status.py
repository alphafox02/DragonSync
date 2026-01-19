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

    def to_dict(self):
        return {
            "uid": self.id,
            "lat": self.lat,
            "lon": self.lon,
            "alt": self.alt,
            "cpu_usage": self.cpu_usage,
            "memory_total": self.memory_total,
            "memory_available": self.memory_available,
            "disk_total": self.disk_total,
            "disk_used": self.disk_used,
            "temperature": self.temperature,
            "uptime": self.uptime,
            "pluto_temp": self.pluto_temp,
            "zynq_temp": self.zynq_temp,
            "speed": self.speed,
            "track": self.track,
            "gps_fix": self.gps_fix,
            "time_source": self.time_source,
            "gpsd_time_utc": self.gpsd_time_utc,
            "last_update_time": self.last_update_time,
        }
        
    def to_cot_xml(self) -> bytes:
        """Converts the system status data to a CoT XML message, embedding provided speed & track."""
        from utils.cot_builder import build_system_status_cot

        cot_xml_bytes = build_system_status_cot(self, stale_seconds=600.0)
        logger.debug("SystemStatus CoT XML for '%s':\n%s", self.id, cot_xml_bytes.decode('utf-8'))
        return cot_xml_bytes
