#!/usr/bin/env python3
"""
Shared pytest fixtures for DragonSync tests.

These fixtures provide sample data matching the formats received from:
- DroneID (BLE/WiFi Remote ID) → list format
- antsdr_dji_droneid → list format with Frequency Message
- ESP32 → dict format
"""

import pytest
from typing import Dict


@pytest.fixture
def ua_type_mapping():
    """Standard UA type mapping used throughout DragonSync"""
    return {
        0: 'Unknown',
        1: 'Aeroplane',
        2: 'Helicopter (or Multirotor)',
        3: 'Gyroplane',
        4: 'Hybrid Lift',
        5: 'Ornithopter',
        6: 'Glider',
        7: 'Kite',
        8: 'Free Balloon',
        9: 'Captive Balloon',
        10: 'Airship',
        11: 'Free Fall/Parachute',
        12: 'Rocket',
        13: 'Tethered Powered Aircraft',
        14: 'Ground Obstacle',
        15: 'Other'
    }


@pytest.fixture
def sample_droneid_message():
    """
    Sample Remote ID message from DroneID (BLE/WiFi).
    List format with Basic ID, Location, System, Self-ID messages.
    """
    return [
        {
            "Basic ID": {
                "id_type": "Serial Number (ANSI/CTA-2063-A)",
                "ua_type": 2,
                "id": "1234567890ABCDEF",
                "MAC": "AA:BB:CC:DD:EE:FF",
                "RSSI": -65
            }
        },
        {
            "Location/Vector Message": {
                "latitude": 39.7392,
                "longitude": -104.9903,
                "geodetic_altitude": 1655.5,
                "height_agl": 50.0,
                "speed": 12.5,
                "vert_speed": 2.0,
                "direction": 180,
                "height_type": "Above Takeoff",
                "op_status": "Airborne",
                "ew_dir_segment": "East",
                "speed_multiplier": "0.25",
                "pressure_altitude": "1650.0 m",
                "horizontal_accuracy": "< 10 m",
                "vertical_accuracy": "< 3 m",
                "baro_accuracy": "< 4 m",
                "speed_accuracy": "< 1 m/s",
                "timestamp": "3600.5",
                "timestamp_accuracy": "0.1s"
            }
        },
        {
            "System Message": {
                "latitude": 39.7400,
                "longitude": -104.9900,
                "home_lat": 39.7395,
                "home_lon": -104.9898
            }
        },
        {
            "Self-ID Message": {
                "text": "Test Drone Alpha"
            }
        }
    ]


@pytest.fixture
def sample_dji_message():
    """
    Sample DJI OcuSync message from antsdr_dji_droneid.
    List format with Frequency Message (DJI-specific).
    """
    return [
        {
            "Basic ID": {
                "id_type": "Serial Number (ANSI/CTA-2063-A)",
                "ua_type": 2,
                "id": "DJI0001234567890",
                "MAC": "60:60:1F:AA:BB:CC",
                "RSSI": -72
            }
        },
        {
            "Location/Vector Message": {
                "latitude": 39.7500,
                "longitude": -105.0000,
                "geodetic_altitude": 1700.0,
                "height_agl": 100.0,
                "speed": 15.0,
                "vert_speed": 1.5,
                "direction": 90,
                "height_type": "Above Takeoff",
                "op_status": "Airborne",
                "timestamp": "3602.0"
            }
        },
        {
            "Frequency Message": {
                "frequency": 5800000000  # 5.8 GHz
            }
        },
        {
            "Self-ID Message": {
                "text": "DJI Mavic"
            }
        }
    ]


@pytest.fixture
def sample_esp32_message():
    """
    Sample WiFi Remote ID message from ESP32.
    Dict format with AUX_ADV_IND and aext fields.
    """
    return {
        "index": 42,
        "runtime": 12345,
        "AUX_ADV_IND": {
            "rssi": -68
        },
        "aext": {
            "AdvA": "AA:BB:CC:DD:EE:FF 12:34:56:78:90:AB"
        },
        "Basic ID": {
            "id_type": "Serial Number (ANSI/CTA-2063-A)",
            "ua_type": 2,
            "id": "ESP32TESTDRONE01",
            "MAC": "AA:BB:CC:DD:EE:FF",
            "RSSI": -68
        },
        "Location/Vector Message": {
            "latitude": 39.7600,
            "longitude": -105.0100,
            "geodetic_altitude": 1720.0,
            "height_agl": 75.0,
            "speed": 10.0,
            "vert_speed": 0.5,
            "direction": 270,
            "height_type": "Above Takeoff",
            "op_status": "Airborne",
            "timestamp": "3605.0"
        },
        "Operator ID Message": {
            "operator_id_type": "CAA Assigned Registration ID",
            "operator_id": "OP-12345"
        },
        "System Message": {
            "operator_lat": 39.7605,
            "operator_lon": -105.0105
        },
        "Self-ID Message": {
            "text": "ESP32 Test Drone"
        }
    }


@pytest.fixture
def sample_caa_message():
    """
    Sample with CAA Assigned Registration ID instead of serial number.
    """
    return [
        {
            "Basic ID": {
                "id_type": "CAA Assigned Registration ID",
                "ua_type": 2,
                "id": "CAA-REG-12345",
                "MAC": "11:22:33:44:55:66",
                "RSSI": -70
            }
        },
        {
            "Location/Vector Message": {
                "latitude": 39.7700,
                "longitude": -105.0200,
                "geodetic_altitude": 1750.0,
                "height_agl": 80.0,
                "speed": 8.0,
                "vert_speed": -0.5,
                "direction": 45
            }
        }
    ]


@pytest.fixture
def sample_minimal_message():
    """
    Minimal valid message (only Basic ID and Location).
    Tests that parser handles sparse data gracefully.
    """
    return [
        {
            "Basic ID": {
                "id": "MINIMAL001"
            }
        },
        {
            "Location/Vector Message": {
                "latitude": 39.7800,
                "longitude": -105.0300
            }
        }
    ]
