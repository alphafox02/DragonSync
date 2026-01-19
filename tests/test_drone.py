#!/usr/bin/env python3
"""
Unit tests for the Drone class.

Tests cover:
- Initialization with minimal and full parameters
- Update method with position tracking and fallback bearing calculation
- CoT XML generation (drone, pilot, home)
- Dictionary serialization for API
- FAA RID lookup result caching
- Frequency formatting (Hz to MHz conversion)
"""

import pytest
import time
import math
from lxml import etree
from core import Drone


@pytest.fixture
def minimal_drone():
    """Drone with minimal required parameters"""
    return Drone(
        id="drone-TEST001",
        lat=39.7392,
        lon=-104.9903,
        speed=10.0,
        vspeed=1.5,
        alt=1655.5,
        height=50.0,
        pilot_lat=39.7400,
        pilot_lon=-104.9900,
        description="Test Drone",
        mac="AA:BB:CC:DD:EE:FF",
        rssi=-65
    )


@pytest.fixture
def full_drone():
    """Drone with all optional parameters populated"""
    return Drone(
        id="drone-DJI001",
        lat=39.7500,
        lon=-105.0000,
        speed=15.0,
        vspeed=2.0,
        alt=1700.0,
        height=100.0,
        pilot_lat=39.7505,
        pilot_lon=-105.0005,
        description="DJI Mavic",
        mac="60:60:1F:AA:BB:CC",
        rssi=-72,
        home_lat=39.7495,
        home_lon=-104.9995,
        id_type="Serial Number (ANSI/CTA-2063-A)",
        ua_type=2,
        ua_type_name="Helicopter or Multirotor",
        operator_id_type="CAA Assigned Registration ID",
        operator_id="OP-12345",
        op_status="Airborne",
        height_type="Above Takeoff",
        ew_dir="East",
        direction=90.0,
        speed_multiplier=0.25,
        pressure_altitude=1650.0,
        vertical_accuracy="< 3 m",
        horizontal_accuracy="< 10 m",
        baro_accuracy="< 4 m",
        speed_accuracy="< 1 m/s",
        timestamp="3600.5",
        rid_timestamp="3600.5",
        observed_at=time.time(),
        timestamp_accuracy="0.1s",
        index=42,
        runtime=12345,
        caa_id="CAA-REG-001",
        freq=5800000000.0,  # 5.8 GHz in Hz
        seen_by="wardragon-001"
    )


def test_drone_initialization_minimal(minimal_drone):
    """Test that minimal drone initialization works"""
    assert minimal_drone.id == "drone-TEST001"
    assert minimal_drone.lat == 39.7392
    assert minimal_drone.lon == -104.9903
    assert minimal_drone.speed == 10.0
    assert minimal_drone.mac == "AA:BB:CC:DD:EE:FF"
    assert minimal_drone.rssi == -65
    assert minimal_drone.last_sent_time == 0.0
    assert minimal_drone.last_update_time > 0


def test_drone_initialization_full(full_drone):
    """Test that full drone initialization preserves all fields"""
    assert full_drone.id == "drone-DJI001"
    assert full_drone.ua_type == 2
    assert full_drone.ua_type_name == "Helicopter or Multirotor"
    assert full_drone.operator_id == "OP-12345"
    assert full_drone.direction == 90.0
    assert full_drone.freq == 5800000000.0
    assert full_drone.seen_by == "wardragon-001"
    assert full_drone.index == 42
    assert full_drone.runtime == 12345


def test_drone_update_position(minimal_drone):
    """Test that update method correctly updates position and tracks previous position"""
    original_lat = minimal_drone.lat
    original_lon = minimal_drone.lon

    minimal_drone.update(
        lat=39.7400,
        lon=-104.9910,
        speed=12.0,
        vspeed=2.0,
        alt=1660.0,
        height=55.0,
        pilot_lat=39.7410,
        pilot_lon=-104.9915,
        description="Updated Drone",
        mac="AA:BB:CC:DD:EE:FF",
        rssi=-68
    )

    assert minimal_drone.lat == 39.7400
    assert minimal_drone.lon == -104.9910
    assert minimal_drone.prev_lat == original_lat
    assert minimal_drone.prev_lon == original_lon
    assert minimal_drone.speed == 12.0
    assert minimal_drone.rssi == -68


def test_drone_fallback_bearing_calculation(minimal_drone):
    """Test that fallback bearing is calculated from position delta when direction is None"""
    # First update to establish prev_lat/prev_lon
    minimal_drone.update(
        lat=39.7392,
        lon=-104.9903,
        speed=10.0,
        vspeed=1.0,
        alt=1655.0,
        height=50.0,
        pilot_lat=39.7400,
        pilot_lon=-104.9900,
        description="Test",
        mac="AA:BB:CC:DD:EE:FF",
        rssi=-65
    )

    # Second update moves north (expect ~0 degrees)
    minimal_drone.update(
        lat=39.7492,  # +0.01 degrees north
        lon=-104.9903,  # same longitude
        speed=10.0,
        vspeed=1.0,
        alt=1655.0,
        height=50.0,
        pilot_lat=39.7400,
        pilot_lon=-104.9900,
        description="Test",
        mac="AA:BB:CC:DD:EE:FF",
        rssi=-65,
        direction=None  # No direction provided, should calculate
    )

    # Should calculate bearing to north (~0 degrees)
    assert minimal_drone.direction is not None
    assert 0 <= minimal_drone.direction < 10 or 350 <= minimal_drone.direction < 360


def test_drone_update_preserves_rid_data(full_drone):
    """Test that RID lookup data persists across updates"""
    # Apply RID lookup result
    full_drone.apply_rid_lookup_result({
        "found": True,
        "rid_tracking": "FA12345",
        "status": "Active",
        "make": "DJI",
        "model": "Mavic 3",
        "source": "FAA"
    })

    # Update position
    full_drone.update(
        lat=39.7510,
        lon=-105.0010,
        speed=16.0,
        vspeed=2.5,
        alt=1710.0,
        height=110.0,
        pilot_lat=39.7515,
        pilot_lon=-105.0015,
        description="DJI Mavic",
        mac="60:60:1F:AA:BB:CC",
        rssi=-74
    )

    # RID data should still be present
    assert full_drone.rid_make == "DJI"
    assert full_drone.rid_model == "Mavic 3"
    assert full_drone.rid_lookup_success is True


def test_drone_to_cot_xml_structure(minimal_drone):
    """Test that CoT XML has correct structure and required elements"""
    cot_xml = minimal_drone.to_cot_xml()

    # Parse XML
    root = etree.fromstring(cot_xml)

    # Check root element
    assert root.tag == "event"
    assert root.get("version") == "2.0"
    assert root.get("uid") == "drone-TEST001"
    assert root.get("type") is not None  # Should have a CoT type

    # Check point element
    point = root.find("point")
    assert point is not None
    assert point.get("lat") == "39.7392"
    assert point.get("lon") == "-104.9903"
    assert point.get("hae") == "1655.5"

    # Check detail elements
    detail = root.find("detail")
    assert detail is not None

    contact = detail.find("contact")
    assert contact is not None
    assert contact.get("callsign") == "drone-TEST001"

    track = detail.find("track")
    assert track is not None
    assert track.get("speed") is not None
    assert track.get("course") is not None

    remarks = detail.find("remarks")
    assert remarks is not None
    assert "MAC: AA:BB:CC:DD:EE:FF" in remarks.text
    assert "RSSI: -65dBm" in remarks.text


def test_drone_to_cot_xml_with_frequency(full_drone):
    """Test that CoT XML includes frequency when present"""
    cot_xml = full_drone.to_cot_xml()
    root = etree.fromstring(cot_xml)

    remarks = root.find("detail/remarks")
    assert remarks is not None
    # Frequency should be converted to MHz (5800 MHz)
    assert "Freq: ~5800" in remarks.text or "5800.0" in remarks.text


def test_drone_to_pilot_cot_xml(minimal_drone):
    """Test that pilot CoT XML is generated correctly"""
    pilot_xml = minimal_drone.to_pilot_cot_xml()

    root = etree.fromstring(pilot_xml)

    assert root.tag == "event"
    assert root.get("uid") == "pilot-TEST001"  # Strips 'drone-' prefix
    assert root.get("type") == "b-m-p-s-m"

    point = root.find("point")
    assert point.get("lat") == "39.74"
    assert point.get("lon") == "-104.99"

    detail = root.find("detail")
    usericon = detail.find("usericon")
    assert usericon is not None
    assert "Person.png" in usericon.get("iconsetpath")


def test_drone_to_pilot_cot_xml_suppressed_for_alert():
    """Test that pilot CoT is suppressed for 'drone-alert'"""
    alert_drone = Drone(
        id="drone-alert",
        lat=39.7392,
        lon=-104.9903,
        speed=10.0,
        vspeed=1.5,
        alt=1655.5,
        height=50.0,
        pilot_lat=0.0,
        pilot_lon=0.0,
        description="Alert",
        mac="AA:BB:CC:DD:EE:FF",
        rssi=-65
    )

    pilot_xml = alert_drone.to_pilot_cot_xml()
    assert pilot_xml == b""


def test_drone_to_home_cot_xml(full_drone):
    """Test that home CoT XML is generated correctly"""
    home_xml = full_drone.to_home_cot_xml()

    root = etree.fromstring(home_xml)

    assert root.tag == "event"
    assert root.get("uid") == "home-DJI001"
    assert root.get("type") == "b-m-p-s-m"

    point = root.find("point")
    assert point.get("lat") == "39.7495"
    assert point.get("lon") == "-104.9995"

    detail = root.find("detail")
    usericon = detail.find("usericon")
    assert usericon is not None
    assert "House.png" in usericon.get("iconsetpath")


def test_drone_to_home_cot_xml_suppressed_for_alert():
    """Test that home CoT is suppressed for 'drone-alert'"""
    alert_drone = Drone(
        id="drone-alert",
        lat=39.7392,
        lon=-104.9903,
        speed=10.0,
        vspeed=1.5,
        alt=1655.5,
        height=50.0,
        pilot_lat=0.0,
        pilot_lon=0.0,
        description="Alert",
        mac="AA:BB:CC:DD:EE:FF",
        rssi=-65,
        home_lat=0.0,
        home_lon=0.0
    )

    home_xml = alert_drone.to_home_cot_xml()
    assert home_xml == b""


def test_drone_to_dict(full_drone):
    """Test that to_dict() returns complete JSON-safe representation"""
    data = full_drone.to_dict()

    assert data["id"] == "drone-DJI001"
    assert data["lat"] == 39.7500
    assert data["lon"] == -105.0000
    assert data["ua_type"] == 2
    assert data["ua_type_name"] == "Helicopter or Multirotor"
    assert data["operator_id"] == "OP-12345"
    assert data["freq"] == 5800.0  # Converted to MHz
    assert data["seen_by"] == "wardragon-001"
    assert data["track_type"] == "drone"

    # Check nested RID dict
    assert "rid" in data
    assert data["rid"]["lookup_attempted"] is False
    assert data["rid"]["lookup_success"] is False


def test_drone_frequency_formatting_hz_to_mhz():
    """Test that _fmt_freq_mhz converts Hz to MHz correctly"""
    # Test Hz conversion (5.8 GHz = 5800000000 Hz)
    assert Drone._fmt_freq_mhz(5800000000.0) == 5800.0

    # Test already in MHz
    assert Drone._fmt_freq_mhz(5800.0) == 5800.0

    # Test None
    assert Drone._fmt_freq_mhz(None) is None

    # Test NaN/Inf
    assert Drone._fmt_freq_mhz(float('nan')) is None
    assert Drone._fmt_freq_mhz(float('inf')) is None


def test_drone_apply_rid_lookup_result_success(minimal_drone):
    """Test applying successful FAA RID lookup result"""
    lookup_result = {
        "found": True,
        "rid_tracking": "FA98765",
        "status": "Active",
        "make": "Autel",
        "model": "EVO II",
        "source": "FAA"
    }

    minimal_drone.apply_rid_lookup_result(lookup_result)

    assert minimal_drone.rid_lookup_attempted is True
    assert minimal_drone.rid_lookup_success is True
    assert minimal_drone.rid_tracking == "FA98765"
    assert minimal_drone.rid_make == "Autel"
    assert minimal_drone.rid_model == "EVO II"
    assert minimal_drone.rid_source == "FAA"


def test_drone_apply_rid_lookup_result_not_found(minimal_drone):
    """Test applying failed FAA RID lookup result"""
    lookup_result = {
        "found": False
    }

    minimal_drone.apply_rid_lookup_result(lookup_result)

    assert minimal_drone.rid_lookup_attempted is True
    assert minimal_drone.rid_lookup_success is False
    assert minimal_drone.rid_make is None
    assert minimal_drone.rid_model is None


def test_drone_ua_type_cot_mapping():
    """Test that different UA types map to correct CoT types"""
    from core.drone import UA_COT_TYPE_MAP

    # Fixed wing should map to 'a-f-A-f'
    assert UA_COT_TYPE_MAP[1] == 'a-f-A-f'

    # Helicopter/multirotor should map to 'a-u-A-M-H-R'
    assert UA_COT_TYPE_MAP[2] == 'a-u-A-M-H-R'

    # Create drones with different UA types
    fixed_wing = Drone(
        id="drone-FIXED",
        lat=39.7392,
        lon=-104.9903,
        speed=30.0,
        vspeed=0.0,
        alt=1655.5,
        height=50.0,
        pilot_lat=39.7400,
        pilot_lon=-104.9900,
        description="Fixed Wing",
        mac="AA:BB:CC:DD:EE:FF",
        rssi=-65,
        ua_type=1
    )

    cot_xml = fixed_wing.to_cot_xml()
    root = etree.fromstring(cot_xml)
    assert root.get("type") == "a-f-A-f"


def test_drone_timestamp_fields(full_drone):
    """Test that timestamp fields are preserved correctly"""
    assert full_drone.timestamp == "3600.5"
    assert full_drone.rid_timestamp == "3600.5"
    assert full_drone.timestamp_accuracy == "0.1s"

    # Test in to_dict output
    data = full_drone.to_dict()
    assert data["timestamp"] == "3600.5"
    assert data["rid_timestamp"] == "3600.5"
    assert data["timestamp_accuracy"] == "0.1s"


def test_drone_update_with_none_direction_no_previous_position(minimal_drone):
    """Test that direction=None with no previous position doesn't crash"""
    # Fresh drone has no prev_lat/prev_lon
    new_drone = Drone(
        id="drone-NEW",
        lat=39.7392,
        lon=-104.9903,
        speed=10.0,
        vspeed=1.5,
        alt=1655.5,
        height=50.0,
        pilot_lat=39.7400,
        pilot_lon=-104.9900,
        description="Test",
        mac="AA:BB:CC:DD:EE:FF",
        rssi=-65
    )

    # Update with direction=None should not crash
    new_drone.update(
        lat=39.7400,
        lon=-104.9910,
        speed=12.0,
        vspeed=2.0,
        alt=1660.0,
        height=55.0,
        pilot_lat=39.7410,
        pilot_lon=-104.9915,
        description="Updated",
        mac="AA:BB:CC:DD:EE:FF",
        rssi=-68,
        direction=None
    )

    # Should have calculated a direction now
    assert new_drone.direction is not None
