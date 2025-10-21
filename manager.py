"""
MIT License

Copyright (c) 2025 cemaxecuter

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
