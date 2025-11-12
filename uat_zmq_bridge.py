#!/usr/bin/env python3
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

UAT to ZMQ Bridge

This script bridges dump978 JSON output to ZMQ for DragonSync ingestion.
It polls the aircraft.json endpoint and publishes aircraft data to a ZMQ socket.
"""

import zmq
import json
import time
import logging
import argparse
import requests
from typing import Dict, Any, List, Optional
from uat_parser import parse_uat_aircraft

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class UatZmqBridge:
    """Bridge between dump978 and ZMQ."""

    def __init__(
        self,
        dump978_host: str = "127.0.0.1",
        dump978_port: int = 30979,
        zmq_bind_address: str = "tcp://127.0.0.1:4227",
        poll_interval: float = 1.0,
        min_position_age: float = 10.0,
        max_position_age: float = 60.0
    ):
        """
        Initialize the UAT to ZMQ bridge.

        Args:
            dump978_host: dump978 host
            dump978_port: dump978 JSON port (default: 30979)
            zmq_bind_address: ZMQ address to bind to
            poll_interval: How often to poll aircraft.json in seconds
            min_position_age: Minimum position age to accept (seconds)
            max_position_age: Maximum position age to accept (seconds)
        """
        self.dump978_url = f"http://{dump978_host}:{dump978_port}/data/aircraft.json"
        self.zmq_bind_address = zmq_bind_address
        self.poll_interval = poll_interval
        self.min_position_age = min_position_age
        self.max_position_age = max_position_age

        # ZMQ setup
        self.context = zmq.Context()
        self.socket = self.context.socket(zmq.PUB)
        self.socket.bind(zmq_bind_address)
        logger.info(f"ZMQ publisher bound to {zmq_bind_address}")

        # HTTP session for connection pooling
        self.session = requests.Session()
        self.session.headers.update({'User-Agent': 'DragonSync-UAT-Bridge/1.0'})

        # Track last seen aircraft to avoid duplicate sends
        self.last_seen: Dict[str, float] = {}

    def fetch_aircraft(self) -> Optional[List[Dict[str, Any]]]:
        """Fetch aircraft data from dump978."""
        try:
            response = self.session.get(self.dump978_url, timeout=5.0)
            response.raise_for_status()
            data = response.json()

            if 'aircraft' in data:
                return data['aircraft']
            else:
                logger.warning("No 'aircraft' key in response")
                return None

        except requests.exceptions.RequestException as e:
            logger.error(f"Error fetching aircraft data: {e}")
            return None
        except json.JSONDecodeError as e:
            logger.error(f"Error decoding JSON: {e}")
            return None

    def should_publish(self, aircraft: Dict[str, Any]) -> bool:
        """
        Determine if an aircraft should be published.

        Filters based on:
        - Position data present
        - Position age within acceptable range
        - Not recently published
        """
        # Must have address
        address = aircraft.get('address')
        if not address:
            return False

        # Must have position data
        if aircraft.get('lat') is None or aircraft.get('lon') is None:
            return False

        # Check position age
        seen_pos = aircraft.get('seen_pos')
        if seen_pos is not None:
            if seen_pos > self.max_position_age:
                return False
            # Skip if position is too fresh (likely not moved)
            if address in self.last_seen and seen_pos < self.min_position_age:
                time_since_last = time.time() - self.last_seen[address]
                if time_since_last < self.poll_interval * 2:
                    return False

        return True

    def publish_aircraft(self, aircraft: Dict[str, Any]) -> bool:
        """
        Parse and publish a single aircraft to ZMQ.

        Returns:
            True if published successfully, False otherwise
        """
        try:
            # Parse aircraft data
            drone_info = parse_uat_aircraft(aircraft)
            if not drone_info:
                return False

            # Publish to ZMQ
            self.socket.send_json(drone_info)

            # Update last seen time
            address = aircraft.get('address')
            if address:
                self.last_seen[address] = time.time()

            logger.debug(f"Published UAT aircraft {address}: {drone_info.get('callsign', 'N/A')}")
            return True

        except Exception as e:
            logger.error(f"Error publishing aircraft: {e}")
            return False

    def run(self):
        """Main loop to poll and publish aircraft data."""
        logger.info("Starting UAT to ZMQ bridge...")
        logger.info(f"Polling {self.dump978_url} every {self.poll_interval}s")

        # Give ZMQ subscribers time to connect
        time.sleep(1)

        published_count = 0
        error_count = 0

        try:
            while True:
                aircraft_list = self.fetch_aircraft()

                if aircraft_list is not None:
                    valid_count = 0
                    for aircraft in aircraft_list:
                        if self.should_publish(aircraft):
                            if self.publish_aircraft(aircraft):
                                valid_count += 1
                                published_count += 1

                    if valid_count > 0:
                        logger.info(f"Published {valid_count} aircraft (total: {published_count})")

                    # Reset error count on success
                    error_count = 0
                else:
                    error_count += 1
                    if error_count >= 5:
                        logger.error(f"Failed to fetch aircraft {error_count} times in a row")

                # Clean up old last_seen entries (older than 5 minutes)
                current_time = time.time()
                self.last_seen = {
                    addr: timestamp
                    for addr, timestamp in self.last_seen.items()
                    if current_time - timestamp < 300
                }

                # Wait before next poll
                time.sleep(self.poll_interval)

        except KeyboardInterrupt:
            logger.info("Shutting down...")
        except Exception as e:
            logger.error(f"Unexpected error in main loop: {e}", exc_info=True)
        finally:
            self.cleanup()

    def cleanup(self):
        """Clean up resources."""
        logger.info(f"Total aircraft published: {sum(1 for _ in self.last_seen)}")
        self.socket.close()
        self.context.term()
        self.session.close()


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(description="UAT to ZMQ Bridge for DragonSync")

    parser.add_argument(
        "--dump978-host",
        default="127.0.0.1",
        help="dump978 host (default: 127.0.0.1)"
    )
    parser.add_argument(
        "--dump978-port",
        type=int,
        default=30979,
        help="dump978 JSON port (default: 30979)"
    )
    parser.add_argument(
        "--zmq-bind",
        default="tcp://127.0.0.1:4227",
        help="ZMQ bind address (default: tcp://127.0.0.1:4227)"
    )
    parser.add_argument(
        "--poll-interval",
        type=float,
        default=1.0,
        help="Poll interval in seconds (default: 1.0)"
    )
    parser.add_argument(
        "--min-position-age",
        type=float,
        default=0.5,
        help="Minimum position age in seconds (default: 0.5)"
    )
    parser.add_argument(
        "--max-position-age",
        type=float,
        default=60.0,
        help="Maximum position age in seconds (default: 60.0)"
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Enable debug logging"
    )

    args = parser.parse_args()

    if args.debug:
        logging.getLogger().setLevel(logging.DEBUG)

    bridge = UatZmqBridge(
        dump978_host=args.dump978_host,
        dump978_port=args.dump978_port,
        zmq_bind_address=args.zmq_bind,
        poll_interval=args.poll_interval,
        min_position_age=args.min_position_age,
        max_position_age=args.max_position_age
    )

    bridge.run()


if __name__ == "__main__":
    main()
