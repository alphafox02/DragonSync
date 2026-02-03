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

Centralized CoT XML generation for DragonSync.

Eliminates 300+ lines of duplication across 6 files by providing
standardized CoT XML builders for all track types (drones, aircraft,
FPV signals, system status).
"""

from lxml import etree
from typing import Optional, Dict, Any
import datetime


def utc_now_iso() -> str:
    """Get current UTC time in ISO 8601 format."""
    return datetime.datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%S.%fZ')


def utc_future_iso(seconds: float) -> str:
    """Get future UTC time (now + seconds) in ISO 8601 format."""
    future = datetime.datetime.utcnow() + datetime.timedelta(seconds=seconds)
    return future.strftime('%Y-%m-%dT%H:%M:%S.%fZ')


def build_event_element(uid: str, cot_type: str, stale_seconds: float) -> etree.Element:
    """Build base event element with common attributes."""
    now = utc_now_iso()
    stale = utc_future_iso(stale_seconds)
    start = utc_now_iso()

    return etree.Element(
        'event',
        version='2.0',
        uid=uid,
        type=cot_type,
        time=now,
        start=start,
        stale=stale,
        how='m-g'
    )


def build_point_element(lat: float, lon: float, alt: float = 0.0,
                       ce: str = '9999999.0', le: str = '9999999.0') -> etree.Element:
    """Build point element with coordinates."""
    return etree.Element(
        'point',
        lat=str(lat),
        lon=str(lon),
        hae=str(alt),
        ce=ce,
        le=le
    )


def build_remarks(parts: list, seen_by: Optional[str] = None) -> str:
    """Build remarks field from list of parts, optionally adding seen_by."""
    remarks = " ".join(str(p) for p in parts if p)
    if seen_by:
        remarks += f"; SeenBy: {seen_by}"
    return remarks


def build_drone_cot(drone, stale_offset: float) -> bytes:
    """Build CoT XML for a drone track.

    Args:
        drone: Drone object with attributes (id, lat, lon, alt, speed, etc.)
        stale_offset: Seconds until the track goes stale

    Returns:
        CoT XML as UTF-8 encoded bytes
    """
    import xml.sax.saxutils
    import math

    now = datetime.datetime.utcnow()
    stale = now + datetime.timedelta(seconds=stale_offset)

    # Pick CoT type by UA index (use drone.cot_type if available)
    cot_type = getattr(drone, 'cot_type', 'a-u-A-M-H-R')

    event = etree.Element(
        'event',
        version='2.0',
        uid=drone.id,
        type=cot_type,
        time=now.strftime('%Y-%m-%dT%H:%M:%S.%fZ'),
        start=now.strftime('%Y-%m-%dT%H:%M:%S.%fZ'),
        stale=stale.strftime('%Y-%m-%dT%H:%M:%S.%fZ'),
        how='m-g'
    )

    etree.SubElement(
        event,
        'point',
        lat=str(drone.lat),
        lon=str(drone.lon),
        hae=str(drone.alt),
        ce='35.0',
        le='999999'
    )

    detail = etree.SubElement(event, 'detail')
    etree.SubElement(detail, 'contact', callsign=drone.id)
    etree.SubElement(detail, 'precisionlocation', geopointsrc='gps', altsrc='gps')

    # Track element
    etree.SubElement(
        detail,
        'track',
        course=str(drone.direction or 0.0),
        speed=str(drone.speed or 0.0)
    )

    # Rich remarks with all telemetry
    # Build operator ID display - show N/A if both type and ID are empty
    op_type = getattr(drone, 'operator_id_type', '')
    op_id = getattr(drone, 'operator_id', '')
    if op_type or op_id:
        operator_display = f"[{op_type}: {op_id}]"
    else:
        operator_display = "N/A"

    remarks = (
        f"MAC: {drone.mac}, RSSI: {drone.rssi}dBm; "
        f"ID Type: {drone.id_type}; UA Type: {getattr(drone, 'ua_type_name', 'Unknown')} "
        f"({getattr(drone, 'ua_type', 0)}); "
        f"Operator ID: {operator_display}; "
        f"Speed: {drone.speed} m/s; Vert Speed: {drone.vspeed} m/s; "
        f"Altitude: {drone.alt} m; AGL: {drone.height} m; "
        f"Course: {drone.direction}°; "
        f"Index: {getattr(drone, 'index', 0)}; Runtime: {getattr(drone, 'runtime', 0)}s"
    )

    # Frequency formatting
    freq = getattr(drone, 'freq', None)
    if freq is not None and not (math.isnan(freq) or math.isinf(freq)):
        f = float(freq)
        if f > 1e5:
            f = f / 1e6
        remarks += f"; Freq: ~{round(f, 3)} MHz"

    # Alert reason
    if drone.id == "drone-alert":
        remarks += "; Alert: Unknown DJI OcuSync format (Encrypted/Partial)"

    # CAA Registration ID
    caa_id = getattr(drone, 'caa_id', None)
    if caa_id:
        remarks += f"; CAA ID: {caa_id}"

    # FAA RID enrichment
    if getattr(drone, 'rid_make', None) or getattr(drone, 'rid_model', None):
        rid_label = f"{getattr(drone, 'rid_make', '') or ''} {getattr(drone, 'rid_model', '') or ''}".strip()
        if rid_label:
            remarks += f"; RID: {rid_label}"
    if getattr(drone, 'rid_source', None):
        remarks += f"; RID Source: {drone.rid_source}"
    if getattr(drone, 'seen_by', None):
        remarks += f"; SeenBy: {drone.seen_by}"
    if getattr(drone, 'observed_at', None):
        obs_dt = datetime.datetime.utcfromtimestamp(drone.observed_at)
        remarks += f"; ObservedAt: {obs_dt.isoformat()}Z"
    if getattr(drone, 'rid_timestamp', None):
        remarks += f"; RID_TS: {drone.rid_timestamp}"

    etree.SubElement(detail, 'remarks').text = xml.sax.saxutils.escape(remarks)
    etree.SubElement(detail, 'color', argb='-256')

    # Structured RID block
    rid = etree.SubElement(detail, 'rid')
    if getattr(drone, 'rid_make', None):
        rid.set('make', drone.rid_make)
    if getattr(drone, 'rid_model', None):
        rid.set('model', drone.rid_model)
    if getattr(drone, 'rid_source', None):
        rid.set('source', drone.rid_source)

    return etree.tostring(event, pretty_print=True, xml_declaration=True, encoding='UTF-8')


def build_pilot_cot(drone, stale_offset: float) -> bytes:
    """Build CoT XML for drone pilot location.

    Args:
        drone: Drone object with pilot_lat, pilot_lon attributes
        stale_offset: Seconds until the track goes stale

    Returns:
        CoT XML as UTF-8 encoded bytes, or empty bytes if no pilot location
    """
    import xml.sax.saxutils

    # Suppress when alert (no pilot from OcuSync)
    if drone.id == "drone-alert":
        return b""

    if not drone.pilot_lat or not drone.pilot_lon:
        return b''

    now = datetime.datetime.utcnow()
    stale = now + datetime.timedelta(seconds=stale_offset)

    base_id = drone.id
    if base_id.startswith("drone-"):
        base_id = base_id[len("drone-"):]
    uid = f"pilot-{base_id}"

    event = etree.Element(
        'event',
        version='2.0',
        uid=uid,
        type='b-m-p-s-m',
        time=now.strftime('%Y-%m-%dT%H:%M:%S.%fZ'),
        start=now.strftime('%Y-%m-%dT%H:%M:%S.%fZ'),
        stale=stale.strftime('%Y-%m-%dT%H:%M:%S.%fZ'),
        how='m-g'
    )
    etree.SubElement(
        event,
        'point',
        lat=str(drone.pilot_lat),
        lon=str(drone.pilot_lon),
        hae=str(drone.alt),
        ce='35.0',
        le='999999'
    )

    detail = etree.SubElement(event, 'detail')
    callsign = f"pilot-{base_id}"
    etree.SubElement(detail, 'contact', callsign=callsign)
    etree.SubElement(detail, 'precisionlocation', geopointsrc='gps', altsrc='gps')
    etree.SubElement(
        detail,
        'usericon',
        iconsetpath='com.atakmap.android.maps.public/Civilian/Person.png'
    )
    pilot_remarks = f"Pilot location for drone {drone.id}"
    caa_id = getattr(drone, 'caa_id', None)
    if caa_id:
        pilot_remarks += f"; CAA ID: {caa_id}"
    if getattr(drone, 'seen_by', None):
        pilot_remarks += f"; SeenBy: {drone.seen_by}"
    if getattr(drone, 'observed_at', None):
        obs_dt = datetime.datetime.utcfromtimestamp(drone.observed_at)
        pilot_remarks += f"; ObservedAt: {obs_dt.isoformat()}Z"
    etree.SubElement(detail, 'remarks').text = xml.sax.saxutils.escape(pilot_remarks)

    return etree.tostring(event, pretty_print=True, xml_declaration=True, encoding='UTF-8')


def build_home_cot(drone, stale_offset: float) -> bytes:
    """Build CoT XML for drone home location.

    Args:
        drone: Drone object with home_lat, home_lon attributes
        stale_offset: Seconds until the track goes stale

    Returns:
        CoT XML as UTF-8 encoded bytes, or empty bytes if no home location
    """
    import xml.sax.saxutils

    # Suppress when alert (no home from OcuSync)
    if drone.id == "drone-alert":
        return b""

    if not drone.home_lat or not drone.home_lon:
        return b''

    now = datetime.datetime.utcnow()
    stale = now + datetime.timedelta(seconds=stale_offset)

    base_id = drone.id
    if base_id.startswith("drone-"):
        base_id = base_id[len("drone-"):]
    uid = f"home-{base_id}"

    event = etree.Element(
        'event',
        version='2.0',
        uid=uid,
        type='b-m-p-s-m',
        time=now.strftime('%Y-%m-%dT%H:%M:%S.%fZ'),
        start=now.strftime('%Y-%m-%dT%H:%M:%S.%fZ'),
        stale=stale.strftime('%Y-%m-%dT%H:%M:%S.%fZ'),
        how='m-g'
    )
    etree.SubElement(
        event,
        'point',
        lat=str(drone.home_lat),
        lon=str(drone.home_lon),
        hae=str(drone.alt),
        ce='35.0',
        le='999999'
    )

    detail = etree.SubElement(event, 'detail')
    callsign = f"home-{base_id}"
    etree.SubElement(detail, 'contact', callsign=callsign)
    etree.SubElement(detail, 'precisionlocation', geopointsrc='gps', altsrc='gps')
    etree.SubElement(
        detail,
        'usericon',
        iconsetpath='com.atakmap.android.maps.public/Civilian/House.png'
    )
    home_remarks = f"Home location for drone {drone.id}"
    caa_id = getattr(drone, 'caa_id', None)
    if caa_id:
        home_remarks += f"; CAA ID: {caa_id}"
    if getattr(drone, 'seen_by', None):
        home_remarks += f"; SeenBy: {drone.seen_by}"
    if getattr(drone, 'observed_at', None):
        obs_dt = datetime.datetime.utcfromtimestamp(drone.observed_at)
        home_remarks += f"; ObservedAt: {obs_dt.isoformat()}Z"
    etree.SubElement(detail, 'remarks').text = xml.sax.saxutils.escape(home_remarks)

    return etree.tostring(event, pretty_print=True, xml_declaration=True, encoding='UTF-8')


def build_adsb_cot(craft: Dict[str, Any], uid: str, seen_by: Optional[str], stale_seconds: float) -> bytes:
    """Build CoT XML for ADS-B aircraft track.

    Args:
        craft: Dictionary with aircraft data (hex, flight, lat, lon, alt_baro, gs, track, etc.)
        uid: Pre-computed unique identifier for this aircraft
        seen_by: Identifier of the sensor that detected this aircraft (optional)
        stale_seconds: Seconds until the track goes stale

    Returns:
        CoT XML as UTF-8 encoded bytes
    """
    import xml.sax.saxutils

    lat = craft.get('lat')
    lon = craft.get('lon')
    if lat is None or lon is None:
        return b''

    # Prefer geometric altitude, fall back to barometric
    alt = craft.get('alt_geom')
    if alt is None:
        alt = craft.get('alt_baro', 0)

    # Identity info
    flight = (craft.get('flight') or '').strip()
    hex_id = (craft.get('hex') or '').strip().upper()
    callsign = uid
    squawk = craft.get('squawk')
    reg = craft.get('reg') or craft.get('r')
    category = craft.get('category') or craft.get('cat')

    # Kinematics
    gs = float(craft.get('gs') or 0.0)  # knots
    track = float(craft.get('track') or 0.0)  # degrees

    # Ground state
    on_ground = bool(craft.get('onground') or craft.get('OnGround') or False)

    # Position quality (NACp / NACv)
    nac_p = craft.get('NACp', craft.get('nac_p'))
    nac_v = craft.get('NACv', craft.get('nac_v', nac_p))

    ce_val = 35.0
    le_val = 999999.0

    if nac_p is not None:
        try:
            nac_p_f = float(nac_p)
            nac_v_f = float(nac_v) if nac_v is not None else nac_p_f
            ground_const = 51.56 if on_ground else 56.57
            ce_val = nac_p_f + ground_const
            le_val = nac_v_f + 12.5
        except (TypeError, ValueError):
            ce_val = 35.0
            le_val = 999999.0

    now = datetime.datetime.utcnow()
    t = now.strftime('%Y-%m-%dT%H:%M:%S.%fZ')
    stale = (now + datetime.timedelta(seconds=stale_seconds)).strftime('%Y-%m-%dT%H:%M:%S.%fZ')

    cot_type = 'a-f-A'  # Simple air track

    event = etree.Element(
        'event',
        version='2.0',
        uid=uid,
        type=cot_type,
        time=t,
        start=t,
        stale=stale,
        how='m-g',
    )

    etree.SubElement(
        event,
        'point',
        lat=str(lat),
        lon=str(lon),
        hae=str(float(alt)),
        ce=str(float(ce_val)),
        le=str(float(le_val)),
    )

    detail = etree.SubElement(event, 'detail')
    etree.SubElement(detail, 'contact', callsign=callsign)

    # Track element
    track_el = etree.SubElement(
        detail,
        'track',
        course=str(track),
        speed=str(gs),
    )
    if on_ground:
        track_el.set('slope', '0')

    # Build remarks
    display_id = flight or hex_id
    remark_parts = [
        'ADS-B',
        f'hex={hex_id}' if hex_id else None,
        f'flight={display_id}' if display_id else None,
        f'alt={alt}ft',
        f'gs={gs}kt',
        f'track={track}',
    ]

    if squawk:
        remark_parts.append(f'squawk={squawk}')
    if reg:
        remark_parts.append(f'reg={reg}')
    if category:
        remark_parts.append(f'cat={category}')
    if on_ground:
        remark_parts.append('onground=1')

    remark_parts.append('src=adsb')
    if seen_by:
        remark_parts.append(f'SeenBy: {seen_by}')

    remarks = ' '.join(p for p in remark_parts if p)
    etree.SubElement(detail, 'remarks').text = xml.sax.saxutils.escape(remarks)

    return etree.tostring(event, pretty_print=False, xml_declaration=True, encoding='UTF-8')


def build_signal_cot(alert: Dict[str, Any], lat: float, lon: float, alt: float,
                     stale_seconds: float, radius_m: float, seen_by: Optional[str] = None) -> bytes:
    """Build CoT XML for FPV signal detection.

    Args:
        alert: Dictionary with signal data (uid, signal_type, source, center_hz,
               bandwidth_hz, pal_conf, ntsc_conf, callsign)
        lat: Latitude of detection
        lon: Longitude of detection
        alt: Altitude of detection
        stale_seconds: Seconds until the track goes stale
        radius_m: Detection radius in meters (used as CE)
        seen_by: Optional sensor identifier

    Returns:
        CoT XML as UTF-8 encoded bytes
    """
    now = datetime.datetime.utcnow()
    t = now.strftime('%Y-%m-%dT%H:%M:%S.%fZ')
    stale = (now + datetime.timedelta(seconds=stale_seconds)).strftime('%Y-%m-%dT%H:%M:%S.%fZ')

    uid = alert['uid']
    signal_type = alert.get('signal_type') or 'fpv'
    callsign = alert.get('callsign') or f"{signal_type.upper()} Signal"

    # Build remarks with all signal metadata
    remarks_parts = [f"signal={signal_type}"]
    if alert.get('source') is not None:
        remarks_parts.append(f"source={alert.get('source')}")
    if alert.get('center_hz') is not None:
        remarks_parts.append(f"center_hz={alert.get('center_hz')}")
    if alert.get('bandwidth_hz') is not None:
        remarks_parts.append(f"bandwidth_hz={alert.get('bandwidth_hz')}")
    if alert.get('pal_conf') is not None:
        remarks_parts.append(f"pal={alert.get('pal_conf')}")
    if alert.get('ntsc_conf') is not None:
        remarks_parts.append(f"ntsc={alert.get('ntsc_conf')}")
    if alert.get('rssi') is not None:
        remarks_parts.append(f"rssi={alert.get('rssi')}dBm")
    if seen_by:
        remarks_parts.append(f"SeenBy: {seen_by}")
    remarks = ' '.join(str(p) for p in remarks_parts if p)

    event = etree.Element(
        'event',
        version='2.0',
        uid=uid,
        type='b-m-p-s-s',
        time=t,
        start=t,
        stale=stale,
        how='m-g',
    )
    etree.SubElement(
        event,
        'point',
        lat=str(lat),
        lon=str(lon),
        hae=str(float(alt or 0.0)),
        ce=str(float(radius_m)),
        le=str(999999.0),
    )
    detail = etree.SubElement(event, 'detail')
    etree.SubElement(detail, 'contact', callsign=str(callsign))
    etree.SubElement(detail, 'remarks').text = remarks

    return etree.tostring(event, encoding='UTF-8', xml_declaration=True)


def build_system_status_cot(status, stale_seconds: float = 600.0) -> bytes:
    """Build CoT XML for WarDragon system status.

    Args:
        status: SystemStatus object with attributes (id, lat, lon, alt, cpu_usage,
                memory_total, pluto_temp, zynq_temp, etc.)
        stale_seconds: Seconds until the track goes stale (default: 600)

    Returns:
        CoT XML as UTF-8 encoded bytes
    """
    import xml.sax.saxutils

    current_time = datetime.datetime.utcnow()
    stale_time = current_time + datetime.timedelta(seconds=stale_seconds)

    event = etree.Element(
        'event',
        version='2.0',
        uid=status.id,
        type='a-f-G-E-S',
        time=current_time.strftime('%Y-%m-%dT%H:%M:%S.%fZ'),
        start=current_time.strftime('%Y-%m-%dT%H:%M:%S.%fZ'),
        stale=stale_time.strftime('%Y-%m-%dT%H:%M:%S.%fZ'),
        how='m-g'
    )

    etree.SubElement(
        event,
        'point',
        lat=str(status.lat),
        lon=str(status.lon),
        hae=str(status.alt),
        ce='35.0',
        le='999999'
    )

    detail = etree.SubElement(event, 'detail')
    etree.SubElement(detail, 'contact', endpoint='', phone='', callsign=status.id)
    etree.SubElement(detail, 'precisionlocation', geopointsrc='gps', altsrc='gps')

    # Rich system health remarks with SDR temps
    remarks_text = (
        f"CPU Usage: {status.cpu_usage}%, "
        f"Memory Total: {status.memory_total:.2f} MB, Memory Available: {status.memory_available:.2f} MB, "
        f"Disk Total: {status.disk_total:.2f} MB, Disk Used: {status.disk_used:.2f} MB, "
        f"Temperature: {status.temperature}°C, "
        f"Uptime: {status.uptime} seconds, "
        f"Pluto Temp: {status.pluto_temp}°C, "
        f"Zynq Temp: {status.zynq_temp}°C"
    )
    if getattr(status, 'time_source', None):
        remarks_text += f"; TimeSource: {status.time_source}"
    if getattr(status, 'gps_fix', None):
        remarks_text += "; GPS Fix: true"
    if getattr(status, 'gpsd_time_utc', None):
        remarks_text += f"; GPSD UTC: {status.gpsd_time_utc}"

    etree.SubElement(detail, 'remarks').text = xml.sax.saxutils.escape(remarks_text)
    etree.SubElement(detail, 'color', argb='-256')

    # Embed GPS-provided track & speed
    etree.SubElement(
        detail,
        'track',
        course=f"{status.track:.1f}",
        speed=f"{status.speed:.2f}"
    )

    return etree.tostring(event, pretty_print=True, xml_declaration=True, encoding='UTF-8')
