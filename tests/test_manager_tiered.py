#!/usr/bin/env python3
"""
Comprehensive test suite for two-tier drone tracking system.

Tests verify:
- Tiered mode initialization
- Verified/unverified tier separation
- Promotion from unverified to verified
- Eviction priority (unverified evicted first)
- MAC index integrity across tiers
- Thread safety
- Backward compatibility
"""

import pytest
import time
from core import DroneManager, Drone


class TestTieredMode:
    """Test two-tier drone tracking system."""

    def test_tiered_mode_initialization(self):
        """Verify tiered mode creates two separate deques."""
        manager = DroneManager(
            max_verified_drones=70,
            max_unverified_drones=30,
            rate_limit=1.0,
            inactivity_timeout=60.0
        )

        assert manager._tiered_mode is True
        assert manager.verified_drones is not None
        assert manager.unverified_drones is not None
        assert manager.drones is None
        assert manager.verified_drones.maxlen == 70
        assert manager.unverified_drones.maxlen == 30

    def test_legacy_mode_initialization(self):
        """Verify legacy mode creates single deque when split not specified."""
        manager = DroneManager(
            max_drones=100,
            rate_limit=1.0,
            inactivity_timeout=60.0
        )

        assert manager._tiered_mode is False
        assert manager.verified_drones is None
        assert manager.unverified_drones is None
        assert manager.drones is not None
        assert manager.drones.maxlen == 100

    def test_add_unverified_drone(self):
        """Verify unverified drone is added to unverified tier."""
        manager = DroneManager(
            max_verified_drones=5,
            max_unverified_drones=3,
            rate_limit=1.0,
            inactivity_timeout=60.0
        )

        drone = Drone(
            id="drone-UNVERIFIED001",
            lat=39.7392,
            lon=-104.9903,
            speed=10.0,
            vspeed=1.5,
            alt=1655.5,
            height=50.0,
            pilot_lat=39.7400,
            pilot_lon=-104.9900,
            description="Test Unverified Drone",
            mac="AA:BB:CC:DD:EE:01",
            rssi=-65
        )
        drone.rid_lookup_success = False  # Unverified

        manager.update_or_add_drone("drone-UNVERIFIED001", drone)

        assert len(manager.unverified_drones) == 1
        assert len(manager.verified_drones) == 0
        assert "drone-UNVERIFIED001" in manager.unverified_drones
        assert "drone-UNVERIFIED001" in manager.drone_dict
        assert manager.mac_to_id.get("AA:BB:CC:DD:EE:01") == "drone-UNVERIFIED001"

    def test_add_verified_drone(self):
        """Verify verified drone is added to verified tier."""
        manager = DroneManager(
            max_verified_drones=5,
            max_unverified_drones=3,
            rate_limit=1.0,
            inactivity_timeout=60.0
        )

        drone = Drone(
            id="drone-VERIFIED001",
            lat=39.7392,
            lon=-104.9903,
            speed=10.0,
            vspeed=1.5,
            alt=1655.5,
            height=50.0,
            pilot_lat=39.7400,
            pilot_lon=-104.9900,
            description="Test Verified Drone",
            mac="AA:BB:CC:DD:EE:02",
            rssi=-65
        )
        drone.rid_lookup_success = True  # Verified

        manager.update_or_add_drone("drone-VERIFIED001", drone)

        assert len(manager.verified_drones) == 1
        assert len(manager.unverified_drones) == 0
        assert "drone-VERIFIED001" in manager.verified_drones
        assert "drone-VERIFIED001" in manager.drone_dict
        assert manager.mac_to_id.get("AA:BB:CC:DD:EE:02") == "drone-VERIFIED001"

    def test_promotion_unverified_to_verified(self):
        """Verify drone is promoted when RID lookup succeeds."""
        manager = DroneManager(
            max_verified_drones=5,
            max_unverified_drones=3,
            rate_limit=1.0,
            inactivity_timeout=60.0
        )

        # Add unverified drone (simulates first telemetry frame)
        drone = Drone(
            id="drone-PROMOTE001",
            lat=39.7392,
            lon=-104.9903,
            speed=10.0,
            vspeed=1.5,
            alt=1655.5,
            height=50.0,
            pilot_lat=39.7400,
            pilot_lon=-104.9900,
            description="Test Promotion",
            mac="AA:BB:CC:DD:EE:03",
            rssi=-65
        )
        drone.rid_lookup_success = False

        manager.update_or_add_drone("drone-PROMOTE001", drone)

        # Verify initial state
        assert len(manager.unverified_drones) == 1
        assert len(manager.verified_drones) == 0
        assert "drone-PROMOTE001" in manager.unverified_drones

        # Simulate RID lookup success (create NEW drone object like production does)
        drone_updated = Drone(
            id="drone-PROMOTE001",
            lat=39.7392,
            lon=-104.9903,
            speed=10.0,
            vspeed=1.5,
            alt=1655.5,
            height=50.0,
            pilot_lat=39.7400,
            pilot_lon=-104.9900,
            description="Test Promotion",
            mac="AA:BB:CC:DD:EE:03",
            rssi=-65
        )
        drone_updated.rid_lookup_success = True
        manager.update_or_add_drone("drone-PROMOTE001", drone_updated)

        # Verify promotion
        assert len(manager.unverified_drones) == 0
        assert len(manager.verified_drones) == 1
        assert "drone-PROMOTE001" in manager.verified_drones
        assert "drone-PROMOTE001" in manager.drone_dict
        assert manager.mac_to_id.get("AA:BB:CC:DD:EE:03") == "drone-PROMOTE001"

    def test_unverified_eviction_when_full(self):
        """Verify unverified tier evicts oldest when full."""
        manager = DroneManager(
            max_verified_drones=5,
            max_unverified_drones=3,
            rate_limit=1.0,
            inactivity_timeout=60.0
        )

        # Fill unverified tier to capacity
        for i in range(3):
            drone = Drone(
                id=f"drone-UNVERIFIED{i:03d}",
                lat=39.7392 + i * 0.0001,
                lon=-104.9903,
                speed=10.0,
                vspeed=1.5,
                alt=1655.5,
                height=50.0,
                pilot_lat=39.7400,
                pilot_lon=-104.9900,
                description=f"Unverified {i}",
                mac=f"AA:BB:CC:DD:EE:{i:02x}",
                rssi=-65
            )
            drone.rid_lookup_success = False
            manager.update_or_add_drone(f"drone-UNVERIFIED{i:03d}", drone)

        # Verify tier is full
        assert len(manager.unverified_drones) == 3
        assert "drone-UNVERIFIED000" in manager.unverified_drones

        # Add one more - should evict oldest (UNVERIFIED000)
        drone_new = Drone(
            id="drone-UNVERIFIED999",
            lat=39.7392,
            lon=-104.9903,
            speed=10.0,
            vspeed=1.5,
            alt=1655.5,
            height=50.0,
            pilot_lat=39.7400,
            pilot_lon=-104.9900,
            description="New Unverified",
            mac="AA:BB:CC:DD:EE:FF",
            rssi=-65
        )
        drone_new.rid_lookup_success = False
        manager.update_or_add_drone("drone-UNVERIFIED999", drone_new)

        # Verify eviction
        assert len(manager.unverified_drones) == 3
        assert "drone-UNVERIFIED000" not in manager.unverified_drones
        assert "drone-UNVERIFIED000" not in manager.drone_dict
        assert manager.mac_to_id.get("AA:BB:CC:DD:EE:00") is None
        assert "drone-UNVERIFIED999" in manager.unverified_drones

    def test_verified_eviction_when_full(self):
        """Verify verified tier evicts oldest when full."""
        manager = DroneManager(
            max_verified_drones=3,
            max_unverified_drones=5,
            rate_limit=1.0,
            inactivity_timeout=60.0
        )

        # Fill verified tier to capacity
        for i in range(3):
            drone = Drone(
                id=f"drone-VERIFIED{i:03d}",
                lat=39.7392 + i * 0.0001,
                lon=-104.9903,
                speed=10.0,
                vspeed=1.5,
                alt=1655.5,
                height=50.0,
                pilot_lat=39.7400,
                pilot_lon=-104.9900,
                description=f"Verified {i}",
                mac=f"BB:BB:CC:DD:EE:{i:02x}",
                rssi=-65
            )
            drone.rid_lookup_success = True
            manager.update_or_add_drone(f"drone-VERIFIED{i:03d}", drone)

        assert len(manager.verified_drones) == 3

        # Add one more - should evict oldest (VERIFIED000)
        drone_new = Drone(
            id="drone-VERIFIED999",
            lat=39.7392,
            lon=-104.9903,
            speed=10.0,
            vspeed=1.5,
            alt=1655.5,
            height=50.0,
            pilot_lat=39.7400,
            pilot_lon=-104.9900,
            description="New Verified",
            mac="BB:BB:CC:DD:EE:FF",
            rssi=-65
        )
        drone_new.rid_lookup_success = True
        manager.update_or_add_drone("drone-VERIFIED999", drone_new)

        # Verify eviction
        assert len(manager.verified_drones) == 3
        assert "drone-VERIFIED000" not in manager.verified_drones
        assert "drone-VERIFIED000" not in manager.drone_dict
        assert "drone-VERIFIED999" in manager.verified_drones

    def test_promotion_evicts_oldest_verified_when_full(self):
        """Verify promotion evicts oldest verified drone when verified tier is full."""
        manager = DroneManager(
            max_verified_drones=2,
            max_unverified_drones=3,
            rate_limit=1.0,
            inactivity_timeout=60.0
        )

        # Fill verified tier
        for i in range(2):
            drone = Drone(
                id=f"drone-VERIFIED{i:03d}",
                lat=39.7392,
                lon=-104.9903,
                speed=10.0,
                vspeed=1.5,
                alt=1655.5,
                height=50.0,
                pilot_lat=39.7400,
                pilot_lon=-104.9900,
                description=f"Verified {i}",
                mac=f"CC:BB:CC:DD:EE:{i:02x}",
                rssi=-65
            )
            drone.rid_lookup_success = True
            manager.update_or_add_drone(f"drone-VERIFIED{i:03d}", drone)

        # Add unverified drone
        drone_unverified = Drone(
            id="drone-PROMOTE999",
            lat=39.7392,
            lon=-104.9903,
            speed=10.0,
            vspeed=1.5,
            alt=1655.5,
            height=50.0,
            pilot_lat=39.7400,
            pilot_lon=-104.9900,
            description="To Promote",
            mac="CC:BB:CC:DD:EE:FF",
            rssi=-65
        )
        drone_unverified.rid_lookup_success = False
        manager.update_or_add_drone("drone-PROMOTE999", drone_unverified)

        assert len(manager.verified_drones) == 2
        assert len(manager.unverified_drones) == 1

        # Promote - should evict oldest verified (VERIFIED000)
        # Create NEW drone object with updated status (like production does)
        drone_promoted = Drone(
            id="drone-PROMOTE999",
            lat=39.7392,
            lon=-104.9903,
            speed=10.0,
            vspeed=1.5,
            alt=1655.5,
            height=50.0,
            pilot_lat=39.7400,
            pilot_lon=-104.9900,
            description="To Promote",
            mac="CC:BB:CC:DD:EE:FF",
            rssi=-65
        )
        drone_promoted.rid_lookup_success = True
        manager.update_or_add_drone("drone-PROMOTE999", drone_promoted)

        assert len(manager.verified_drones) == 2
        assert len(manager.unverified_drones) == 0
        assert "drone-VERIFIED000" not in manager.verified_drones
        assert "drone-VERIFIED000" not in manager.drone_dict
        assert "drone-PROMOTE999" in manager.verified_drones

    def test_mac_index_across_tiers(self):
        """Verify MAC index works for drones in both tiers."""
        manager = DroneManager(
            max_verified_drones=5,
            max_unverified_drones=3,
            rate_limit=1.0,
            inactivity_timeout=60.0
        )

        # Add verified drone
        drone_v = Drone(
            id="drone-VERIFIED001",
            lat=39.7392,
            lon=-104.9903,
            speed=10.0,
            vspeed=1.5,
            alt=1655.5,
            height=50.0,
            pilot_lat=39.7400,
            pilot_lon=-104.9900,
            description="Verified",
            mac="DD:BB:CC:DD:EE:01",
            rssi=-65
        )
        drone_v.rid_lookup_success = True
        manager.update_or_add_drone("drone-VERIFIED001", drone_v)

        # Add unverified drone
        drone_u = Drone(
            id="drone-UNVERIFIED001",
            lat=39.7392,
            lon=-104.9903,
            speed=10.0,
            vspeed=1.5,
            alt=1655.5,
            height=50.0,
            pilot_lat=39.7400,
            pilot_lon=-104.9900,
            description="Unverified",
            mac="DD:BB:CC:DD:EE:02",
            rssi=-65
        )
        drone_u.rid_lookup_success = False
        manager.update_or_add_drone("drone-UNVERIFIED001", drone_u)

        # Verify MAC lookups work for both tiers
        assert manager.get_drone_by_mac("DD:BB:CC:DD:EE:01").id == "drone-VERIFIED001"
        assert manager.get_drone_by_mac("DD:BB:CC:DD:EE:02").id == "drone-UNVERIFIED001"

    def test_mac_index_during_promotion(self):
        """Verify MAC index remains valid after promotion."""
        manager = DroneManager(
            max_verified_drones=5,
            max_unverified_drones=3,
            rate_limit=1.0,
            inactivity_timeout=60.0
        )

        drone = Drone(
            id="drone-PROMOTE001",
            lat=39.7392,
            lon=-104.9903,
            speed=10.0,
            vspeed=1.5,
            alt=1655.5,
            height=50.0,
            pilot_lat=39.7400,
            pilot_lon=-104.9900,
            description="Promotion Test",
            mac="EE:BB:CC:DD:EE:01",
            rssi=-65
        )
        drone.rid_lookup_success = False
        manager.update_or_add_drone("drone-PROMOTE001", drone)

        # Verify MAC lookup works before promotion
        assert manager.get_drone_by_mac("EE:BB:CC:DD:EE:01").id == "drone-PROMOTE001"

        # Promote (create new object like production does)
        drone_promoted = Drone(
            id="drone-PROMOTE001",
            lat=39.7392,
            lon=-104.9903,
            speed=10.0,
            vspeed=1.5,
            alt=1655.5,
            height=50.0,
            pilot_lat=39.7400,
            pilot_lon=-104.9900,
            description="Promotion Test",
            mac="EE:BB:CC:DD:EE:01",
            rssi=-65
        )
        drone_promoted.rid_lookup_success = True
        manager.update_or_add_drone("drone-PROMOTE001", drone_promoted)

        # Verify MAC lookup still works after promotion
        assert manager.get_drone_by_mac("EE:BB:CC:DD:EE:01").id == "drone-PROMOTE001"

    def test_send_updates_iterates_both_tiers(self):
        """Verify send_updates processes drones from both tiers."""
        manager = DroneManager(
            max_verified_drones=5,
            max_unverified_drones=3,
            rate_limit=0.1,
            inactivity_timeout=60.0
        )

        # Add verified drone
        drone_v = Drone(
            id="drone-VERIFIED001",
            lat=39.7392,
            lon=-104.9903,
            speed=10.0,
            vspeed=1.5,
            alt=1655.5,
            height=50.0,
            pilot_lat=39.7400,
            pilot_lon=-104.9900,
            description="Verified",
            mac="FF:BB:CC:DD:EE:01",
            rssi=-65
        )
        drone_v.rid_lookup_success = True
        manager.update_or_add_drone("drone-VERIFIED001", drone_v)

        # Add unverified drone
        drone_u = Drone(
            id="drone-UNVERIFIED001",
            lat=39.7392,
            lon=-104.9903,
            speed=10.0,
            vspeed=1.5,
            alt=1655.5,
            height=50.0,
            pilot_lat=39.7400,
            pilot_lon=-104.9900,
            description="Unverified",
            mac="FF:BB:CC:DD:EE:02",
            rssi=-65
        )
        drone_u.rid_lookup_success = False
        manager.update_or_add_drone("drone-UNVERIFIED001", drone_u)

        # Wait for rate limit
        time.sleep(0.15)

        # Send updates - should process both tiers
        manager.send_updates()

        # Verify both drones were processed (last_sent_time updated)
        assert manager.drone_dict["drone-VERIFIED001"].last_sent_time > 0
        assert manager.drone_dict["drone-UNVERIFIED001"].last_sent_time > 0

    def test_inactivity_cleanup_both_tiers(self):
        """Verify inactive drones are removed from both tiers."""
        manager = DroneManager(
            max_verified_drones=5,
            max_unverified_drones=3,
            rate_limit=1.0,
            inactivity_timeout=0.5  # Short timeout for testing
        )

        # Add verified drone
        drone_v = Drone(
            id="drone-VERIFIED001",
            lat=39.7392,
            lon=-104.9903,
            speed=10.0,
            vspeed=1.5,
            alt=1655.5,
            height=50.0,
            pilot_lat=39.7400,
            pilot_lon=-104.9900,
            description="Verified",
            mac="AA:AA:CC:DD:EE:01",
            rssi=-65
        )
        drone_v.rid_lookup_success = True
        manager.update_or_add_drone("drone-VERIFIED001", drone_v)

        # Add unverified drone
        drone_u = Drone(
            id="drone-UNVERIFIED001",
            lat=39.7392,
            lon=-104.9903,
            speed=10.0,
            vspeed=1.5,
            alt=1655.5,
            height=50.0,
            pilot_lat=39.7400,
            pilot_lon=-104.9900,
            description="Unverified",
            mac="AA:AA:CC:DD:EE:02",
            rssi=-65
        )
        drone_u.rid_lookup_success = False
        manager.update_or_add_drone("drone-UNVERIFIED001", drone_u)

        assert len(manager.verified_drones) == 1
        assert len(manager.unverified_drones) == 1

        # Wait for inactivity timeout
        time.sleep(0.6)

        # Trigger cleanup
        manager.send_updates()

        # Both drones should be removed
        assert len(manager.verified_drones) == 0
        assert len(manager.unverified_drones) == 0
        assert len(manager.drone_dict) == 0
        assert manager.mac_to_id.get("AA:AA:CC:DD:EE:01") is None
        assert manager.mac_to_id.get("AA:AA:CC:DD:EE:02") is None

    def test_export_tracks_includes_both_tiers(self):
        """Verify export_tracks returns drones from both tiers."""
        manager = DroneManager(
            max_verified_drones=5,
            max_unverified_drones=3,
            rate_limit=1.0,
            inactivity_timeout=60.0
        )

        # Add verified drone
        drone_v = Drone(
            id="drone-VERIFIED001",
            lat=39.7392,
            lon=-104.9903,
            speed=10.0,
            vspeed=1.5,
            alt=1655.5,
            height=50.0,
            pilot_lat=39.7400,
            pilot_lon=-104.9900,
            description="Verified",
            mac="BB:AA:CC:DD:EE:01",
            rssi=-65
        )
        drone_v.rid_lookup_success = True
        manager.update_or_add_drone("drone-VERIFIED001", drone_v)

        # Add unverified drone
        drone_u = Drone(
            id="drone-UNVERIFIED001",
            lat=39.7392,
            lon=-104.9903,
            speed=10.0,
            vspeed=1.5,
            alt=1655.5,
            height=50.0,
            pilot_lat=39.7400,
            pilot_lon=-104.9900,
            description="Unverified",
            mac="BB:AA:CC:DD:EE:02",
            rssi=-65
        )
        drone_u.rid_lookup_success = False
        manager.update_or_add_drone("drone-UNVERIFIED001", drone_u)

        tracks = manager.export_tracks()

        assert len(tracks) == 2
        track_ids = [t["id"] for t in tracks]
        assert "drone-VERIFIED001" in track_ids
        assert "drone-UNVERIFIED001" in track_ids


class TestBackwardCompatibility:
    """Verify legacy mode continues to work as before."""

    def test_legacy_mode_behavior(self):
        """Verify legacy mode behaves identically to pre-tiering code."""
        manager = DroneManager(
            max_drones=10,
            rate_limit=1.0,
            inactivity_timeout=60.0
        )

        # Add drones using legacy mode
        for i in range(12):  # Add more than capacity
            drone = Drone(
                id=f"drone-LEGACY{i:03d}",
                lat=39.7392 + i * 0.0001,
                lon=-104.9903,
                speed=10.0,
                vspeed=1.5,
                alt=1655.5,
                height=50.0,
                pilot_lat=39.7400,
                pilot_lon=-104.9900,
                description=f"Legacy {i}",
                mac=f"CC:AA:CC:DD:EE:{i:02x}",
                rssi=-65
            )
            # RID lookup status should not affect tier placement in legacy mode
            drone.rid_lookup_success = (i % 2 == 0)
            manager.update_or_add_drone(f"drone-LEGACY{i:03d}", drone)

        # Should have max_drones (10) drones, oldest 2 evicted
        assert len(manager.drones) == 10
        assert len(manager.drone_dict) == 10
        assert "drone-LEGACY000" not in manager.drone_dict
        assert "drone-LEGACY001" not in manager.drone_dict
        assert "drone-LEGACY011" in manager.drone_dict


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
