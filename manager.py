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

import time
from collections import deque
from typing import Optional, List, Dict, Tuple
import logging
import math

from drone import Drone
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
    """

    def __init__(
        self,
        max_drones: int = 30,
        rate_limit: float = 1.0,
        inactivity_timeout: float = 60.0,
        cot_messenger: Optional[CotMessenger] = None,
        extra_sinks: Optional[List] = None,
    ):
        # Opportunistic slots are the classic limit; trusted drones have a separate pool.
        self.max_opportunistic = max_drones
        self.max_trusted = max_drones  # allow trusted to double the total without evicting opportunistic slots

        self.drones: deque[str] = deque()  # manual eviction, no fixed maxlen
        self.drone_dict: Dict[str, Drone] = {}
        self.trusted_ids: set[str] = set()

        # MAC spam guard: track distinct IDs per MAC over a short window
        self.mac_id_window: Dict[str, List[tuple[float, str]]] = {}
        self.mac_window_seconds = 30.0
        self.max_ids_per_mac_window = 5
        self.mac_backoff_seconds = 60.0
        self.mac_blocked_until: Dict[str, float] = {}

        self.rate_limit = rate_limit
        self.inactivity_timeout = inactivity_timeout
        self.cot_messenger = cot_messenger
        self.extra_sinks = list(extra_sinks or [])

    def update_or_add_drone(self, drone_id: str, drone_data: Drone):
        """Updates an existing drone or adds a new one to the collection."""
        now = time.time()

        if drone_id not in self.drone_dict:
            if not self._admit_new_drone(drone_id, drone_data, now):
                return
        else:
            # Same as before, but now also track freq and trust promotion
            existing = self.drone_dict[drone_id]
            existing.update(
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

            # If RID lookup succeeds later, promote to trusted pool
            if getattr(existing, "rid_lookup_success", False):
                self.trusted_ids.add(drone_id)

            logger.debug(f"Updated drone: {drone_id}: {drone_data}")

    def send_updates(self):
        """Sends rate-limited CoT updates and dispatches the full Drone to sinks."""
        now = time.time()
        to_remove: List[str] = []

        for drone_id in list(self.drones):
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

                # 1) CoT main event
                try:
                    cot_xml = drone.to_cot_xml(stale_offset=stale_offset)
                    if self.cot_messenger and cot_xml:
                        self.cot_messenger.send_cot(cot_xml)
                except Exception as e:
                    logger.warning("CoT send failed for %s: %s", drone_id, e)

                # 2) Sinks (MQTT/HA/Lattice/etc.)
                for s in self.extra_sinks:
                    try:
                        if hasattr(s, "publish_drone"):
                            s.publish_drone(drone)
                        if (getattr(drone, "pilot_lat", 0.0) or getattr(drone, "pilot_lon", 0.0)) and hasattr(s, "publish_pilot"):
                            s.publish_pilot(drone_id, drone.pilot_lat, drone.pilot_lon, 0.0)
                        if (getattr(drone, "home_lat", 0.0) or getattr(drone, "home_lon", 0.0)) and hasattr(s, "publish_home"):
                            s.publish_home(drone_id, drone.home_lat, drone.home_lon, 0.0)
                    except Exception as e:
                        logger.warning("Sink publish failed for %s (sink=%s): %s", drone_id, s, e)

                # 3) Pilot/Home CoT
                try:
                    if drone.pilot_lat != 0.0 or drone.pilot_lon != 0.0:
                        pilot_xml = drone.to_pilot_cot_xml(stale_offset=stale_offset)
                        if self.cot_messenger and pilot_xml:
                            self.cot_messenger.send_cot(pilot_xml)
                    if drone.home_lat != 0.0 or drone.home_lon != 0.0:
                        home_xml = drone.to_home_cot_xml(stale_offset=stale_offset)
                        if self.cot_messenger and home_xml:
                            self.cot_messenger.send_cot(home_xml)
                except Exception as e:
                    logger.warning("Pilot/Home CoT send failed for %s: %s", drone_id, e)

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

            try:
                self.drones.remove(drone_id)
            except ValueError:
                pass
            self.drone_dict.pop(drone_id, None)
            self.trusted_ids.discard(drone_id)
            logger.debug("Removed drone: %s", drone_id)


    def close(self):
        """Give every sink a chance to cleanup (e.g., stop MQTT loops, flush, etc.)."""
        for s in self.extra_sinks:
            try:
                if hasattr(s, "close"):
                    s.close()
            except Exception as e:
                logger.warning("Error shutting down sink %s: %s", s, e)

    # ───────────────────────────── internal helpers ────────────────────────────

    def _is_trusted(self, d: Drone) -> bool:
        """Trusted when RID lookup succeeded (make/model resolved)."""
        return bool(getattr(d, "rid_lookup_success", False))

    def _admit_new_drone(self, drone_id: str, drone_data: Drone, now: float) -> bool:
        """Admission control with MAC/ID consistency and trusted reserve."""
        mac = getattr(drone_data, "mac", "") or ""
        trusted = self._is_trusted(drone_data)

        # MAC spam guard
        if mac:
            blocked_until = self.mac_blocked_until.get(mac, 0.0)
            if now < blocked_until:
                logger.debug("Rejecting %s from MAC %s (backoff active)", drone_id, mac)
                return False

            # prune old entries
            entries = self.mac_id_window.get(mac, [])
            entries = [(t, i) for (t, i) in entries if now - t <= self.mac_window_seconds]
            entries.append((now, drone_id))
            self.mac_id_window[mac] = entries
            unique_ids = {i for _, i in entries}
            if len(unique_ids) > self.max_ids_per_mac_window:
                self.mac_blocked_until[mac] = now + self.mac_backoff_seconds
                logger.warning("MAC %s presented %d unique IDs in %.0fs; backoff applied",
                               mac, len(unique_ids), self.mac_window_seconds)
                return False

        # Figure out pool sizes
        current_trusted = len(self.trusted_ids)
        current_opportunistic = len(self.drone_dict) - current_trusted

        if trusted:
            # If trusted pool is full, evict oldest trusted to make room
            if current_trusted >= self.max_trusted:
                evicted = self._evict_oldest(trusted_only=True)
                if not evicted:
                    logger.debug("No trusted slot available for %s; dropping", drone_id)
                    return False
        else:
            # Opportunistic pool enforcement
            if current_opportunistic >= self.max_opportunistic:
                evicted = self._evict_oldest(trusted_only=False)
                if not evicted:
                    logger.debug("No opportunistic slot available for %s; dropping", drone_id)
                    return False

        # Admit
        self.drones.append(drone_id)
        self.drone_dict[drone_id] = drone_data
        drone_data.last_sent_time = 0.0
        if trusted:
            self.trusted_ids.add(drone_id)
        logger.debug("Added new %s drone: %s", "trusted" if trusted else "opportunistic", drone_id)
        return True

    def _evict_oldest(self, trusted_only: bool) -> bool:
        """Evict the oldest drone matching trust filter. Returns True if evicted."""
        for _ in range(len(self.drones)):
            candidate_id = self.drones.popleft()
            is_trusted = candidate_id in self.trusted_ids
            if trusted_only and not is_trusted:
                # keep in order, append back
                self.drones.append(candidate_id)
                continue
            if not trusted_only and is_trusted:
                self.drones.append(candidate_id)
                continue

            # Evict this candidate
            self.drone_dict.pop(candidate_id, None)
            if is_trusted:
                self.trusted_ids.discard(candidate_id)
            logger.debug("Evicted oldest %s drone: %s",
                         "trusted" if is_trusted else "opportunistic", candidate_id)
            return True

        # nothing evicted
        return False
