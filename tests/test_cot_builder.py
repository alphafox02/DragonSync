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

Tests for centralized CoT XML generation (cot_builder.py).
"""

import pytest
from lxml import etree
from utils.cot_builder import (
    build_drone_cot,
    build_pilot_cot,
    build_home_cot,
    build_adsb_cot,
    build_signal_cot,
    build_system_status_cot,
    utc_now_iso,
    utc_future_iso,
)


class MockDrone:
    """Mock drone object for testing."""
    def __init__(self):
        self.id = "drone-test123"
        self.lat = 40.7128
        self.lon = -74.0060
        self.alt = 100.0
        self.speed = 5.0
        self.vspeed = 1.0
        self.height = 50.0
        self.direction = 90.0
        self.mac = "AA:BB:CC:DD:EE:FF"
        self.rssi = -60
        self.freq = 5800e6  # 5800 MHz in Hz
        self.id_type = 1
        self.ua_type = 1
        self.ua_type_name = "Helicopter"
        self.operator_id_type = "Serial"
        self.operator_id = "TEST123"
        self.index = 0
        self.runtime = 300
        self.rid_make = "DJI"
        self.rid_model = "Mavic 3"
        self.rid_source = "FAA"
        self.seen_by = "WarDragon-001"
        self.observed_at = 1704067200.0
        self.rid_timestamp = "2024-01-01T00:00:00Z"
        self.pilot_lat = 40.7100
        self.pilot_lon = -74.0050
        self.home_lat = 40.7110
        self.home_lon = -74.0055
        self.cot_type = 'a-u-A-M-H-R'


class MockSystemStatus:
    """Mock system status object for testing."""
    def __init__(self):
        self.id = "wardragon-001"
        self.lat = 40.7128
        self.lon = -74.0060
        self.alt = 10.0
        self.cpu_usage = 45.5
        self.memory_total = 4096.0
        self.memory_available = 2048.0
        self.disk_total = 64000.0
        self.disk_used = 32000.0
        self.temperature = 55.0
        self.uptime = 3600
        self.pluto_temp = 45.0
        self.zynq_temp = 50.0
        self.track = 180.0
        self.speed = 15.5
        self.time_source = "GPS"
        self.gps_fix = True
        self.gpsd_time_utc = "2024-01-01T12:00:00Z"


def test_utc_now_iso():
    """Test UTC timestamp formatting."""
    timestamp = utc_now_iso()
    assert isinstance(timestamp, str)
    assert 'T' in timestamp
    assert 'Z' in timestamp
    # Basic ISO format check
    assert len(timestamp) >= 20


def test_utc_future_iso():
    """Test future UTC timestamp calculation."""
    future = utc_future_iso(60.0)
    assert isinstance(future, str)
    assert 'T' in future
    assert 'Z' in future


def test_build_drone_cot():
    """Test drone CoT XML generation."""
    drone = MockDrone()
    xml_bytes = build_drone_cot(drone, stale_offset=120.0)

    assert isinstance(xml_bytes, bytes)
    assert xml_bytes.startswith(b'<?xml')

    # Parse and validate structure
    root = etree.fromstring(xml_bytes)
    assert root.tag == 'event'
    assert root.get('uid') == 'drone-test123'
    assert root.get('type') == 'a-u-A-M-H-R'

    # Check point
    point = root.find('point')
    assert point is not None
    assert point.get('lat') == '40.7128'
    assert point.get('lon') == '-74.006'

    # Check detail elements
    detail = root.find('detail')
    assert detail is not None

    contact = detail.find('contact')
    assert contact is not None
    assert contact.get('callsign') == 'drone-test123'

    track = detail.find('track')
    assert track is not None
    assert track.get('course') == '90.0'
    assert track.get('speed') == '5.0'

    remarks = detail.find('remarks')
    assert remarks is not None
    assert 'MAC: AA:BB:CC:DD:EE:FF' in remarks.text
    assert 'RSSI: -60dBm' in remarks.text
    assert 'Freq: ~5800.0 MHz' in remarks.text
    assert 'RID: DJI Mavic 3' in remarks.text
    assert 'SeenBy: WarDragon-001' in remarks.text

    # Check RID block
    rid = detail.find('rid')
    assert rid is not None
    assert rid.get('make') == 'DJI'
    assert rid.get('model') == 'Mavic 3'
    assert rid.get('source') == 'FAA'


def test_build_pilot_cot():
    """Test pilot location CoT XML generation."""
    drone = MockDrone()
    xml_bytes = build_pilot_cot(drone, stale_offset=120.0)

    assert isinstance(xml_bytes, bytes)
    assert xml_bytes.startswith(b'<?xml')

    root = etree.fromstring(xml_bytes)
    assert root.tag == 'event'
    assert root.get('uid') == 'pilot-test123'
    assert root.get('type') == 'b-m-p-s-m'

    point = root.find('point')
    assert point is not None
    assert point.get('lat') == str(drone.pilot_lat)
    assert point.get('lon') == str(drone.pilot_lon)

    detail = root.find('detail')
    usericon = detail.find('usericon')
    assert usericon is not None
    assert 'Person.png' in usericon.get('iconsetpath')

    remarks = detail.find('remarks')
    assert 'Pilot location for drone' in remarks.text


def test_build_pilot_cot_no_location():
    """Test pilot CoT skips when no location."""
    drone = MockDrone()
    drone.pilot_lat = 0.0
    drone.pilot_lon = 0.0
    xml_bytes = build_pilot_cot(drone, stale_offset=120.0)
    assert xml_bytes == b''


def test_build_pilot_cot_alert_suppressed():
    """Test pilot CoT suppressed for drone-alert."""
    drone = MockDrone()
    drone.id = "drone-alert"
    xml_bytes = build_pilot_cot(drone, stale_offset=120.0)
    assert xml_bytes == b''


def test_build_home_cot():
    """Test home location CoT XML generation."""
    drone = MockDrone()
    xml_bytes = build_home_cot(drone, stale_offset=120.0)

    assert isinstance(xml_bytes, bytes)
    assert xml_bytes.startswith(b'<?xml')

    root = etree.fromstring(xml_bytes)
    assert root.tag == 'event'
    assert root.get('uid') == 'home-test123'
    assert root.get('type') == 'b-m-p-s-m'

    point = root.find('point')
    assert point is not None
    assert point.get('lat') == str(drone.home_lat)
    assert point.get('lon') == str(drone.home_lon)

    detail = root.find('detail')
    usericon = detail.find('usericon')
    assert usericon is not None
    assert 'House.png' in usericon.get('iconsetpath')

    remarks = detail.find('remarks')
    assert 'Home location for drone' in remarks.text


def test_build_home_cot_no_location():
    """Test home CoT skips when no location."""
    drone = MockDrone()
    drone.home_lat = 0.0
    drone.home_lon = 0.0
    xml_bytes = build_home_cot(drone, stale_offset=120.0)
    assert xml_bytes == b''


def test_build_adsb_cot():
    """Test ADS-B aircraft CoT XML generation."""
    craft = {
        'hex': 'A12345',
        'flight': 'UAL123',
        'lat': 40.7128,
        'lon': -74.0060,
        'alt_baro': 35000,
        'gs': 450,
        'track': 270,
        'squawk': '1200',
        'reg': 'N12345',
        'category': 'A3',
        'onground': False,
        'nac_p': 9,
        'nac_v': 2,
    }
    uid = 'adsb-A12345'
    xml_bytes = build_adsb_cot(craft, uid, 'WarDragon-001', 60.0)

    assert isinstance(xml_bytes, bytes)
    assert xml_bytes.startswith(b'<?xml')

    root = etree.fromstring(xml_bytes)
    assert root.tag == 'event'
    assert root.get('uid') == 'adsb-A12345'
    assert root.get('type') == 'a-f-A'

    point = root.find('point')
    assert point is not None

    detail = root.find('detail')
    track = detail.find('track')
    assert track is not None
    assert track.get('course') == '270.0'
    assert track.get('speed') == '450.0'

    remarks = detail.find('remarks')
    assert 'ADS-B' in remarks.text
    assert 'hex=A12345' in remarks.text
    assert 'squawk=1200' in remarks.text
    assert 'reg=N12345' in remarks.text
    assert 'SeenBy: WarDragon-001' in remarks.text


def test_build_adsb_cot_no_location():
    """Test ADS-B CoT skips when no location."""
    craft = {'hex': 'A12345'}  # Missing lat/lon
    xml_bytes = build_adsb_cot(craft, 'adsb-A12345', None, 60.0)
    assert xml_bytes == b''


def test_build_adsb_cot_on_ground():
    """Test ADS-B CoT with onground flag."""
    craft = {
        'hex': 'A12345',
        'lat': 40.7128,
        'lon': -74.0060,
        'alt_baro': 0,
        'gs': 0,
        'track': 0,
        'onground': True,
    }
    xml_bytes = build_adsb_cot(craft, 'adsb-A12345', None, 60.0)

    root = etree.fromstring(xml_bytes)
    detail = root.find('detail')
    track = detail.find('track')
    assert track.get('slope') == '0'

    remarks = detail.find('remarks')
    assert 'onground=1' in remarks.text


def test_build_signal_cot():
    """Test FPV signal detection CoT XML generation."""
    alert = {
        'uid': 'fpv-5800MHz',
        'signal_type': 'analog_video',
        'source': 'sdr',
        'center_hz': 5800000000,
        'bandwidth_hz': 20000000,
        'pal_conf': 0.85,
        'ntsc_conf': 0.15,
        'callsign': 'FPV 5800MHz',
    }
    xml_bytes = build_signal_cot(alert, 40.7128, -74.0060, 10.0, 60.0, 15.0, 'WarDragon-001')

    assert isinstance(xml_bytes, bytes)
    assert xml_bytes.startswith(b'<?xml')

    root = etree.fromstring(xml_bytes)
    assert root.tag == 'event'
    assert root.get('uid') == 'fpv-5800MHz'
    assert root.get('type') == 'b-m-p-s-s'

    point = root.find('point')
    assert point is not None
    assert point.get('ce') == '15.0'  # radius_m

    detail = root.find('detail')
    contact = detail.find('contact')
    assert contact.get('callsign') == 'FPV 5800MHz'

    remarks = detail.find('remarks')
    assert 'signal=analog_video' in remarks.text
    assert 'source=sdr' in remarks.text
    assert 'center_hz=5800000000' in remarks.text
    assert 'bandwidth_hz=20000000' in remarks.text
    assert 'pal=0.85' in remarks.text
    assert 'ntsc=0.15' in remarks.text
    assert 'SeenBy: WarDragon-001' in remarks.text


def test_build_system_status_cot():
    """Test system status CoT XML generation."""
    status = MockSystemStatus()
    xml_bytes = build_system_status_cot(status, stale_seconds=600.0)

    assert isinstance(xml_bytes, bytes)
    assert xml_bytes.startswith(b'<?xml')

    root = etree.fromstring(xml_bytes)
    assert root.tag == 'event'
    assert root.get('uid') == 'wardragon-001'
    assert root.get('type') == 'a-f-G-E-S'

    point = root.find('point')
    assert point is not None

    detail = root.find('detail')
    contact = detail.find('contact')
    assert contact.get('callsign') == 'wardragon-001'

    remarks = detail.find('remarks')
    assert 'CPU Usage: 45.5%' in remarks.text
    assert 'Memory Total: 4096.00 MB' in remarks.text
    assert 'Pluto Temp: 45.0°C' in remarks.text
    assert 'Zynq Temp: 50.0°C' in remarks.text
    assert 'TimeSource: GPS' in remarks.text
    assert 'GPS Fix: true' in remarks.text

    track = detail.find('track')
    assert track is not None
    assert track.get('course') == '180.0'
    assert track.get('speed') == '15.50'


def test_drone_alert_special_handling():
    """Test drone-alert gets special remarks."""
    drone = MockDrone()
    drone.id = "drone-alert"
    xml_bytes = build_drone_cot(drone, stale_offset=120.0)

    root = etree.fromstring(xml_bytes)
    detail = root.find('detail')
    remarks = detail.find('remarks')
    assert 'Alert: Unknown DJI OcuSync format' in remarks.text


def test_drone_with_minimal_data():
    """Test drone CoT with minimal data (no RID, etc.)."""
    drone = MockDrone()
    drone.rid_make = None
    drone.rid_model = None
    drone.rid_source = None
    drone.seen_by = None
    drone.observed_at = None

    xml_bytes = build_drone_cot(drone, stale_offset=120.0)

    root = etree.fromstring(xml_bytes)
    assert root.tag == 'event'

    # Should still generate valid XML
    detail = root.find('detail')
    remarks = detail.find('remarks')
    assert remarks is not None


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
