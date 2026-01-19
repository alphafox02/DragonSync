#!/usr/bin/env python3
"""
Unit tests for the DroneManager class.

Tests cover:
- Drone addition and removal (FIFO queue behavior)
- Update existing drone
- Rate limiting for CoT sends
- Inactivity timeout and cleanup
- Sink dispatching (MQTT, Lattice, etc.)
- Track export for API
"""

import pytest
import time
from unittest.mock import Mock, MagicMock, call
from collections import deque

from drone import Drone
from manager import DroneManager


@pytest.fixture
def mock_cot_messenger():
    """Mock CotMessenger for testing"""
    messenger = Mock()
    messenger.send_cot = Mock()
    return messenger


@pytest.fixture
def mock_sink():
    """Mock sink (MQTT/Lattice/etc.) for testing"""
    sink = Mock()
    sink.publish_drone = Mock()
    sink.publish_pilot = Mock()
    sink.publish_home = Mock()
    sink.mark_inactive = Mock()
    sink.close = Mock()
    return sink


@pytest.fixture
def manager(mock_cot_messenger):
    """DroneManager with default settings"""
    return DroneManager(
        max_drones=10,
        rate_limit=1.0,
        inactivity_timeout=60.0,
        cot_messenger=mock_cot_messenger
    )


@pytest.fixture
def manager_with_sink(mock_cot_messenger, mock_sink):
    """DroneManager with a sink attached"""
    return DroneManager(
        max_drones=10,
        rate_limit=1.0,
        inactivity_timeout=60.0,
        cot_messenger=mock_cot_messenger,
        extra_sinks=[mock_sink]
    )


@pytest.fixture
def sample_drone():
    """Create a sample drone for testing"""
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


def test_manager_initialization():
    """Test that DroneManager initializes correctly"""
    manager = DroneManager(
        max_drones=30,
        rate_limit=2.0,
        inactivity_timeout=120.0
    )

    assert manager.rate_limit == 2.0
    assert manager.inactivity_timeout == 120.0
    assert manager.drones.maxlen == 30
    assert len(manager.drone_dict) == 0
    assert len(manager.extra_sinks) == 0


def test_manager_add_new_drone(manager, sample_drone):
    """Test adding a new drone to the manager"""
    drone_id = "drone-TEST001"

    manager.update_or_add_drone(drone_id, sample_drone)

    assert drone_id in manager.drone_dict
    assert drone_id in manager.drones
    assert len(manager.drone_dict) == 1
    assert manager.drone_dict[drone_id] == sample_drone
    assert sample_drone.last_sent_time == 0.0


def test_manager_update_existing_drone(manager, sample_drone):
    """Test updating an existing drone"""
    drone_id = "drone-TEST001"

    # Add drone first
    manager.update_or_add_drone(drone_id, sample_drone)

    # Create updated drone data
    updated_drone = Drone(
        id=drone_id,
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

    # Update existing drone
    manager.update_or_add_drone(drone_id, updated_drone)

    # Should still have only 1 drone
    assert len(manager.drone_dict) == 1

    # Position should be updated
    stored_drone = manager.drone_dict[drone_id]
    assert stored_drone.lat == 39.7400
    assert stored_drone.lon == -104.9910
    assert stored_drone.speed == 12.0
    assert stored_drone.rssi == -68


def test_manager_fifo_eviction(manager):
    """Test that oldest drone is removed when max_drones is reached"""
    # Manager has max_drones=10
    # Add 11 drones
    for i in range(11):
        drone = Drone(
            id=f"drone-TEST{i:03d}",
            lat=39.7392 + i * 0.001,
            lon=-104.9903,
            speed=10.0,
            vspeed=1.5,
            alt=1655.5,
            height=50.0,
            pilot_lat=39.7400,
            pilot_lon=-104.9900,
            description=f"Drone {i}",
            mac=f"AA:BB:CC:DD:EE:{i:02X}",
            rssi=-65
        )
        manager.update_or_add_drone(f"drone-TEST{i:03d}", drone)

    # Should have exactly 10 drones
    assert len(manager.drone_dict) == 10
    assert len(manager.drones) == 10

    # First drone (TEST000) should be removed
    assert "drone-TEST000" not in manager.drone_dict

    # Last 10 drones (TEST001 through TEST010) should be present
    for i in range(1, 11):
        assert f"drone-TEST{i:03d}" in manager.drone_dict


def test_manager_send_updates_rate_limiting(manager_with_sink, sample_drone):
    """Test that rate limiting prevents too-frequent sends"""
    drone_id = "drone-TEST001"
    manager_with_sink.update_or_add_drone(drone_id, sample_drone)

    # First send should work immediately (sends both drone and pilot CoT)
    manager_with_sink.send_updates()
    initial_call_count = manager_with_sink.cot_messenger.send_cot.call_count
    assert initial_call_count >= 1  # At least drone CoT

    # Second send immediately after should be rate-limited
    manager_with_sink.send_updates()
    assert manager_with_sink.cot_messenger.send_cot.call_count == initial_call_count  # No new calls

    # Update last_sent_time to be >1 second ago
    sample_drone.last_sent_time = time.time() - 2.0

    # Now send should work again
    manager_with_sink.send_updates()
    assert manager_with_sink.cot_messenger.send_cot.call_count > initial_call_count


def test_manager_send_updates_calls_sinks(manager_with_sink, sample_drone, mock_sink):
    """Test that send_updates dispatches to all sinks"""
    drone_id = "drone-TEST001"
    manager_with_sink.update_or_add_drone(drone_id, sample_drone)

    # Force immediate send by setting last_sent_time in the past
    sample_drone.last_sent_time = 0.0

    manager_with_sink.send_updates()

    # Sink methods should be called
    mock_sink.publish_drone.assert_called_once_with(sample_drone)
    mock_sink.publish_pilot.assert_called_once()
    mock_sink.publish_home.assert_not_called()  # home is 0,0 by default


def test_manager_send_updates_with_pilot_home(manager_with_sink, mock_sink):
    """Test that pilot and home CoT are sent when present"""
    drone = Drone(
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
        rssi=-65,
        home_lat=39.7380,
        home_lon=-104.9890
    )

    manager_with_sink.update_or_add_drone("drone-TEST001", drone)
    drone.last_sent_time = 0.0

    manager_with_sink.send_updates()

    # Both pilot and home should be published
    mock_sink.publish_pilot.assert_called_once()
    mock_sink.publish_home.assert_called_once()


def test_manager_inactivity_timeout(manager, sample_drone):
    """Test that inactive drones are removed after timeout"""
    drone_id = "drone-TEST001"
    manager.update_or_add_drone(drone_id, sample_drone)

    # Set last_update_time to be beyond inactivity_timeout
    sample_drone.last_update_time = time.time() - 120.0  # 120 seconds ago

    # Timeout is 60 seconds, so this drone should be removed
    manager.send_updates()

    assert drone_id not in manager.drone_dict
    assert drone_id not in manager.drones


def test_manager_inactivity_calls_mark_inactive(manager_with_sink, sample_drone, mock_sink):
    """Test that mark_inactive is called on sinks when drone times out"""
    drone_id = "drone-TEST001"
    manager_with_sink.update_or_add_drone(drone_id, sample_drone)

    # Make drone inactive
    sample_drone.last_update_time = time.time() - 120.0

    manager_with_sink.send_updates()

    # Sink should be notified
    mock_sink.mark_inactive.assert_called_once_with(drone_id)


def test_manager_export_tracks_empty(manager):
    """Test export_tracks returns empty list when no drones"""
    tracks = manager.export_tracks()
    assert tracks == []


def test_manager_export_tracks_with_drones(manager, sample_drone):
    """Test export_tracks returns drone dictionaries"""
    manager.update_or_add_drone("drone-TEST001", sample_drone)

    drone2 = Drone(
        id="drone-TEST002",
        lat=39.7500,
        lon=-105.0000,
        speed=15.0,
        vspeed=2.0,
        alt=1700.0,
        height=100.0,
        pilot_lat=39.7505,
        pilot_lon=-105.0005,
        description="Test Drone 2",
        mac="11:22:33:44:55:66",
        rssi=-70
    )
    manager.update_or_add_drone("drone-TEST002", drone2)

    tracks = manager.export_tracks()

    assert len(tracks) == 2
    assert all(t["track_type"] == "drone" for t in tracks)
    assert any(t["id"] == "drone-TEST001" for t in tracks)
    assert any(t["id"] == "drone-TEST002" for t in tracks)


def test_manager_export_tracks_with_aircraft(manager):
    """Test export_tracks includes aircraft when present"""
    # Add aircraft to manager
    manager.aircraft["adsb-ABC123"] = {
        "id": "adsb-ABC123",
        "lat": 39.8000,
        "lon": -105.1000,
        "alt": 30000.0,
        "speed": 450.0
    }

    tracks = manager.export_tracks()

    assert len(tracks) == 1
    assert tracks[0]["track_type"] == "aircraft"
    assert tracks[0]["id"] == "adsb-ABC123"


def test_manager_close_calls_sink_close(manager_with_sink, mock_sink):
    """Test that close() calls close() on all sinks"""
    manager_with_sink.close()

    mock_sink.close.assert_called_once()


def test_manager_close_graceful_with_no_close_method(manager):
    """Test that close() doesn't crash if sink has no close method"""
    # Add a sink without close method
    fake_sink = Mock(spec=[])  # No methods defined
    manager.extra_sinks.append(fake_sink)

    # Should not raise exception
    manager.close()


def test_manager_handles_sink_exceptions(manager_with_sink, sample_drone, mock_sink):
    """Test that sink exceptions don't crash send_updates"""
    # Make sink raise exception
    mock_sink.publish_drone.side_effect = Exception("Sink failure")

    manager_with_sink.update_or_add_drone("drone-TEST001", sample_drone)
    sample_drone.last_sent_time = 0.0

    # Should not crash despite sink exception
    manager_with_sink.send_updates()

    # CoT should still be sent
    assert manager_with_sink.cot_messenger.send_cot.call_count >= 1


def test_manager_multiple_sinks(mock_cot_messenger, sample_drone):
    """Test that multiple sinks are all called"""
    sink1 = Mock()
    sink1.publish_drone = Mock()
    sink2 = Mock()
    sink2.publish_drone = Mock()

    manager = DroneManager(
        max_drones=10,
        rate_limit=1.0,
        inactivity_timeout=60.0,
        cot_messenger=mock_cot_messenger,
        extra_sinks=[sink1, sink2]
    )

    manager.update_or_add_drone("drone-TEST001", sample_drone)
    sample_drone.last_sent_time = 0.0

    manager.send_updates()

    # Both sinks should be called
    sink1.publish_drone.assert_called_once()
    sink2.publish_drone.assert_called_once()


def test_manager_no_cot_messenger(sample_drone):
    """Test that manager works without a CoT messenger"""
    manager = DroneManager(
        max_drones=10,
        rate_limit=1.0,
        inactivity_timeout=60.0,
        cot_messenger=None
    )

    manager.update_or_add_drone("drone-TEST001", sample_drone)
    sample_drone.last_sent_time = 0.0

    # Should not crash
    manager.send_updates()


def test_manager_stale_offset_calculation(manager, sample_drone):
    """Test that stale_offset is calculated correctly"""
    drone_id = "drone-TEST001"
    manager.update_or_add_drone(drone_id, sample_drone)

    # Set update time to 10 seconds ago
    current_time = time.time()
    sample_drone.last_update_time = current_time - 10.0
    sample_drone.last_sent_time = 0.0

    # Mock to_cot_xml to capture stale_offset
    original_to_cot_xml = sample_drone.to_cot_xml
    captured_stale_offset = None

    def capture_stale_offset(stale_offset=None):
        nonlocal captured_stale_offset
        captured_stale_offset = stale_offset
        return original_to_cot_xml(stale_offset=stale_offset)

    sample_drone.to_cot_xml = capture_stale_offset

    manager.send_updates()

    # stale_offset should be inactivity_timeout - age
    # = 60.0 - 10.0 = 50.0
    assert captured_stale_offset is not None
    assert 49.0 < captured_stale_offset < 51.0  # Allow small timing variance


def test_manager_position_change_tracking(manager, sample_drone):
    """Test that position changes are tracked"""
    drone_id = "drone-TEST001"
    manager.update_or_add_drone(drone_id, sample_drone)

    # Set initial sent position
    sample_drone.last_sent_lat = 39.7392
    sample_drone.last_sent_lon = -104.9903
    sample_drone.last_sent_time = 0.0

    # Update position
    sample_drone.lat = 39.7400
    sample_drone.lon = -104.9910

    manager.send_updates()

    # After send, last_sent_lat/lon should be updated
    assert sample_drone.last_sent_lat == 39.7400
    assert sample_drone.last_sent_lon == -104.9910


def test_manager_drone_dict_consistency(manager):
    """Test that drones deque and drone_dict stay in sync"""
    # Add drones
    for i in range(5):
        drone = Drone(
            id=f"drone-TEST{i:03d}",
            lat=39.7392,
            lon=-104.9903,
            speed=10.0,
            vspeed=1.5,
            alt=1655.5,
            height=50.0,
            pilot_lat=39.7400,
            pilot_lon=-104.9900,
            description=f"Drone {i}",
            mac=f"AA:BB:CC:DD:EE:{i:02X}",
            rssi=-65
        )
        manager.update_or_add_drone(f"drone-TEST{i:03d}", drone)

    # Check consistency
    assert len(manager.drones) == len(manager.drone_dict)

    for drone_id in manager.drones:
        assert drone_id in manager.drone_dict


def test_manager_update_or_add_with_frequency(manager):
    """Test that frequency is preserved when updating drone"""
    drone1 = Drone(
        id="drone-DJI001",
        lat=39.7392,
        lon=-104.9903,
        speed=10.0,
        vspeed=1.5,
        alt=1655.5,
        height=50.0,
        pilot_lat=39.7400,
        pilot_lon=-104.9900,
        description="DJI",
        mac="60:60:1F:AA:BB:CC",
        rssi=-72,
        freq=5800000000.0
    )

    manager.update_or_add_drone("drone-DJI001", drone1)

    # Update with new frequency
    drone2 = Drone(
        id="drone-DJI001",
        lat=39.7400,
        lon=-104.9910,
        speed=12.0,
        vspeed=2.0,
        alt=1660.0,
        height=55.0,
        pilot_lat=39.7410,
        pilot_lon=-104.9915,
        description="DJI",
        mac="60:60:1F:AA:BB:CC",
        rssi=-74,
        freq=5805000000.0
    )

    manager.update_or_add_drone("drone-DJI001", drone2)

    # Frequency should be updated
    assert manager.drone_dict["drone-DJI001"].freq == 5805000000.0
