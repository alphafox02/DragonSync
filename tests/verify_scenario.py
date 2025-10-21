#!/usr/bin/env python3
"""Simple script to verify scenario file constraints."""

import json
import math
import sys

EARTH_RADIUS_M = 6371000
FEET_TO_METERS = 0.3048


def calculate_distance(lat1, lon1, lat2, lon2):
    """Calculate distance using Haversine formula (meters)."""
    lat1_rad = math.radians(lat1)
    lat2_rad = math.radians(lat2)
    delta_lat = math.radians(lat2 - lat1)
    delta_lon = math.radians(lon2 - lon1)

    a = math.sin(delta_lat / 2) ** 2 + math.cos(lat1_rad) * math.cos(lat2_rad) * math.sin(delta_lon / 2) ** 2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))

    return EARTH_RADIUS_M * c


def verify_scenario(filename):
    """Verify scenario constraints."""
    with open(filename, 'r') as f:
        scenario = json.load(f)

    print(f"Verifying: {filename}\n")

    tracks = scenario['scenarios']['animated_tracks']

    for idx, track in enumerate(tracks, 1):
        name = track['name']
        print(f"Drone {idx}: {name}")

        home = track['drone_config']['home_location']
        pilot = track['drone_config']['pilot_location']
        home_lat, home_lon = home['latitude'], home['longitude']
        pilot_lat, pilot_lon = pilot['latitude'], pilot['longitude']

        # Check pilot distance from home
        pilot_distance_m = calculate_distance(home_lat, home_lon, pilot_lat, pilot_lon)
        pilot_distance_ft = pilot_distance_m / FEET_TO_METERS
        print(f"  Pilot distance from home: {pilot_distance_ft:.1f} ft (should be < 100 ft)")

        # Check waypoint distances from home
        waypoints = track['flight_path']['waypoints']
        max_distance_m = 0
        min_distance_m = float('inf')

        for wp in waypoints:
            distance_m = calculate_distance(home_lat, home_lon, wp['latitude'], wp['longitude'])
            max_distance_m = max(max_distance_m, distance_m)
            if distance_m > 1:  # Exclude home waypoint
                min_distance_m = min(min_distance_m, distance_m)

        max_distance_ft = max_distance_m / FEET_TO_METERS
        min_distance_ft = min_distance_m / FEET_TO_METERS

        print(f"  Flight path distance from home: {min_distance_ft:.1f} - {max_distance_ft:.1f} ft")
        print(f"    (should be between 50 - 5000 ft)")

        # Check altitude
        altitude_m = track['flight_path']['cruise_altitude']
        altitude_ft = altitude_m / FEET_TO_METERS
        print(f"  Altitude: {altitude_ft:.0f} ft AGL (should be 50-400 ft)")

        # Check speed
        speed_ms = track['flight_path']['cruise_speed']
        print(f"  Speed: {speed_ms:.1f} m/s (should be 5-25 m/s)")

        # Estimate flight time
        total_distance = 0
        for i in range(len(waypoints) - 1):
            wp1 = waypoints[i]
            wp2 = waypoints[i + 1]
            distance = calculate_distance(wp1['latitude'], wp1['longitude'],
                                        wp2['latitude'], wp2['longitude'])
            total_distance += distance

        flight_time_sec = total_distance / speed_ms if speed_ms > 0 else 0
        flight_time_min = flight_time_sec / 60
        print(f"  Estimated flight time: {flight_time_min:.1f} min (should be 2-4 min)")
        print(f"  Waypoints: {len(waypoints)}")
        print()


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python verify_scenario.py <scenario_file.json>")
        sys.exit(1)

    verify_scenario(sys.argv[1])
