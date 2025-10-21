#!/usr/bin/env python3
"""
MIT License

Copyright (c) 2025 cemaxecuter

Drone Scenario Generator for DragonSync Testing

Generates realistic drone flight scenarios with randomized flight paths based on
a starting latitude/longitude coordinate. Creates scenario files compatible with
test_drone_generator.py.

Usage:
    python generate_scenario.py --lat 41.901 --lon -70.678
    python generate_scenario.py --lat 42.901 --lon -70.678 --seed 12345
"""

import argparse
import json
import math
import random
import sys
from typing import List, Dict, Any, Tuple


# Constants
EARTH_RADIUS_M = 6371000  # meters
FEET_TO_METERS = 0.3048
MILES_TO_METERS = 1609.34

# Drone configuration
HOME_RADIUS_MILES = 1.0
PILOT_RADIUS_FEET = 100.0
MIN_ALTITUDE_FEET = 50.0
MAX_ALTITUDE_FEET = 400.0
MIN_SPEED_MS = 5.0
MAX_SPEED_MS = 25.0
MIN_FLIGHT_TIME_SEC = 120  # 2 minutes
MAX_FLIGHT_TIME_SEC = 240  # 4 minutes
MIN_PATH_DISTANCE_FEET = 50.0
MAX_PATH_DISTANCE_FEET = 5000.0

# Frequency options (in Hz)
DRONE_FREQUENCIES = [
    2412000000.0,  # 2.4 GHz WiFi
    2437000000.0,
    2462000000.0,
    5745000000.0,  # 5.8 GHz
    5805000000.0,
    5825000000.0,
]

# Drone manufacturers and models
DRONE_MODELS = [
    {"manufacturer": "DJI", "model": "Mavic 3", "prefix": "1581F6BV"},
    {"manufacturer": "DJI", "model": "Phantom 4", "prefix": "P4P2024"},
    {"manufacturer": "Autel", "model": "EVO II", "prefix": "AUTEL2024EV2"},
    {"manufacturer": "Skydio", "model": "X2", "prefix": "SKY2024X2"},
    {"manufacturer": "Parrot", "model": "ANAFI", "prefix": "PA2024ANF"},
]


def lat_lon_to_radians(lat: float, lon: float) -> Tuple[float, float]:
    """Convert latitude and longitude to radians."""
    return math.radians(lat), math.radians(lon)


def radians_to_lat_lon(lat_rad: float, lon_rad: float) -> Tuple[float, float]:
    """Convert radians to latitude and longitude."""
    return math.degrees(lat_rad), math.degrees(lon_rad)


def calculate_bearing(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """
    Calculate bearing from point 1 to point 2 in degrees.

    Returns:
        Bearing in degrees (0 = North, 90 = East, 180 = South, 270 = West)
    """
    lat1_rad, lon1_rad = lat_lon_to_radians(lat1, lon1)
    lat2_rad, lon2_rad = lat_lon_to_radians(lat2, lon2)

    delta_lon = lon2_rad - lon1_rad

    x = math.sin(delta_lon) * math.cos(lat2_rad)
    y = math.cos(lat1_rad) * math.sin(lat2_rad) - math.sin(lat1_rad) * math.cos(lat2_rad) * math.cos(delta_lon)

    bearing_rad = math.atan2(x, y)
    bearing_deg = (math.degrees(bearing_rad) + 360) % 360

    return bearing_deg


def calculate_distance(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """
    Calculate distance between two points using Haversine formula.

    Returns:
        Distance in meters
    """
    lat1_rad, lon1_rad = lat_lon_to_radians(lat1, lon1)
    lat2_rad, lon2_rad = lat_lon_to_radians(lat2, lon2)

    delta_lat = lat2_rad - lat1_rad
    delta_lon = lon2_rad - lon1_rad

    a = math.sin(delta_lat / 2) ** 2 + math.cos(lat1_rad) * math.cos(lat2_rad) * math.sin(delta_lon / 2) ** 2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))

    return EARTH_RADIUS_M * c


def point_at_distance_and_bearing(lat: float, lon: float, distance_m: float, bearing_deg: float) -> Tuple[float, float]:
    """
    Calculate a new point given a starting point, distance, and bearing.

    Args:
        lat: Starting latitude
        lon: Starting longitude
        distance_m: Distance in meters
        bearing_deg: Bearing in degrees (0 = North)

    Returns:
        (new_lat, new_lon) tuple
    """
    lat_rad, lon_rad = lat_lon_to_radians(lat, lon)
    bearing_rad = math.radians(bearing_deg)

    angular_distance = distance_m / EARTH_RADIUS_M

    new_lat_rad = math.asin(
        math.sin(lat_rad) * math.cos(angular_distance) +
        math.cos(lat_rad) * math.sin(angular_distance) * math.cos(bearing_rad)
    )

    new_lon_rad = lon_rad + math.atan2(
        math.sin(bearing_rad) * math.sin(angular_distance) * math.cos(lat_rad),
        math.cos(angular_distance) - math.sin(lat_rad) * math.sin(new_lat_rad)
    )

    return radians_to_lat_lon(new_lat_rad, new_lon_rad)


def random_point_within_radius(center_lat: float, center_lon: float, radius_m: float) -> Tuple[float, float]:
    """
    Generate a random point within a given radius of a center point.

    Args:
        center_lat: Center latitude
        center_lon: Center longitude
        radius_m: Radius in meters

    Returns:
        (lat, lon) tuple
    """
    # Random distance (using square root for uniform distribution)
    random_distance = math.sqrt(random.random()) * radius_m

    # Random bearing
    random_bearing = random.random() * 360

    return point_at_distance_and_bearing(center_lat, center_lon, random_distance, random_bearing)


def generate_mac_address(prefix: str = None) -> str:
    """Generate a random MAC address."""
    if prefix:
        # Use provided prefix (e.g., "60:60:1F")
        suffix = ":".join([f"{random.randint(0, 255):02X}" for _ in range(3)])
        return f"{prefix}:{suffix}"
    else:
        return ":".join([f"{random.randint(0, 255):02X}" for _ in range(6)])


def generate_serial_number(prefix: str, length: int = 16) -> str:
    """Generate a random serial number with given prefix."""
    remaining = length - len(prefix)
    chars = "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
    suffix = "".join(random.choice(chars) for _ in range(remaining))
    return prefix + suffix


def generate_operator_id() -> str:
    """Generate a random operator ID."""
    year = 2024
    country = "US"
    number = random.randint(10000, 99999)
    return f"OP-{year}-{country}-{number}"


def generate_drone_config(drone_model: Dict[str, str], home_lat: float, home_lon: float,
                         pilot_lat: float, pilot_lon: float, altitude_agl: float) -> Dict[str, Any]:
    """
    Generate a complete drone configuration.

    Args:
        drone_model: Dict with manufacturer, model, and prefix
        home_lat, home_lon: Home location coordinates
        pilot_lat, pilot_lon: Pilot location coordinates
        altitude_agl: Altitude above ground level in feet

    Returns:
        Drone configuration dictionary
    """
    serial = generate_serial_number(drone_model["prefix"])

    # Generate MAC with manufacturer prefix patterns
    mac_prefixes = {
        "DJI": "60:60:1F",
        "Autel": "A4:C1:38",
        "Skydio": "B8:27:EB",
        "Parrot": "90:3A:E6",
    }
    mac_prefix = mac_prefixes.get(drone_model["manufacturer"])
    mac = generate_mac_address(mac_prefix)

    return {
        "Basic ID": {
            "id_type": "Serial Number (ANSI/CTA-2063-A)",
            "id": serial,
            "ua_type": 2,
            "MAC": mac,
            "RSSI": random.randint(-75, -55)
        },
        "frequency": random.choice(DRONE_FREQUENCIES),
        "self_id_text": f"{drone_model['manufacturer']} {drone_model['model']} Flight",
        "operator_id_type": "Operator ID",
        "operator_id": generate_operator_id(),
        "pilot_location": {
            "latitude": pilot_lat,
            "longitude": pilot_lon
        },
        "home_location": {
            "latitude": home_lat,
            "longitude": home_lon
        }
    }


def generate_grid_pattern(home_lat: float, home_lon: float, speed_ms: float,
                         altitude_m: float, duration_sec: float) -> List[Dict[str, Any]]:
    """
    Generate a grid pattern flight path.

    Args:
        home_lat, home_lon: Home location (start/end point)
        speed_ms: Cruise speed in m/s
        altitude_m: Altitude in meters
        duration_sec: Target flight duration in seconds

    Returns:
        List of waypoint dictionaries
    """
    waypoints = []

    # Calculate grid parameters
    total_distance = speed_ms * duration_sec
    min_distance_m = MIN_PATH_DISTANCE_FEET * FEET_TO_METERS
    max_distance_m = MAX_PATH_DISTANCE_FEET * FEET_TO_METERS

    # Grid will be roughly square, with 3-5 rows
    num_rows = random.randint(3, 5)
    row_spacing_m = random.uniform(min_distance_m * 0.5, max_distance_m * 0.8 / num_rows)

    # Calculate grid dimensions
    grid_width_m = random.uniform(min_distance_m, max_distance_m)

    # Start at home
    waypoints.append({
        "latitude": home_lat,
        "longitude": home_lon,
        "altitude": altitude_m,
        "dwell_time": 2.0,
        "description": "Grid start - Home"
    })

    # Generate grid pattern (lawn mower pattern)
    current_bearing = random.randint(0, 360)  # Random initial direction

    for row in range(num_rows):
        # Determine direction (alternate for lawn mower pattern)
        if row % 2 == 0:
            direction = current_bearing
        else:
            direction = (current_bearing + 180) % 360

        # Calculate row offset
        row_offset_bearing = (current_bearing + 90) % 360
        row_offset_distance = row * row_spacing_m

        # Start of row
        start_lat, start_lon = point_at_distance_and_bearing(
            home_lat, home_lon, row_offset_distance, row_offset_bearing
        )

        if row % 2 == 0:
            # Move to start of row
            waypoints.append({
                "latitude": start_lat,
                "longitude": start_lon,
                "altitude": altitude_m,
                "dwell_time": 1.0,
                "description": f"Grid row {row + 1} start"
            })

            # End of row
            end_lat, end_lon = point_at_distance_and_bearing(
                start_lat, start_lon, grid_width_m, direction
            )
        else:
            # For odd rows, start from the other end
            start_lat, start_lon = point_at_distance_and_bearing(
                start_lat, start_lon, grid_width_m, current_bearing
            )

            waypoints.append({
                "latitude": start_lat,
                "longitude": start_lon,
                "altitude": altitude_m,
                "dwell_time": 1.0,
                "description": f"Grid row {row + 1} start"
            })

            end_lat, end_lon = point_at_distance_and_bearing(
                start_lat, start_lon, grid_width_m, direction
            )

        waypoints.append({
            "latitude": end_lat,
            "longitude": end_lon,
            "altitude": altitude_m,
            "dwell_time": 1.0,
            "description": f"Grid row {row + 1} end"
        })

    # Return to home
    waypoints.append({
        "latitude": home_lat,
        "longitude": home_lon,
        "altitude": altitude_m,
        "dwell_time": 3.0,
        "description": "Return to home"
    })

    return waypoints


def generate_circular_pattern(home_lat: float, home_lon: float, speed_ms: float,
                              altitude_m: float, duration_sec: float) -> List[Dict[str, Any]]:
    """
    Generate a circular pattern flight path.

    Args:
        home_lat, home_lon: Home location (start/end point)
        speed_ms: Cruise speed in m/s
        altitude_m: Altitude in meters
        duration_sec: Target flight duration in seconds

    Returns:
        List of waypoint dictionaries
    """
    waypoints = []

    # Calculate circle parameters
    min_distance_m = MIN_PATH_DISTANCE_FEET * FEET_TO_METERS
    max_distance_m = MAX_PATH_DISTANCE_FEET * FEET_TO_METERS

    # Calculate total distance available based on duration and speed
    total_distance_available = speed_ms * duration_sec

    # Circle circumference = 2 * pi * radius
    # We want circumference to fit within duration, accounting for return to home
    # Reserve some distance for going from home to circle and back
    travel_margin = 0.8  # 80% of distance for circle, 20% for travel to/from
    circle_circumference = total_distance_available * travel_margin

    # Calculate radius from circumference: r = C / (2 * pi)
    calculated_radius_m = circle_circumference / (2 * math.pi)

    # Clamp radius to min/max distance constraints
    radius_m = max(min_distance_m, min(calculated_radius_m, max_distance_m * 0.7))

    # Number of waypoints around the circle (8-16 for smooth circle)
    num_points = random.randint(8, 12)
    angle_step = 360 / num_points

    # Random starting bearing
    start_bearing = random.randint(0, 360)

    # Start at home
    waypoints.append({
        "latitude": home_lat,
        "longitude": home_lon,
        "altitude": altitude_m,
        "dwell_time": 2.0,
        "description": "Circular pattern start - Home"
    })

    # Generate circle waypoints
    for i in range(num_points):
        bearing = (start_bearing + i * angle_step) % 360
        lat, lon = point_at_distance_and_bearing(home_lat, home_lon, radius_m, bearing)

        dwell_time = 1.5 if i % 4 == 0 else 0.5  # Longer dwell at cardinal points

        waypoints.append({
            "latitude": lat,
            "longitude": lon,
            "altitude": altitude_m,
            "dwell_time": dwell_time,
            "description": f"Circle point {i + 1} ({int(bearing)}°)"
        })

    # Return to home
    waypoints.append({
        "latitude": home_lat,
        "longitude": home_lon,
        "altitude": altitude_m,
        "dwell_time": 3.0,
        "description": "Return to home"
    })

    return waypoints


def generate_point_to_point_pattern(home_lat: float, home_lon: float, speed_ms: float,
                                    altitude_m: float, duration_sec: float) -> List[Dict[str, Any]]:
    """
    Generate a point-to-point pattern flight path (out and back with waypoints).

    Args:
        home_lat, home_lon: Home location (start/end point)
        speed_ms: Cruise speed in m/s
        altitude_m: Altitude in meters
        duration_sec: Target flight duration in seconds

    Returns:
        List of waypoint dictionaries
    """
    waypoints = []

    min_distance_m = MIN_PATH_DISTANCE_FEET * FEET_TO_METERS
    max_distance_m = MAX_PATH_DISTANCE_FEET * FEET_TO_METERS

    # Calculate total distance available based on duration and speed
    total_distance_available = speed_ms * duration_sec

    # Number of waypoints (3-5 points before returning)
    num_points = random.randint(3, 5)

    # Allocate distance budget (half for outbound, half for return, with some margin)
    outbound_distance_budget = total_distance_available * 0.4  # 40% for outbound
    distance_per_segment = outbound_distance_budget / num_points

    # Ensure segments are within bounds
    distance_per_segment = max(min_distance_m * 0.3, min(distance_per_segment, max_distance_m * 0.3))

    # Start at home
    waypoints.append({
        "latitude": home_lat,
        "longitude": home_lon,
        "altitude": altitude_m,
        "dwell_time": 2.0,
        "description": "Point-to-point start - Home"
    })

    # Generate outbound waypoints
    current_lat, current_lon = home_lat, home_lon

    for i in range(num_points):
        # Random bearing (but generally in the same direction for a realistic flight)
        if i == 0:
            bearing = random.randint(0, 360)
            base_bearing = bearing
        else:
            # Vary bearing slightly (±30 degrees) for natural flight path
            bearing = (base_bearing + random.randint(-30, 30)) % 360

        # Random distance between points (with some variation)
        distance_m = distance_per_segment * random.uniform(0.7, 1.3)

        # Ensure we don't go too far from home
        distance_from_home = calculate_distance(home_lat, home_lon, current_lat, current_lon)
        if distance_from_home + distance_m > max_distance_m:
            distance_m = max(min_distance_m * 0.3, max_distance_m - distance_from_home)

        new_lat, new_lon = point_at_distance_and_bearing(current_lat, current_lon, distance_m, bearing)

        dwell_time = random.uniform(1.5, 3.0) if i == num_points - 1 else random.uniform(0.5, 1.5)

        waypoints.append({
            "latitude": new_lat,
            "longitude": new_lon,
            "altitude": altitude_m,
            "dwell_time": dwell_time,
            "description": f"Waypoint {i + 1}" if i < num_points - 1 else f"Destination {i + 1}"
        })

        current_lat, current_lon = new_lat, new_lon

    # Return to home (can add intermediate waypoints on return path)
    # Add 1-2 intermediate waypoints on return for realism
    num_return_points = random.randint(1, 2)
    return_distance = calculate_distance(current_lat, current_lon, home_lat, home_lon)

    for i in range(num_return_points):
        # Interpolate between current position and home
        progress = (i + 1) / (num_return_points + 1)
        interp_lat = current_lat + progress * (home_lat - current_lat)
        interp_lon = current_lon + progress * (home_lon - current_lon)

        waypoints.append({
            "latitude": interp_lat,
            "longitude": interp_lon,
            "altitude": altitude_m,
            "dwell_time": 0.5,
            "description": f"Return waypoint {i + 1}"
        })

    # Final return to home
    waypoints.append({
        "latitude": home_lat,
        "longitude": home_lon,
        "altitude": altitude_m,
        "dwell_time": 3.0,
        "description": "Return to home"
    })

    return waypoints


def generate_scenario(center_lat: float, center_lon: float, seed: int = None) -> Dict[str, Any]:
    """
    Generate a complete scenario with 3 drones.

    Args:
        center_lat: Center latitude for scenario
        center_lon: Center longitude for scenario
        seed: Optional random seed for reproducibility

    Returns:
        Complete scenario dictionary
    """
    if seed is not None:
        random.seed(seed)

    # Generate 3 unique altitudes
    altitudes_feet = random.sample(range(int(MIN_ALTITUDE_FEET), int(MAX_ALTITUDE_FEET) + 1), 3)
    altitudes_m = [alt * FEET_TO_METERS for alt in altitudes_feet]

    # Generate 3 unique speeds
    speeds_ms = [random.uniform(MIN_SPEED_MS, MAX_SPEED_MS) for _ in range(3)]

    # Generate 3 flight durations
    durations_sec = [random.uniform(MIN_FLIGHT_TIME_SEC, MAX_FLIGHT_TIME_SEC) for _ in range(3)]

    # Select 3 different drone models
    selected_models = random.sample(DRONE_MODELS, 3)

    animated_tracks = []

    pattern_generators = [
        ("Grid Pattern", generate_grid_pattern),
        ("Circular Pattern", generate_circular_pattern),
        ("Point-to-Point Pattern", generate_point_to_point_pattern),
    ]

    for idx, (pattern_name, pattern_func) in enumerate(pattern_generators):
        # Generate random home location within radius
        home_lat, home_lon = random_point_within_radius(
            center_lat, center_lon, HOME_RADIUS_MILES * MILES_TO_METERS
        )

        # Generate random pilot location near home
        pilot_lat, pilot_lon = random_point_within_radius(
            home_lat, home_lon, PILOT_RADIUS_FEET * FEET_TO_METERS
        )

        # Generate drone config
        drone_config = generate_drone_config(
            selected_models[idx],
            home_lat, home_lon,
            pilot_lat, pilot_lon,
            altitudes_feet[idx]
        )

        # Generate flight path
        waypoints = pattern_func(
            home_lat, home_lon,
            speeds_ms[idx],
            altitudes_m[idx],
            durations_sec[idx]
        )

        # Create track
        track = {
            "name": f"{selected_models[idx]['manufacturer']} {selected_models[idx]['model']} - {pattern_name}",
            "description": f"Drone following {pattern_name.lower()} at {speeds_ms[idx]:.1f} m/s, {altitudes_feet[idx]:.0f} ft AGL",
            "drone_config": drone_config,
            "flight_path": {
                "cruise_speed": speeds_ms[idx],
                "cruise_altitude": altitudes_m[idx],
                "altitude_agl": altitudes_m[idx] * 0.75,  # Approximate AGL (simplified)
                "waypoints": waypoints,
                "loop": True
            }
        }

        animated_tracks.append(track)

    scenario = {
        "description": f"Generated drone scenario centered at ({center_lat:.6f}, {center_lon:.6f})",
        "scenarios": {
            "static_detections": [],
            "animated_tracks": animated_tracks
        }
    }

    return scenario


def format_coordinate_for_filename(coord: float) -> str:
    """
    Format coordinate for filename (4 digits, removing decimal).
    Example: 42.216 -> 4221, -70.902 -> -7090
    """
    # Take first 4 significant digits
    abs_coord = abs(coord)

    # Convert to string and remove decimal
    coord_str = f"{abs_coord:.2f}".replace(".", "")

    # Take first 4 digits
    coord_str = coord_str[:4].ljust(4, "0")

    # Add negative sign if needed
    if coord < 0:
        coord_str = "-" + coord_str

    return coord_str


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Generate drone scenario files for DragonSync testing",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Generate scenario at specific coordinates
  python generate_scenario.py --lat 42.216 --lon -70.902

  # Generate with seed for reproducibility
  python generate_scenario.py --lat 42.216 --lon -70.902 --seed 12345

  # Specify output filename
  python generate_scenario.py --lat 42.216 --lon -70.902 --output my_scenario.json
        """
    )

    parser.add_argument(
        "--lat",
        type=float,
        required=True,
        help="Center latitude for scenario"
    )
    parser.add_argument(
        "--lon",
        type=float,
        required=True,
        help="Center longitude for scenario"
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=None,
        help="Random seed for reproducibility (optional)"
    )
    parser.add_argument(
        "--output",
        type=str,
        default=None,
        help="Output filename (default: scenario_XXYY_AABB.json based on coordinates)"
    )

    args = parser.parse_args()

    # Generate scenario
    print(f"Generating scenario centered at ({args.lat}, {args.lon})...")
    if args.seed is not None:
        print(f"Using random seed: {args.seed}")

    scenario = generate_scenario(args.lat, args.lon, args.seed)

    # Determine output filename
    if args.output:
        output_filename = args.output
    else:
        lat_str = format_coordinate_for_filename(args.lat)
        lon_str = format_coordinate_for_filename(args.lon)
        output_filename = f"scenario_{lat_str}_{lon_str}.json"

    # Write to file
    with open(output_filename, 'w') as f:
        json.dump(scenario, f, indent=2)

    print(f"\n✓ Scenario generated successfully: {output_filename}")
    print(f"\nScenario details:")
    print(f"  - {len(scenario['scenarios']['animated_tracks'])} drones")

    for track in scenario['scenarios']['animated_tracks']:
        name = track['name']
        speed = track['flight_path']['cruise_speed']
        altitude = track['flight_path']['cruise_altitude']
        waypoints = len(track['flight_path']['waypoints'])
        print(f"  - {name}")
        print(f"    Speed: {speed:.1f} m/s, Altitude: {altitude:.1f} m, Waypoints: {waypoints}")

    print(f"\nTo test this scenario:")
    print(f"  run_test_scenario.sh --scenario {output_filename} --mode simulate --loop")


if __name__ == "__main__":
    main()
