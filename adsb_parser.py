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

# ADS-B Category to UA type mapping (ICAO Doc 9871)
ADSB_CATEGORY_TO_UA_TYPE = {
    # Category A (Powered aircraft)
    'A0': (1, 'Light'),
    'A1': (1, 'Small'),
    'A2': (1, 'Large'),
    'A3': (1, 'High Vortex Large'),
    'A4': (1, 'Heavy'),
    'A5': (1, 'High Performance'),
    'A6': (2, 'Rotorcraft'),
    'A7': (1, 'Reserved'),
    # Category B (Unpowered aircraft/balloons)
    'B0': (8, 'Reserved'),
    'B1': (6, 'Glider/Sailplane'),
    'B2': (8, 'Lighter-than-Air'),
    'B3': (14, 'Parachutist/Skydiver'),
    'B4': (12, 'Ultralight/hang-glider/paraglider'),
    'B5': (1, 'Reserved'),
    'B6': (12, 'Unmanned Aerial Vehicle'),
    'B7': (15, 'Space/Trans-atmospheric vehicle'),
    # Category C (Ground vehicles)
    'C0': (14, 'Reserved'),
    'C1': (14, 'Surface Vehicle - Emergency Vehicle'),
    'C2': (14, 'Surface Vehicle - Service Vehicle'),
    'C3': (14, 'Point Obstacle'),
    'C4': (14, 'Cluster Obstacle'),
    'C5': (14, 'Line Obstacle'),
    'C6': (14, 'Reserved'),
    'C7': (14, 'Reserved'),
    # Category D (Reserved)
    'D0': (15, 'Reserved'),
    'D1': (15, 'Reserved'),
    'D2': (15, 'Reserved'),
    'D3': (15, 'Reserved'),
    'D4': (15, 'Reserved'),
    'D5': (15, 'Reserved'),
    'D6': (15, 'Reserved'),
    'D7': (15, 'Reserved'),
}

def parse_adsb_aircraft(aircraft: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """
    Parse a single aircraft object from dump1090/readsb JSON format.
    Returns a normalized dict compatible with DragonSync's Drone model.
    """
    if not isinstance(aircraft, dict):
        logger.error("Invalid aircraft data: expected dict")
        return None

    # ICAO address is required
    icao_hex = aircraft.get('hex')
    if not icao_hex:
        logger.warning("Aircraft missing ICAO hex address, skipping")
        return None

    drone_info: Dict[str, Any] = {}

    # Core identification
    drone_info['id'] = icao_hex.upper()
    drone_info['mac'] = icao_hex.upper()  # Use ICAO as MAC for compatibility

    # Callsign (strip whitespace)
    callsign = aircraft.get('flight', '').strip()
    drone_info['callsign'] = callsign if callsign else icao_hex

    # Position (required for display)
    lat = aircraft.get('lat')
    lon = aircraft.get('lon')
    if lat is not None and lon is not None:
        drone_info['lat'] = get_float(lat)
        drone_info['lon'] = get_float(lon)
    else:
        # No position data - still track but mark as invalid position
        drone_info['lat'] = 0.0
        drone_info['lon'] = 0.0

    # Altitude - prefer geometric, fall back to barometric
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

    # Aircraft category to UA type mapping
    category = aircraft.get('category', '')
    if category in ADSB_CATEGORY_TO_UA_TYPE:
        ua_type, ua_subtype = ADSB_CATEGORY_TO_UA_TYPE[category]
        drone_info['ua_type'] = ua_type
        drone_info['ua_type_name'] = f'Aircraft - {ua_subtype}'
    else:
        # Default to fixed-wing aircraft
        drone_info['ua_type'] = 1
        drone_info['ua_type_name'] = 'Aircraft - Unknown Type'

    # Signal strength (RSSI in dBFS, convert to approximate value)
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

    # Description - combine callsign and category info
    desc_parts = []
    if callsign:
        desc_parts.append(f"Flight: {callsign}")
    if squawk:
        desc_parts.append(f"Squawk: {squawk}")
    if category:
        desc_parts.append(f"Cat: {category}")

    drone_info['description'] = ' | '.join(desc_parts) if desc_parts else f'ADS-B: {icao_hex}'

    # Additional metadata
    drone_info['id_type'] = 'ICAO 24-bit Address'
    drone_info['source'] = 'ADS-B'
    drone_info['nic'] = aircraft.get('nic', 0)
    drone_info['nac_p'] = aircraft.get('nac_p', 0)
    drone_info['nac_v'] = aircraft.get('nac_v', 0)

    # Time since last seen
    seen = aircraft.get('seen')
    if seen is not None:
        drone_info['seen'] = get_float(seen)

    # Message count
    messages = aircraft.get('messages')
    if messages is not None:
        drone_info['message_count'] = get_int(messages)

    return drone_info


def parse_adsb_message(message: Any) -> Optional[Dict[str, Any]]:
    """
    Parse dump1090/readsb JSON message format.
    Returns the first valid aircraft parsed, or None if no valid aircraft found.
    """
    if not message:
        return None

    # Handle full aircraft.json format
    if isinstance(message, dict) and 'aircraft' in message:
        aircraft_list = message.get('aircraft', [])
        if not aircraft_list:
            return None

        # Process first aircraft for now (bridge will handle batch processing)
        for aircraft in aircraft_list:
            parsed = parse_adsb_aircraft(aircraft)
            if parsed:
                return parsed

        return None

    # Handle single aircraft dict
    elif isinstance(message, dict):
        return parse_adsb_aircraft(message)

    else:
        logger.error("Unexpected ADS-B message format")
        return None
