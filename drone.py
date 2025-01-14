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

class Drone:
    """Represents a drone and its telemetry data."""

    def __init__(self, id: str, lat: float, lon: float, speed: float, vspeed: float,
                 alt: float, height: float, pilot_lat: float, pilot_lon: float, description: str, mac: str, rssi: int):
        self.id = id
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
        self.description = description
        self.last_update_time = time.time()
        self.last_sent_time = 0.0  # Track last time an update was sent

    def update(self, lat: float, lon: float, speed: float, vspeed: float, alt: float,
               height: float, pilot_lat: float, pilot_lon: float, description: str, mac: str, rssi: int):
        """Updates the drone's telemetry data."""
        self.lat = lat
        self.lon = lon
        self.speed = speed
        self.vspeed = vspeed
        self.alt = alt
        self.height = height
        self.pilot_lat = pilot_lat
        self.pilot_lon = pilot_lon
        self.description = description
        self.last_update_time = time.time()
        self.mac = mac
        self.rssi = rssi

    def to_cot_xml(self, stale_offset: Optional[float] = None) -> bytes:
        """Converts the drone's telemetry data to a Cursor-on-Target (CoT) XML message."""
        current_time = datetime.datetime.utcnow()
        if stale_offset is not None:
            stale_time = current_time + datetime.timedelta(seconds=stale_offset)
        else:
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

        remarks_text = (
            f"MAC: {self.mac}, RSSI: {self.rssi}dBm, "
            f"Self-ID: {self.description}, "
            f"Location/Vector: [Speed: {self.speed} m/s, Vert Speed: {self.vspeed} m/s, "
            f"Geodetic Altitude: {self.alt} m, Height AGL: {self.height} m], "
            f"System: [Operator Lat: {self.pilot_lat}, Operator Lon: {self.pilot_lon}]"
        )
        remarks_text = xml.sax.saxutils.escape(remarks_text)
        etree.SubElement(detail, 'remarks').text = remarks_text

        etree.SubElement(detail, 'color', argb='-256')

        etree.SubElement(
            detail,
            'usericon',
            iconsetpath='34ae1613-9645-4222-a9d2-e5f243dea2865/Military/UAV_quad.png'
        )

        return etree.tostring(event, pretty_print=True, xml_declaration=True, encoding='UTF-8')
