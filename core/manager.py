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

import time
import threading
from collections import deque
from typing import Optional, List, Dict
import logging
import math

from .drone import Drone
from messaging import CotMessenger

logger = logging.getLogger(__name__)


class DroneManager:
    """Manages a collection of drones and handles their updates.

    All outputs (MQTT/HA/Lattice/etc.) are delegated to objects passed via
    `extra_sinks`. A sink may implement:
      - publish_drone(drone)
      - publish_pilot(drone_id, lat, lon, alt)
      - publish_home(drone_id,  lat, lon, alt)
      - close()

    Thread-safe: All drone_dict access is protected by an internal lock.
    """

    def __init__(
        self,
        max_drones: int = 30,
        max_verified_drones: Optional[int] = None,
        max_unverified_drones: Optional[int] = None,
        rate_limit: float = 1.0,
        inactivity_timeout: float = 60.0,
        cot_messenger: Optional[CotMessenger] = None,
        extra_sinks: Optional[List] = None,
    ):
        # Backward compatibility: if split not specified, use legacy single deque
        if max_verified_drones is None and max_unverified_drones is None:
            # Legacy mode: single deque (no tiering)
            self.verified_drones: Optional[deque[str]] = None
            self.unverified_drones: Optional[deque[str]] = None
            self.drones: deque[str] = deque(maxlen=max_drones)
            self._tiered_mode = False
            logger.info(f"DroneManager initialized in legacy mode: max_drones={max_drones}")
        else:
            # Tiered mode: two separate deques
            self.verified_drones: deque[str] = deque(maxlen=max_verified_drones or 70)
            self.unverified_drones: deque[str] = deque(maxlen=max_unverified_drones or 30)
            self.drones: Optional[deque[str]] = None
            self._tiered_mode = True
            logger.info(f"DroneManager initialized in tiered mode: verified={max_verified_drones or 70}, unverified={max_unverified_drones or 30}")

        self.drone_dict: Dict[str, Drone] = {}
        self.mac_to_id: Dict[str, str] = {}  # MAC address to drone_id index for fast CAA-only lookups
        # Optional ADS-B cache (uid -> dict). Populated externally if desired.
        self.aircraft: Dict[str, dict] = {}
        self.rate_limit = rate_limit
        self.inactivity_timeout = inactivity_timeout
        self.cot_messenger = cot_messenger
        self.extra_sinks = list(extra_sinks or [])
        self._lock = threading.RLock()  # Reentrant lock for nested access

    def _add_verified_drone(self, drone_id: str, drone_data: Drone):
        """Add drone to verified tier. Evict oldest verified if full.

        Must be called with self._lock held.
        """
        if len(self.verified_drones) >= self.verified_drones.maxlen:
            oldest_verified_id = self.verified_drones.popleft()
            oldest_drone = self.drone_dict.pop(oldest_verified_id, None)
            if oldest_drone and oldest_drone.mac:
                self.mac_to_id.pop(oldest_drone.mac, None)
            logger.debug(f"Evicted oldest verified drone: {oldest_verified_id}")

        self.verified_drones.append(drone_id)
        self.drone_dict[drone_id] = drone_data
        if drone_data.mac:
            self.mac_to_id[drone_data.mac] = drone_id
        logger.info(f"Added verified drone: {drone_id}")

    def _add_unverified_drone(self, drone_id: str, drone_data: Drone):
        """Add drone to unverified tier. Evict oldest unverified if full.

        Must be called with self._lock held.
        """
        if len(self.unverified_drones) >= self.unverified_drones.maxlen:
            oldest_unverified_id = self.unverified_drones.popleft()
            oldest_drone = self.drone_dict.pop(oldest_unverified_id, None)
            if oldest_drone and oldest_drone.mac:
                self.mac_to_id.pop(oldest_drone.mac, None)
            logger.debug(f"Evicted oldest unverified drone: {oldest_unverified_id}")

        self.unverified_drones.append(drone_id)
        self.drone_dict[drone_id] = drone_data
        if drone_data.mac:
            self.mac_to_id[drone_data.mac] = drone_id
        logger.debug(f"Added unverified drone: {drone_id}")

    def _promote_to_verified(self, drone_id: str):
        """Promote drone from unverified to verified tier after RID lookup success.

        Must be called with self._lock held.
        """
        drone = self.drone_dict.get(drone_id)
        if not drone:
            logger.debug(f"Cannot promote {drone_id}: already evicted")
            return

        if drone_id not in self.unverified_drones:
            return  # Already verified or not in system

        try:
            self.unverified_drones.remove(drone_id)
            logger.debug(f"Removed {drone_id} from unverified for promotion")
        except ValueError:
            logger.debug(f"Race condition: {drone_id} already removed during promotion")
            return

        if len(self.verified_drones) >= self.verified_drones.maxlen:
            oldest_verified_id = self.verified_drones.popleft()
            oldest_drone = self.drone_dict.pop(oldest_verified_id, None)
            if oldest_drone and oldest_drone.mac:
                self.mac_to_id.pop(oldest_drone.mac, None)
            logger.info(f"Evicted {oldest_verified_id} to make room for promoted {drone_id}")

        self.verified_drones.append(drone_id)
        logger.info(f"Promoted {drone_id} to verified tier (RID verified)")

    def update_or_add_drone(self, drone_id: str, drone_data: Drone):
        """Updates an existing drone or adds a new one to the collection.

        Thread-safe: Protected by internal lock.
        """
        with self._lock:
            if not self._tiered_mode:
                # Legacy mode: use existing single-deque logic
                if drone_id not in self.drone_dict:
                    if len(self.drones) >= self.drones.maxlen:
                        oldest_drone_id = self.drones.popleft()
                        oldest_drone = self.drone_dict.pop(oldest_drone_id, None)
                        if oldest_drone and oldest_drone.mac:
                            self.mac_to_id.pop(oldest_drone.mac, None)
                        logger.debug(f"Removed oldest drone: {oldest_drone_id}")
                    self.drones.append(drone_id)
                    self.drone_dict[drone_id] = drone_data
                    if drone_data.mac:
                        self.mac_to_id[drone_data.mac] = drone_id
                    drone_data.last_sent_time = 0.0
                    logger.debug(f"Added new drone: {drone_id}: {drone_data}")
                else:
                    self.drone_dict[drone_id].update(
                        lat=drone_data.lat,
                        lon=drone_data.lon,
                        speed=drone_data.speed,
                        vspeed=drone_data.vspeed,
                        alt=drone_data.alt,
                        height=drone_data.height,
                        pilot_lat=drone_data.pilot_lat,
                        pilot_lon=drone_data.pilot_lon,
                        description=drone_data.description,
                        mac=drone_data.mac,
                        rssi=drone_data.rssi,
                        freq=getattr(drone_data, "freq", None),
                    )
                    if drone_data.mac and self.mac_to_id.get(drone_data.mac) != drone_id:
                        self.mac_to_id[drone_data.mac] = drone_id
                    logger.debug(f"Updated drone: {drone_id}: {drone_data}")
                return

            # TIERED MODE
            if drone_id in self.drone_dict:
                existing_drone = self.drone_dict[drone_id]
                was_verified = existing_drone.rid_lookup_success
                now_verified = drone_data.rid_lookup_success

                if not was_verified and now_verified:
                    self._promote_to_verified(drone_id)

                existing_drone.update(
                    lat=drone_data.lat,
                    lon=drone_data.lon,
                    speed=drone_data.speed,
                    vspeed=drone_data.vspeed,
                    alt=drone_data.alt,
                    height=drone_data.height,
                    pilot_lat=drone_data.pilot_lat,
                    pilot_lon=drone_data.pilot_lon,
                    description=drone_data.description,
                    mac=drone_data.mac,
                    rssi=drone_data.rssi,
                    freq=getattr(drone_data, "freq", None),
                )

                # Update RID verification status after promotion check
                if drone_data.rid_lookup_success != existing_drone.rid_lookup_success:
                    existing_drone.rid_lookup_success = drone_data.rid_lookup_success

                if drone_data.mac and self.mac_to_id.get(drone_data.mac) != drone_id:
                    self.mac_to_id[drone_data.mac] = drone_id
                logger.debug(f"Updated drone: {drone_id}")
            else:
                drone_data.last_sent_time = 0.0
                if drone_data.rid_lookup_success:
                    self._add_verified_drone(drone_id, drone_data)
                else:
                    self._add_unverified_drone(drone_id, drone_data)

    def get_drone_by_mac(self, mac: str) -> Optional[Drone]:
        """Look up drone by MAC address (O(1) using index).

        Thread-safe: Protected by internal lock.
        Used for CAA-only broadcasts that don't include serial numbers.
        """
        with self._lock:
            drone_id = self.mac_to_id.get(mac)
            if drone_id:
                return self.drone_dict.get(drone_id)
            return None

    def _send_cot(self, cot_xml: bytes, context: str):
        """Helper to send CoT XML with error handling."""
        try:
            if self.cot_messenger and cot_xml:
                self.cot_messenger.send_cot(cot_xml)
        except Exception as e:
            logger.warning("%s: %s", context, e)

    def _dispatch_to_sinks(self, drone_id: str, drone: Drone):
        """Helper to dispatch drone updates to all configured sinks."""
        for s in self.extra_sinks:
            try:
                if hasattr(s, "publish_drone"):
                    s.publish_drone(drone)
                if (drone.pilot_lat or drone.pilot_lon) and hasattr(s, "publish_pilot"):
                    s.publish_pilot(drone_id, drone.pilot_lat, drone.pilot_lon, 0.0)
                if (drone.home_lat or drone.home_lon) and hasattr(s, "publish_home"):
                    s.publish_home(drone_id, drone.home_lat, drone.home_lon, 0.0)
            except Exception as e:
                logger.warning("Sink publish failed for %s (sink=%s): %s", drone_id, s, e)

    def send_updates(self):
        """Sends rate-limited CoT updates and dispatches the full Drone to sinks.

        Thread-safe: Protected by internal lock.
        """
        now = time.time()
        to_remove: List[str] = []

        with self._lock:
            # Determine which queue(s) to iterate
            if self._tiered_mode:
                drone_ids = list(self.verified_drones) + list(self.unverified_drones)
            else:
                drone_ids = list(self.drones)

            for drone_id in drone_ids:
                drone = self.drone_dict[drone_id]
                age = now - drone.last_update_time

                if age > self.inactivity_timeout:
                    to_remove.append(drone_id)
                    logger.debug("Drone %s inactive for %.2fs. Removing.", drone_id, age)
                    continue

                # position delta for diagnostics
                delta_lat = drone.lat - drone.last_sent_lat
                delta_lon = drone.lon - drone.last_sent_lon
                position_change = math.hypot(delta_lat, delta_lon)

                if (now - drone.last_sent_time) >= self.rate_limit:
                    stale_offset = self.inactivity_timeout - age

                    # Send drone CoT
                    self._send_cot(
                        drone.to_cot_xml(stale_offset=stale_offset),
                        f"CoT send failed for {drone_id}"
                    )

                    # Dispatch to sinks
                    self._dispatch_to_sinks(drone_id, drone)

                    # Send pilot/home CoT
                    if drone.pilot_lat != 0.0 or drone.pilot_lon != 0.0:
                        self._send_cot(
                            drone.to_pilot_cot_xml(stale_offset=stale_offset),
                            f"Pilot CoT send failed for {drone_id}"
                        )
                    if drone.home_lat != 0.0 or drone.home_lon != 0.0:
                        self._send_cot(
                            drone.to_home_cot_xml(stale_offset=stale_offset),
                            f"Home CoT send failed for {drone_id}"
                        )

                    drone.last_sent_lat = drone.lat
                    drone.last_sent_lon = drone.lon
                    drone.last_sent_time = now
                    logger.debug(
                        "Sent update for drone %s (position change: %.8f).",
                        drone_id, position_change
                    )

            # Housekeeping: drop inactive drones
            for drone_id in to_remove:
                for s in self.extra_sinks:
                    try:
                        if hasattr(s, "mark_inactive"):
                            s.mark_inactive(drone_id)
                    except Exception as e:
                        logger.warning("Sink mark_inactive failed for %s (sink=%s): %s", drone_id, s, e)

                # Remove from appropriate queue
                if self._tiered_mode:
                    try:
                        if drone_id in self.verified_drones:
                            self.verified_drones.remove(drone_id)
                        elif drone_id in self.unverified_drones:
                            self.unverified_drones.remove(drone_id)
                    except ValueError:
                        pass
                else:
                    try:
                        self.drones.remove(drone_id)
                    except ValueError:
                        pass

                removed_drone = self.drone_dict.pop(drone_id, None)
                # Remove from MAC index if it had a MAC
                if removed_drone and removed_drone.mac:
                    self.mac_to_id.pop(removed_drone.mac, None)
                logger.debug("Removed drone: %s", drone_id)


    def close(self):
        """Give every sink a chance to cleanup (e.g., stop MQTT loops, flush, etc.)."""
        for s in self.extra_sinks:
            try:
                if hasattr(s, "close"):
                    s.close()
            except Exception as e:
                logger.warning("Error shutting down sink %s: %s", s, e)

    def export_tracks(self):
        """
        Export a list of track dictionaries (drones + any aircraft) for API consumption.
        Adds a track_type field to disambiguate.

        Thread-safe: Protected by internal lock.
        """
        tracks = []
        with self._lock:
            try:
                for d in list(self.drone_dict.values()):
                    obj = d.to_dict()
                    obj["track_type"] = "drone"
                    tracks.append(obj)
            except Exception as e:
                logger.debug("Failed exporting drones for API: %s", e)
            # Aircraft export hook (if aircraft data is integrated into this manager)
            if hasattr(self, "aircraft") and isinstance(self.aircraft, dict):
                try:
                    for a in list(self.aircraft.values()):
                        obj = dict(a)
                        obj["track_type"] = "aircraft"
                        tracks.append(obj)
                except Exception as e:
                    logger.debug("Failed exporting aircraft for API: %s", e)
        return tracks
