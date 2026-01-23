#!/usr/bin/env python3
"""
Integration tests for DragonSync using test scenario system.

These tests verify end-to-end functionality with simulated drone data.
"""

import pytest
import json
import time
from pathlib import Path
from unittest.mock import Mock, patch

# Import the main module to verify refactoring didn't break anything
import dragonsync
from dragonsync import _build_drone_update_kwargs, UA_TYPE_MAPPING
from core import parse_drone_info, Drone, DroneManager


def test_helper_function_exists():
    """Verify the new helper function exists and is callable"""
    assert callable(_build_drone_update_kwargs)


def test_helper_function_returns_complete_kwargs():
    """Verify helper function returns all expected parameters"""
    test_info = {
        'id': 'TEST001',
        'lat': 39.7392,
        'lon': -104.9903,
        'speed': 10.0,
        'vspeed': 1.5,
        'alt': 1655.5,
        'height': 50.0,
        'pilot_lat': 39.7400,
        'pilot_lon': -104.9900,
        'description': 'Test Drone',
        'mac': 'AA:BB:CC:DD:EE:FF',
        'rssi': -65,
        'ua_type': 2,
        'freq': 5800000000.0
    }

    kwargs = _build_drone_update_kwargs(test_info, 'test-kit')

    # Verify critical fields are present
    assert 'lat' in kwargs
    assert 'lon' in kwargs
    assert 'speed' in kwargs
    assert 'mac' in kwargs
    assert 'freq' in kwargs
    assert 'seen_by' in kwargs

    # Verify values are correct
    assert kwargs['lat'] == 39.7392
    assert kwargs['lon'] == -104.9903
    assert kwargs['freq'] == 5800000000.0
    assert kwargs['seen_by'] == 'test-kit'


def test_helper_function_with_minimal_data():
    """Verify helper function handles minimal data with defaults"""
    minimal_info = {
        'lat': 39.7392,
        'lon': -104.9903,
    }

    kwargs = _build_drone_update_kwargs(minimal_info, 'test-kit')

    # Should have defaults for missing fields
    assert kwargs['speed'] == 0.0
    assert kwargs['alt'] == 0.0
    assert kwargs['description'] == ""
    assert kwargs['rssi'] == 0


def test_end_to_end_parser_to_drone():
    """Integration test: Parse telemetry → Create drone with helper"""
    # Simulate a DJI message
    message = [
        {
            "Basic ID": {
                "id_type": "Serial Number (ANSI/CTA-2063-A)",
                "id": "DJI0001234567890",
                "ua_type": 2,
                "MAC": "60:60:1F:AA:BB:CC",
                "RSSI": -72
            }
        },
        {
            "Location/Vector Message": {
                "latitude": 39.7500,
                "longitude": -105.0000,
                "speed": 15.0,
                "vert_speed": 1.5,
                "geodetic_altitude": 1700.0,
                "height_agl": 100.0
            }
        },
        {
            "Frequency Message": {
                "frequency": 5800000000
            }
        }
    ]

    # Parse telemetry
    drone_info = parse_drone_info(message, UA_TYPE_MAPPING)
    assert drone_info is not None
    assert drone_info['id'] == 'DJI0001234567890'
    assert drone_info['freq'] == 5800000000.0

    # Create drone using helper (as dragonsync.py does)
    drone = Drone(
        id=f"drone-{drone_info['id']}",
        **_build_drone_update_kwargs(drone_info, 'test-kit')
    )

    # Verify drone was created correctly
    assert drone.id == "drone-DJI0001234567890"
    assert drone.lat == 39.7500
    assert drone.lon == -105.0000
    assert drone.freq == 5800000000.0
    assert drone.seen_by == 'test-kit'


def test_end_to_end_parser_to_manager():
    """Integration test: Parse telemetry → Manager → Update drone"""
    manager = DroneManager(max_drones=10, rate_limit=1.0, inactivity_timeout=60.0)

    # First message - create drone
    message1 = [
        {"Basic ID": {"id": "TEST001", "id_type": "Serial Number (ANSI/CTA-2063-A)", "MAC": "AA:BB:CC:DD:EE:FF", "RSSI": -65}},
        {"Location/Vector Message": {"latitude": 39.7392, "longitude": -104.9903, "speed": 10.0, "vert_speed": 1.5, "geodetic_altitude": 1655.5, "height_agl": 50.0}}
    ]

    drone_info = parse_drone_info(message1, UA_TYPE_MAPPING)
    drone = Drone(id=f"drone-{drone_info['id']}", **_build_drone_update_kwargs(drone_info, 'test-kit'))
    manager.update_or_add_drone("drone-TEST001", drone)

    assert len(manager.drone_dict) == 1
    assert manager.drone_dict["drone-TEST001"].lat == 39.7392

    # Second message - update existing drone
    message2 = [
        {"Basic ID": {"id": "TEST001", "id_type": "Serial Number (ANSI/CTA-2063-A)", "MAC": "AA:BB:CC:DD:EE:FF", "RSSI": -68}},
        {"Location/Vector Message": {"latitude": 39.7400, "longitude": -104.9910, "speed": 12.0, "vert_speed": 2.0, "geodetic_altitude": 1660.0, "height_agl": 55.0}}
    ]

    drone_info2 = parse_drone_info(message2, UA_TYPE_MAPPING)
    updated_drone = Drone(id=f"drone-{drone_info2['id']}", **_build_drone_update_kwargs(drone_info2, 'test-kit'))
    manager.update_or_add_drone("drone-TEST001", updated_drone)

    # Should still be 1 drone (updated, not added)
    assert len(manager.drone_dict) == 1
    # Position should be updated
    assert manager.drone_dict["drone-TEST001"].lat == 39.7400


def test_scenario_file_parsing():
    """Verify test scenario files can be parsed"""
    scenario_path = Path(__file__).parent / "test_refactor_scenario.json"

    if not scenario_path.exists():
        pytest.skip("Test scenario not generated yet")

    with open(scenario_path) as f:
        scenario = json.load(f)

    # Verify scenario structure
    assert "scenarios" in scenario
    assert "animated_tracks" in scenario["scenarios"]
    assert len(scenario["scenarios"]["animated_tracks"]) > 0

    # Verify drone structure
    for drone_data in scenario["scenarios"]["animated_tracks"]:
        assert "name" in drone_data
        assert "drone_config" in drone_data
        assert "flight_path" in drone_data


def test_refactoring_preserves_behavior():
    """Verify refactored code produces same results as before"""
    # This test verifies the helper function produces identical output
    # to the old manual parameter passing

    test_data = {
        'lat': 39.7392, 'lon': -104.9903,
        'speed': 10.0, 'vspeed': 1.5,
        'alt': 1655.5, 'height': 50.0,
        'pilot_lat': 39.7400, 'pilot_lon': -104.9900,
        'home_lat': 39.7380, 'home_lon': -104.9890,
        'description': 'Test', 'mac': 'AA:BB:CC', 'rssi': -65,
        'id_type': 'Serial Number (ANSI/CTA-2063-A)',
        'ua_type': 2, 'ua_type_name': 'Helicopter or Multirotor',
        'freq': 5800000000.0, 'index': 42, 'runtime': 12345
    }

    kwargs = _build_drone_update_kwargs(test_data, 'test-kit')

    # Create drone with helper function
    drone_new = Drone(id='drone-TEST', **kwargs)

    # Create drone with manual parameters (old way)
    drone_old = Drone(
        id='drone-TEST',
        lat=test_data.get('lat', 0.0),
        lon=test_data.get('lon', 0.0),
        speed=test_data.get('speed', 0.0),
        vspeed=test_data.get('vspeed', 0.0),
        alt=test_data.get('alt', 0.0),
        height=test_data.get('height', 0.0),
        pilot_lat=test_data.get('pilot_lat', 0.0),
        pilot_lon=test_data.get('pilot_lon', 0.0),
        description=test_data.get('description', ""),
        mac=test_data.get('mac', ""),
        rssi=test_data.get('rssi', 0),
        home_lat=test_data.get('home_lat', 0.0),
        home_lon=test_data.get('home_lon', 0.0),
        id_type=test_data.get('id_type', ""),
        ua_type=test_data.get('ua_type'),
        ua_type_name=test_data.get('ua_type_name', ""),
        freq=test_data.get('freq'),
        seen_by='test-kit'
    )

    # Verify both produce identical results
    assert drone_new.lat == drone_old.lat
    assert drone_new.lon == drone_old.lon
    assert drone_new.speed == drone_old.speed
    assert drone_new.freq == drone_old.freq
    assert drone_new.seen_by == drone_old.seen_by
    assert drone_new.ua_type == drone_old.ua_type


def test_caa_only_path_uses_helper():
    """Verify CAA-only code path also uses the helper function correctly"""
    # This simulates the MAC-match update path (lines 692 in dragonsync.py)
    manager = DroneManager(max_drones=10, rate_limit=1.0, inactivity_timeout=60.0)

    # Add initial drone with MAC
    initial_data = {
        'id': 'TEST001',
        'lat': 39.7392, 'lon': -104.9903,
        'speed': 10.0, 'vspeed': 1.5,
        'alt': 1655.5, 'height': 50.0,
        'pilot_lat': 39.7400, 'pilot_lon': -104.9900,
        'description': 'Test', 'mac': 'AA:BB:CC:DD:EE:FF', 'rssi': -65
    }

    drone = Drone(id='drone-TEST001', **_build_drone_update_kwargs(initial_data, 'test-kit'))
    manager.update_or_add_drone('drone-TEST001', drone)

    # Now simulate CAA-only update (no serial, just MAC match)
    caa_update = {
        'lat': 39.7400, 'lon': -104.9910,  # Updated position
        'speed': 12.0, 'vspeed': 2.0,
        'alt': 1660.0, 'height': 55.0,
        'pilot_lat': 39.7410, 'pilot_lon': -104.9915,
        'description': 'Test', 'mac': 'AA:BB:CC:DD:EE:FF', 'rssi': -68,
        'caa': 'CAA-XYZ'
    }

    # Update using helper (as dragonsync.py does in MAC-match path)
    drone.update(**_build_drone_update_kwargs(caa_update, 'test-kit'))

    # Verify update worked
    assert drone.lat == 39.7400
    assert drone.lon == -104.9910
    assert drone.caa_id == 'CAA-XYZ'
