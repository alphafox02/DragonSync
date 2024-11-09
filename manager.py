# manager.py

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
        self.rate_limit = rate_limit
        self.inactivity_timeout = inactivity_timeout
        self.last_sent_time = 0.0
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
            logger.debug(f"Added new drone: {drone_id}")
        else:
            self.drone_dict[drone_id] = drone_data
            logger.debug(f"Updated drone: {drone_id}")

    def send_updates(self):
        """Sends updates to the TAK server or multicast address."""
        current_time = time.time()
        if current_time - self.last_sent_time >= self.rate_limit:
            drones_to_remove = []
            for drone_id in list(self.drones):
                drone = self.drone_dict[drone_id]
                time_since_update = current_time - drone.last_update_time
                if time_since_update > self.inactivity_timeout:
                    # Drone is inactive, send a final CoT message with stale time set to now
                    cot_xml = drone.to_cot_xml(stale_offset=0)  # Set stale time to current time
                    if self.cot_messenger:
                        self.cot_messenger.send_cot(cot_xml)
                    drones_to_remove.append(drone_id)
                    logger.debug(f"Drone {drone_id} is inactive for {time_since_update:.2f} seconds. Sent final CoT message and removing from tracking.")
                    continue  # Skip sending regular CoT message for inactive drones

                # Update the 'stale' time in CoT message to reflect inactivity timeout
                cot_xml = drone.to_cot_xml(stale_offset=self.inactivity_timeout - time_since_update)
                if self.cot_messenger:
                    self.cot_messenger.send_cot(cot_xml)

            # Remove inactive drones
            for drone_id in drones_to_remove:
                self.drones.remove(drone_id)
                del self.drone_dict[drone_id]
                logger.debug(f"Removed drone: {drone_id}")

            self.last_sent_time = current_time
