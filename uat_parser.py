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

from typing import Any, Dict, Optional
import logging
from utils import get_float, get_int

logger = logging.getLogger(__name__)

# UAT emitter category to UA type mapping (DO-282B)
UAT_EMITTER_TO_UA_TYPE = {
    0: (15, 'No aircraft type information'),
    1: (1, 'Light (< 15,500 lbs)'),
    2: (1, 'Small (15,500 to 75,000 lbs)'),
    3: (1, 'Large (75,000 to 300,000 lbs)'),
    4: (1, 'High Vortex Large'),
    5: (1, 'Heavy (> 300,000 lbs)'),
    6: (1, 'High Performance (> 5g acceleration and > 400 kts)'),
    7: (2, 'Rotorcraft'),
    8: (6, 'Glider / sailplane'),
    9: (8, 'Lighter-than-air'),
    10: (14, 'Parachutist / skydiver'),
    11: (12, 'Ultralight / hang-glider / paraglider'),
    12: (15, 'Unmanned Aerial Vehicle'),
    13: (15, 'Space / trans-atmospheric vehicle'),
    14: (14, 'Surface vehicle - emergency vehicle'),
    15: (14, 'Surface vehicle - service vehicle'),
    16: (14, 'Point obstacle'),
    17: (14, 'Cluster obstacle'),
    18: (14, 'Line obstacle'),
    19: (15, 'Reserved'),
}


def parse_uat_aircraft(aircraft: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """
    Parse a single aircraft object from dump978 JSON format.
    Returns a normalized dict compatible with DragonSync's Drone model.

    Expected input format from dump978-fa:
    {
        "address": "A12345",       # ICAO 24-bit address
        "address_type": "adsb_icao", # Address type
        "callsign": "N12345",      # Callsign/tail number
        "emitter_category": 1,     # Emitter category code
        "lat": 39.123456,          # Latitude
        "lon": -77.654321,         # Longitude
        "alt_geom": 35200,         # Geometric altitude in feet
        "nic": 8,                  # Navigation Integrity Category
        "nac_p": 9,                # Navigation Accuracy Category - Position
        "nac_v": 2,                # Navigation Accuracy Category - Velocity
        "sil": 3,                  # Source Integrity Level
        "sil_type": "perhour",     # SIL type
        "gs": 450.5,               # Ground speed in knots
        "track": 270.5,            # Track in degrees
        "baro_rate": 0,            # Vertical rate in ft/min
        "squawk": "1234",          # Squawk code
        "emergency": "none",       # Emergency status
        "category": "A3",          # ADS-B category
        "nav_altitude_mcp": 35000, # Selected altitude
        "nav_heading": 270,        # Selected heading
        "seen": 0.5,               # Time since last message
        "rssi": -12.3              # Signal strength
    }
    """
    if not isinstance(aircraft, dict):
        logger.error("Invalid UAT aircraft data: expected dict")
        return None

    # Address is required
    address = aircraft.get('address')
    if not address:
        logger.warning("UAT aircraft missing address, skipping")
        return None

    drone_info: Dict[str, Any] = {}

    # Core identification
    drone_info['id'] = address.upper()
    drone_info['mac'] = address.upper()  # Use address as MAC for compatibility

    # Callsign (strip whitespace)
    callsign = aircraft.get('callsign', '').strip()
    drone_info['callsign'] = callsign if callsign else address

    # Position
    lat = aircraft.get('lat')
    lon = aircraft.get('lon')
    if lat is not None and lon is not None:
        drone_info['lat'] = get_float(lat)
        drone_info['lon'] = get_float(lon)
    else:
        drone_info['lat'] = 0.0
        drone_info['lon'] = 0.0

    # Altitude - UAT typically provides geometric altitude
    # Convert feet to meters (1 ft = 0.3048 m)
    alt_geom = aircraft.get('alt_geom')
    alt_baro = aircraft.get('alt_baro')

    if alt_geom is not None and alt_geom != "ground":
        drone_info['alt'] = get_float(alt_geom) * 0.3048
    elif alt_baro is not None and alt_baro != "ground":
        drone_info['alt'] = get_float(alt_baro) * 0.3048
    else:
        drone_info['alt'] = 0.0

    # Height AGL - for aircraft, assume same as altitude
    drone_info['height'] = drone_info['alt']

    # Ground speed - convert knots to m/s (1 knot = 0.514444 m/s)
    gs = aircraft.get('gs')
    if gs is not None:
        drone_info['speed'] = get_float(gs) * 0.514444
    else:
        drone_info['speed'] = 0.0

    # Vertical speed - convert ft/min to m/s (1 ft/min = 0.00508 m/s)
    baro_rate = aircraft.get('baro_rate')
    geom_rate = aircraft.get('geom_rate')

    if geom_rate is not None:
        drone_info['vspeed'] = get_float(geom_rate) * 0.00508
    elif baro_rate is not None:
        drone_info['vspeed'] = get_float(baro_rate) * 0.00508
    else:
        drone_info['vspeed'] = 0.0

    # Track/heading
    track = aircraft.get('track')
    if track is not None:
        drone_info['direction'] = get_int(track)
    else:
        drone_info['direction'] = None

    # UAT emitter category to UA type mapping
    emitter_category = aircraft.get('emitter_category', 0)
    if emitter_category in UAT_EMITTER_TO_UA_TYPE:
        ua_type, ua_subtype = UAT_EMITTER_TO_UA_TYPE[emitter_category]
        drone_info['ua_type'] = ua_type
        drone_info['ua_type_name'] = f'Aircraft - {ua_subtype}'
    else:
        # Default to fixed-wing aircraft
        drone_info['ua_type'] = 1
        drone_info['ua_type_name'] = 'Aircraft - Unknown Type'

    # Signal strength (RSSI in dBFS)
    rssi = aircraft.get('rssi')
    if rssi is not None:
        drone_info['rssi'] = int(max(-100, min(0, get_float(rssi))))
    else:
        drone_info['rssi'] = -50  # Default moderate signal

    # Squawk code
    squawk = aircraft.get('squawk')
    if squawk:
        drone_info['squawk'] = str(squawk)
    else:
        drone_info['squawk'] = ''

    # Emergency status
    emergency = aircraft.get('emergency', 'none')
    drone_info['emergency'] = emergency

    # Address type
    address_type = aircraft.get('address_type', 'unknown')
    drone_info['address_type'] = address_type

    # Description - combine callsign and emitter info
    desc_parts = []
    if callsign:
        desc_parts.append(f"Flight: {callsign}")
    if squawk:
        desc_parts.append(f"Squawk: {squawk}")
    if emergency and emergency != 'none':
        desc_parts.append(f"EMERGENCY: {emergency.upper()}")
    if emitter_category in UAT_EMITTER_TO_UA_TYPE:
        _, emitter_desc = UAT_EMITTER_TO_UA_TYPE[emitter_category]
        desc_parts.append(f"Type: {emitter_desc}")

    drone_info['description'] = ' | '.join(desc_parts) if desc_parts else f'UAT: {address}'

    # Additional metadata
    drone_info['id_type'] = 'UAT Address'
    drone_info['source'] = 'UAT'
    drone_info['nic'] = aircraft.get('nic', 0)
    drone_info['nac_p'] = aircraft.get('nac_p', 0)
    drone_info['nac_v'] = aircraft.get('nac_v', 0)
    drone_info['sil'] = aircraft.get('sil', 0)
    drone_info['sil_type'] = aircraft.get('sil_type', '')

    # Navigation intent (autopilot settings)
    nav_altitude_mcp = aircraft.get('nav_altitude_mcp')
    if nav_altitude_mcp is not None:
        drone_info['nav_altitude_mcp'] = get_int(nav_altitude_mcp)

    nav_heading = aircraft.get('nav_heading')
    if nav_heading is not None:
        drone_info['nav_heading'] = get_int(nav_heading)

    # Time since last seen
    seen = aircraft.get('seen')
    if seen is not None:
        drone_info['seen'] = get_float(seen)

    # Message count
    messages = aircraft.get('messages')
    if messages is not None:
        drone_info['message_count'] = get_int(messages)

    return drone_info


def parse_uat_message(message: Any) -> Optional[Dict[str, Any]]:
    """
    Parse dump978 JSON message format.
    Returns the first valid aircraft parsed, or None if no valid aircraft found.
    """
    if not message:
        return None

    # Handle full aircraft list format
    if isinstance(message, dict) and 'aircraft' in message:
        aircraft_list = message.get('aircraft', [])
        if not aircraft_list:
            return None

        # Process first aircraft for now (bridge will handle batch processing)
        for aircraft in aircraft_list:
            parsed = parse_uat_aircraft(aircraft)
            if parsed:
                return parsed

        return None

    # Handle single aircraft dict
    elif isinstance(message, dict):
        return parse_uat_aircraft(message)

    else:
        logger.error("Unexpected UAT message format")
        return None
