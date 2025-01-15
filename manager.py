"""
MIT License

Copyright (c) 2024 cemaxecuter

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
from typing import Optional
import logging

from drone import Drone
from messaging import CotMessenger

logger = logging.getLogger(__name__)

class DroneManager:
    """Manages a collection of drones and handles their updates."""

    def __init__(self, max_drones=30, rate_limit=1.0, inactivity_timeout=60.0,
                 cot_messenger: Optional[CotMessenger] = None):
        """
        Initializes the DroneManager.
        
        :param max_drones: Maximum number of drones to track.
        :param rate_limit: Minimum interval between sending updates (in seconds).
        :param inactivity_timeout: Time after which a drone is considered inactive (in seconds).
        :param cot_messenger: Instance of CotMessenger for sending CoT messages.
        """
        self.drones = deque(maxlen=max_drones)
        self.drone_dict = {}
        self.rate_limit = rate_limit  # Active drone update frequency
        self.inactivity_timeout = inactivity_timeout  # Time before a drone is considered stale
        self.keep_alive_interval = 10.0  # Interval for sending keep-alive CoT updates for inactive drones
        self.cot_messenger = cot_messenger

    def update_or_add_drone(self, drone_id: str, drone_data: Drone):
        """Updates an existing drone or adds a new one to the collection."""
        if drone_id not in self.drone_dict:
            if len(self.drones) >= self.drones.maxlen:
                oldest_drone_id = self.drones.popleft()
                del self.drone_dict[oldest_drone_id]
                logger.debug(f"Removed oldest drone: {oldest_drone_id}")
            self.drones.append(drone_id)
            self.drone_dict[drone_id] = drone_data
            drone_data.last_sent_time = 0.0  # Initialize last sent time for the new drone
            logger.debug(f"Added new drone: {drone_id}")
        else:
            self.drone_dict[drone_id].update(
                lat=drone_data.lat, lon=drone_data.lon, speed=drone_data.speed,
                vspeed=drone_data.vspeed, alt=drone_data.alt, height=drone_data.height,
                pilot_lat=drone_data.pilot_lat, pilot_lon=drone_data.pilot_lon,
                description=drone_data.description, mac=drone_data.mac, rssi=drone_data.rssi
            )
            logger.debug(f"Updated drone: {drone_id}")

    def send_updates(self):
        """Sends updates to the TAK server or multicast address."""
        current_time = time.time()
        drones_to_remove = []

        for drone_id in list(self.drones):
            drone = self.drone_dict[drone_id]
            time_since_update = current_time - drone.last_update_time

            # Remove drones that have been inactive beyond the timeout
            if time_since_update > self.inactivity_timeout:
                # Final stale CoT message
                cot_xml = drone.to_cot_xml(stale_offset=0)  # Set stale time to current time
                if self.cot_messenger:
                    self.cot_messenger.send_cot(cot_xml)
                drones_to_remove.append(drone_id)
                logger.debug(f"Drone {drone_id} inactive for {time_since_update:.2f}s. Sent final CoT message.")
                continue

            # Active drone: send updates based on the rate limit
            if time_since_update < self.rate_limit:
                if current_time - drone.last_sent_time >= self.rate_limit:
                    cot_xml = drone.to_cot_xml(stale_offset=self.inactivity_timeout - time_since_update)
                    if self.cot_messenger:
                        self.cot_messenger.send_cot(cot_xml)
                        drone.last_sent_time = current_time
                        logger.debug(f"Sent CoT update for active drone {drone_id} after {time_since_update:.2f}s.")
            else:
                # Inactive-but-not-stale drone: send less frequent keep-alive updates
                if current_time - drone.last_sent_time >= self.keep_alive_interval:
                    cot_xml = drone.to_cot_xml(stale_offset=self.inactivity_timeout - time_since_update)
                    if self.cot_messenger:
                        self.cot_messenger.send_cot(cot_xml)
                        drone.last_sent_time = current_time
                        logger.debug(f"Sent keep-alive CoT update for inactive drone {drone_id}.")

        # Remove inactive drones after sending the final stale message
        for drone_id in drones_to_remove:
            self.drones.remove(drone_id)
            del self.drone_dict[drone_id]
            logger.debug(f"Removed drone: {drone_id}")
