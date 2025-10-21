#!/usr/bin/env python3
"""
MIT License

Copyright (c) 2025 cemaxecuter

Test Drone Detection Message Generator for DragonSync

Publishes simulated drone detection messages to ZMQ telemetry stream for testing
TAK and Lattice integrations without requiring live drone detections.

Usage:
    # Replay static detections
    python test_drone_generator.py --scenario test_scenarios.json --mode replay

    # Simulate animated tracks
    python test_drone_generator.py --scenario test_scenarios.json --mode simulate --loop

    # Custom ZMQ endpoint
    python test_drone_generator.py --zmq-host 192.168.1.100 --zmq-port 4224
"""

import argparse
import json
import logging
import math
import signal
import sys
import time
from typing import Dict, List, Any, Optional, Tuple
import zmq

logger = logging.getLogger(__name__)


class DroneSimulator:
    """Simulates drone movement along a flight path with waypoint interpolation."""

    def __init__(self, track_config: Dict[str, Any]):
        """
        Initialize drone simulator from animated track configuration.

        Args:
            track_config: Dictionary containing drone_config and flight_path
        """
        self.name = track_config.get("name", "Unknown")
        self.description = track_config.get("description", "")
        self.drone_config = track_config["drone_config"]
        self.flight_path = track_config["flight_path"]

        self.waypoints = self.flight_path["waypoints"]
        self.cruise_speed = self.flight_path.get("cruise_speed", 8.0)
        self.cruise_altitude = self.flight_path.get("cruise_altitude", 75.0)
        self.altitude_agl = self.flight_path.get("altitude_agl", 50.0)
        self.loop = self.flight_path.get("loop", True)

        # Current state
        self.current_waypoint_idx = 0
        self.next_waypoint_idx = 1
        self.interpolation_progress = 0.0  # 0.0 to 1.0
        self.dwell_timer = 0.0
        self.is_dwelling = False
        self.completed = False

    def calculate_bearing(self, lat1: float, lon1: float, lat2: float, lon2: float) -> float:
        """
        Calculate bearing from point 1 to point 2 in degrees (0-360).

        Args:
            lat1, lon1: Starting point coordinates
            lat2, lon2: Ending point coordinates

        Returns:
            Bearing in degrees (0 = North, 90 = East, 180 = South, 270 = West)
        """
        lat1_rad = math.radians(lat1)
        lat2_rad = math.radians(lat2)
        delta_lon = math.radians(lon2 - lon1)

        x = math.sin(delta_lon) * math.cos(lat2_rad)
        y = math.cos(lat1_rad) * math.sin(lat2_rad) - math.sin(lat1_rad) * math.cos(lat2_rad) * math.cos(delta_lon)

        bearing_rad = math.atan2(x, y)
        bearing_deg = (math.degrees(bearing_rad) + 360) % 360

        return bearing_deg

    def calculate_distance(self, lat1: float, lon1: float, lat2: float, lon2: float) -> float:
        """
        Calculate distance between two points using Haversine formula.

        Args:
            lat1, lon1: Starting point coordinates
            lat2, lon2: Ending point coordinates

        Returns:
            Distance in meters
        """
        R = 6371000  # Earth radius in meters

        lat1_rad = math.radians(lat1)
        lat2_rad = math.radians(lat2)
        delta_lat = math.radians(lat2 - lat1)
        delta_lon = math.radians(lon2 - lon1)

        a = math.sin(delta_lat / 2) ** 2 + math.cos(lat1_rad) * math.cos(lat2_rad) * math.sin(delta_lon / 2) ** 2
        c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))

        return R * c

    def update(self, dt: float) -> Dict[str, Any]:
        """
        Update drone position based on elapsed time.

        Args:
            dt: Time delta in seconds since last update

        Returns:
            Dictionary containing current telemetry for message generation
        """
        if self.completed:
            return self._get_current_telemetry()

        # Handle dwelling at waypoint
        if self.is_dwelling:
            self.dwell_timer += dt
            current_wp = self.waypoints[self.current_waypoint_idx]
            dwell_time = current_wp.get("dwell_time", 0.0)

            if self.dwell_timer >= dwell_time:
                self.is_dwelling = False
                self.dwell_timer = 0.0
                # Move to next waypoint
                self.current_waypoint_idx = self.next_waypoint_idx
                self.next_waypoint_idx = (self.next_waypoint_idx + 1) % len(self.waypoints)
                self.interpolation_progress = 0.0

                # Check if we've completed the route
                if not self.loop and self.current_waypoint_idx == len(self.waypoints) - 1:
                    self.completed = True

            return self._get_current_telemetry()

        # Interpolate between waypoints
        current_wp = self.waypoints[self.current_waypoint_idx]
        next_wp = self.waypoints[self.next_waypoint_idx]

        # Calculate distance and time to next waypoint
        distance = self.calculate_distance(
            current_wp["latitude"], current_wp["longitude"],
            next_wp["latitude"], next_wp["longitude"]
        )

        if distance < 0.1:  # Less than 10cm, consider reached
            self.is_dwelling = True
            return self._get_current_telemetry()

        # Calculate progress increment based on speed and distance
        travel_time = distance / self.cruise_speed if self.cruise_speed > 0 else 1.0
        progress_increment = dt / travel_time if travel_time > 0 else 1.0

        self.interpolation_progress += progress_increment

        if self.interpolation_progress >= 1.0:
            # Reached next waypoint
            self.interpolation_progress = 0.0
            self.is_dwelling = True

        return self._get_current_telemetry()

    def _get_current_telemetry(self) -> Dict[str, Any]:
        """Generate telemetry data for current position."""
        current_wp = self.waypoints[self.current_waypoint_idx]
        next_wp = self.waypoints[self.next_waypoint_idx]

        # Interpolate position
        if self.is_dwelling or self.completed:
            lat = current_wp["latitude"]
            lon = current_wp["longitude"]
            alt = current_wp.get("altitude", self.cruise_altitude)
            speed = 0.0
            vert_speed = 0.0
        else:
            t = self.interpolation_progress
            lat = current_wp["latitude"] + t * (next_wp["latitude"] - current_wp["latitude"])
            lon = current_wp["longitude"] + t * (next_wp["longitude"] - current_wp["longitude"])
            alt = current_wp.get("altitude", self.cruise_altitude)
            speed = self.cruise_speed
            vert_speed = 0.0  # Simplified, could interpolate altitude changes

        # Calculate heading
        direction = self.calculate_bearing(
            current_wp["latitude"], current_wp["longitude"],
            next_wp["latitude"], next_wp["longitude"]
        ) if not self.is_dwelling else 0.0

        return {
            "latitude": lat,
            "longitude": lon,
            "altitude": alt,
            "altitude_agl": self.altitude_agl,
            "speed": speed,
            "vert_speed": vert_speed,
            "direction": int(direction)
        }

    def generate_message(self) -> List[Dict[str, Any]]:
        """Generate complete ZMQ message list for current position."""
        telemetry = self._get_current_telemetry()

        message = []

        # Basic ID
        message.append({"Basic ID": self.drone_config["Basic ID"]})

        # Location/Vector Message
        loc_msg = {
            "latitude": telemetry["latitude"],
            "longitude": telemetry["longitude"],
            "speed": telemetry["speed"],
            "vert_speed": telemetry["vert_speed"],
            "geodetic_altitude": telemetry["altitude"],
            "height_agl": telemetry["altitude_agl"],
            "op_status": "Airborne",
            "height_type": "Above Takeoff",
            "ew_dir_segment": "East",
            "direction": telemetry["direction"],
            "speed_multiplier": "0.25 m/s",
            "pressure_altitude": f"{telemetry['altitude'] - 1.5:.1f} m",
            "vertical_accuracy": "< 1 m",
            "horizontal_accuracy": "< 3 m",
            "baro_accuracy": "< 1 m",
            "speed_accuracy": "< 0.3 m/s",
            "timestamp": "0.0 seconds past the hour",
            "timestamp_accuracy": "0.1 seconds"
        }
        message.append({"Location/Vector Message": loc_msg})

        # Frequency Message
        if "frequency" in self.drone_config:
            message.append({"Frequency Message": {"frequency": self.drone_config["frequency"]}})

        # Self-ID Message
        if "self_id_text" in self.drone_config:
            message.append({"Self-ID Message": {"text": self.drone_config["self_id_text"]}})

        # System Message (pilot and home)
        pilot_loc = self.drone_config.get("pilot_location", {})
        home_loc = self.drone_config.get("home_location", {})
        if pilot_loc and home_loc:
            system_msg = {
                "latitude": pilot_loc["latitude"],
                "longitude": pilot_loc["longitude"],
                "home_lat": home_loc["latitude"],
                "home_lon": home_loc["longitude"]
            }
            message.append({"System Message": system_msg})

        # Operator ID Message
        if "operator_id_type" in self.drone_config and "operator_id" in self.drone_config:
            op_msg = {
                "operator_id_type": self.drone_config["operator_id_type"],
                "operator_id": self.drone_config["operator_id"]
            }
            message.append({"Operator ID Message": op_msg})

        return message


class TestDroneGenerator:
    """Main generator class for publishing test drone messages to ZMQ."""

    def __init__(
        self,
        zmq_host: str = "127.0.0.1",
        zmq_port: int = 4224,
        scenario_file: str = "test_scenarios.json",
        mode: str = "replay",
        interval: float = 2.0,
        loop: bool = False,
        dry_run: bool = False
    ):
        """
        Initialize test drone generator.

        Args:
            zmq_host: ZMQ server host
            zmq_port: ZMQ server port for telemetry
            scenario_file: Path to JSON scenario file
            mode: "replay" for static detections, "simulate" for animated tracks
            interval: Seconds between messages in replay mode
            loop: Whether to loop scenarios
            dry_run: Print messages to stdout instead of sending via ZMQ
        """
        self.zmq_host = zmq_host
        self.zmq_port = zmq_port
        self.scenario_file = scenario_file
        self.mode = mode
        self.interval = interval
        self.loop = loop
        self.dry_run = dry_run
        self.running = False
        self.message_count = 0

        # Load scenarios
        with open(scenario_file, 'r') as f:
            self.scenarios = json.load(f)

        # Setup ZMQ publisher only if not in dry-run mode
        if not self.dry_run:
            self.context = zmq.Context()
            self.socket = self.context.socket(zmq.PUB)
            self.socket.bind(f"tcp://{zmq_host}:{zmq_port}")
            logger.info(f"Test drone generator initialized on tcp://{zmq_host}:{zmq_port}")
            # Give ZMQ time to establish
            time.sleep(0.5)
        else:
            self.context = None
            self.socket = None
            logger.info(f"Test drone generator in DRY-RUN mode (no ZMQ)")

        logger.info(f"Mode: {mode}, Interval: {interval}s, Loop: {loop}")

    def run_replay_mode(self):
        """Run in replay mode - send static detections cyclically."""
        static_detections = self.scenarios["scenarios"]["static_detections"]
        logger.info(f"Replay mode: {len(static_detections)} static detections loaded")

        iteration = 0
        while self.running:
            iteration += 1
            logger.info(f"=== Replay iteration {iteration} ===")

            for detection in static_detections:
                if not self.running:
                    break

                name = detection.get("name", "Unknown")
                description = detection.get("description", "")

                # Send or print message
                message = detection["messages"]
                self.message_count += 1

                if self.dry_run:
                    print(f"\n{'='*70}")
                    print(f"[{self.message_count}] {name}")
                    if description:
                        print(f"    {description}")
                    print(f"{'='*70}")
                    print(json.dumps(message, indent=2))
                else:
                    logger.info(f"Publishing: {name}")
                    self.socket.send_json(message)

                time.sleep(self.interval)

            if not self.loop:
                logger.info("Single replay complete (loop disabled)")
                break

            if self.running and self.loop:
                logger.info("Replay cycle complete, restarting...")
                time.sleep(self.interval)

    def run_simulate_mode(self):
        """Run in simulate mode - animate drone tracks."""
        animated_tracks = self.scenarios["scenarios"]["animated_tracks"]
        logger.info(f"Simulate mode: {len(animated_tracks)} animated tracks loaded")

        # Create simulators for each track
        simulators = [DroneSimulator(track) for track in animated_tracks]

        update_interval = 1.0  # Update every second for smooth movement
        last_update = time.time()

        logger.info("Starting simulation...")
        for sim in simulators:
            logger.info(f"  - {sim.name}: {len(sim.waypoints)} waypoints, {sim.cruise_speed} m/s")

        while self.running:
            current_time = time.time()
            dt = current_time - last_update
            last_update = current_time

            # Update all simulators
            for sim in simulators:
                if sim.completed and not self.loop:
                    continue

                # Reset if completed and looping
                if sim.completed and self.loop:
                    sim.completed = False
                    sim.current_waypoint_idx = 0
                    sim.next_waypoint_idx = 1
                    sim.interpolation_progress = 0.0
                    logger.info(f"Restarting track: {sim.name}")

                # Update position
                sim.update(dt)

                # Generate and send message
                message = sim.generate_message()
                self.message_count += 1
                telemetry = sim._get_current_telemetry()

                if self.dry_run:
                    print(f"\n[{self.message_count}] {sim.name} @ {time.strftime('%H:%M:%S')}")
                    print(f"  Position: ({telemetry['latitude']:.6f}, {telemetry['longitude']:.6f}) Alt: {telemetry['altitude']:.1f}m")
                    print(f"  Speed: {telemetry['speed']:.1f}m/s  Heading: {telemetry['direction']}°")
                    if sim.is_dwelling:
                        print(f"  Status: DWELLING at waypoint {sim.current_waypoint_idx}")
                    else:
                        print(f"  Status: En route to waypoint {sim.next_waypoint_idx} (progress: {sim.interpolation_progress*100:.1f}%)")
                else:
                    self.socket.send_json(message)
                    # Log position periodically
                    logger.debug(f"{sim.name}: lat={telemetry['latitude']:.6f}, "
                               f"lon={telemetry['longitude']:.6f}, "
                               f"alt={telemetry['altitude']:.1f}m, "
                               f"speed={telemetry['speed']:.1f}m/s, "
                               f"hdg={telemetry['direction']}°")

            # Check if all completed (non-loop mode)
            if not self.loop and all(sim.completed for sim in simulators):
                logger.info("All simulations complete (loop disabled)")
                break

            time.sleep(update_interval)

    def start(self):
        """Start the generator based on selected mode."""
        self.running = True

        try:
            if self.mode == "replay":
                self.run_replay_mode()
            elif self.mode == "simulate":
                self.run_simulate_mode()
            else:
                logger.error(f"Invalid mode: {self.mode}")
                sys.exit(1)

        except KeyboardInterrupt:
            logger.info("Interrupted by user")
        except Exception as e:
            logger.exception(f"Error in generator: {e}")
        finally:
            self.stop()

    def stop(self):
        """Stop the generator and cleanup."""
        self.running = False
        logger.info("Stopping generator...")

        if self.dry_run:
            print(f"\n{'='*70}")
            print(f"DRY-RUN COMPLETE: {self.message_count} messages generated")
            print(f"{'='*70}")

        if self.socket:
            self.socket.close()
        if self.context:
            self.context.term()

        logger.info("Generator stopped")


def setup_logging(debug: bool):
    """Configure logging."""
    level = logging.DEBUG if debug else logging.INFO
    logging.basicConfig(
        level=level,
        format='%(asctime)s - %(levelname)s - %(name)s - %(message)s'
    )


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Test Drone Detection Message Generator for DragonSync",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Replay static detections once
  python test_drone_generator.py --scenario test_scenarios.json --mode replay

  # Replay static detections in loop
  python test_drone_generator.py --mode replay --loop

  # Simulate animated tracks
  python test_drone_generator.py --mode simulate --loop

  # Custom ZMQ endpoint with faster interval
  python test_drone_generator.py --zmq-host 192.168.1.100 --zmq-port 4224 --interval 1.0
        """
    )

    parser.add_argument(
        "-s", "--scenario",
        type=str,
        default="test_scenarios.json",
        help="Path to scenario JSON file (default: test_scenarios.json)"
    )
    parser.add_argument(
        "-m", "--mode",
        type=str,
        choices=["replay", "simulate"],
        default="replay",
        help="Generator mode: 'replay' for static detections, 'simulate' for animated tracks (default: replay)"
    )
    parser.add_argument(
        "--zmq-host",
        type=str,
        default="127.0.0.1",
        help="ZMQ server host (default: 127.0.0.1)"
    )
    parser.add_argument(
        "--zmq-port",
        type=int,
        default=4224,
        help="ZMQ server port for telemetry (default: 4224)"
    )
    parser.add_argument(
        "-i", "--interval",
        type=float,
        default=2.0,
        help="Interval between messages in replay mode, seconds (default: 2.0)"
    )
    parser.add_argument(
        "-l", "--loop",
        action="store_true",
        help="Loop scenarios continuously"
    )
    parser.add_argument(
        "-d", "--debug",
        action="store_true",
        help="Enable debug logging"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print messages to stdout instead of sending via ZMQ (useful for testing without ZMQ)"
    )

    args = parser.parse_args()

    setup_logging(args.debug)

    # Create and run generator
    generator = TestDroneGenerator(
        zmq_host=args.zmq_host,
        zmq_port=args.zmq_port,
        scenario_file=args.scenario,
        mode=args.mode,
        interval=args.interval,
        loop=args.loop,
        dry_run=args.dry_run
    )

    # Setup signal handlers
    def signal_handler(sig, frame):
        logger.info("Received signal, stopping...")
        generator.stop()
        sys.exit(0)

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    # Start generator
    generator.start()


if __name__ == "__main__":
    main()
