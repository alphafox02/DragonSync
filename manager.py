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
from collections import deque
from typing import Optional, List, Dict
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
        self.drones: deque[str] = deque(maxlen=max_drones)
        self.drone_dict: Dict[str, Drone] = {}
        # Optional ADS-B cache (uid -> dict). Populated externally if desired.
        self.aircraft: Dict[str, dict] = {}
        self.rate_limit = rate_limit
        self.inactivity_timeout = inactivity_timeout
        self.cot_messenger = cot_messenger
        self.extra_sinks = list(extra_sinks or [])

    def update_or_add_drone(self, drone_id: str, drone_data: Drone):
        """Updates an existing drone or adds a new one to the collection."""
        if drone_id not in self.drone_dict:
            if len(self.drones) >= self.drones.maxlen:
                oldest_drone_id = self.drones.popleft()
                self.drone_dict.pop(oldest_drone_id, None)
                logger.debug(f"Removed oldest drone: {oldest_drone_id}")
            self.drones.append(drone_id)
            self.drone_dict[drone_id] = drone_data
            drone_data.last_sent_time = 0.0
            logger.debug(f"Added new drone: {drone_id}: {drone_data}")
        else:
            # Same as before, but now also track freq
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
        """
        tracks = []
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
