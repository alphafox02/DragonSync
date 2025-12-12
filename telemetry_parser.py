#!/usr/bin/env python3
"""
Copyright 2025 cemaxecuter

Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at

    http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the License for the specific language governing permissions and
limitations under the License.
"""

from typing import Any, Dict, Optional
import logging
from utils import get_float, get_int

logger = logging.getLogger(__name__)

def _ua_code_and_name(raw_ua, ua_type_mapping):
    """Coerce raw UA value to (code:int|None, name:str)."""
    ua_code = None
    if raw_ua is not None:
        try:
            ua_code = int(raw_ua)
        except (TypeError, ValueError):
            # allow name lookup
            ua_code = next(
                (k for k, v in ua_type_mapping.items()
                 if v.lower() == str(raw_ua).lower()),
                None
            )
    if ua_code not in ua_type_mapping:
        ua_code = None
    ua_name = ua_type_mapping.get(ua_code, 'Unknown')
    return ua_code, ua_name

def parse_drone_info(message: Any, ua_type_mapping: Dict[int, str]) -> Optional[Dict[str, Any]]:
    """
    Normalize incoming ZMQ telemetry (DJI list format or ESP32 dict format)
    into a flat dict your pipeline expects. Returns None if the message is unusable.
    """
    drone_info: Dict[str, Any] = {}

    # ─── DJI/AntSDR list-of-dicts format ─────────────────────────────────────
    if isinstance(message, list):
        for item in message:
            if not isinstance(item, dict):
                logger.error("Unexpected item type in message list; expected dict.")
                continue

            # Common fields that sometimes appear at top level
            if 'MAC' in item:
                drone_info['mac'] = item['MAC']
            if 'RSSI' in item:
                drone_info['rssi'] = item['RSSI']

            # Frequency Message (DJI-only)
            if 'Frequency Message' in item:
                fobj = item['Frequency Message']
                drone_info['freq'] = get_float(fobj.get('frequency', None), None)

            # Basic ID
            if 'Basic ID' in item:
                basic = item['Basic ID']
                ua_code, ua_name = _ua_code_and_name(basic.get('ua_type', None), ua_type_mapping)
                drone_info['ua_type'] = ua_code
                drone_info['ua_type_name'] = ua_name

                id_type = basic.get('id_type')
                drone_info['id_type'] = id_type
                drone_info['mac'] = basic.get('MAC', drone_info.get('mac', ''))
                drone_info['rssi'] = basic.get('RSSI', drone_info.get('rssi', 0))

                if id_type == 'Serial Number (ANSI/CTA-2063-A)':
                    drone_info['id'] = basic.get('id', 'unknown')
                elif id_type == 'CAA Assigned Registration ID':
                    drone_info['caa'] = basic.get('id', 'unknown')

            # Operator ID Message
            if 'Operator ID Message' in item:
                op = item['Operator ID Message']
                drone_info['operator_id_type'] = op.get('operator_id_type', "")
                drone_info['operator_id'] = op.get('operator_id', "")

            # Location/Vector Message
            if 'Location/Vector Message' in item:
                loc = item['Location/Vector Message']
                drone_info['lat']    = get_float(loc.get('latitude', 0.0))
                drone_info['lon']    = get_float(loc.get('longitude', 0.0))
                drone_info['speed']  = get_float(loc.get('speed', 0.0))
                drone_info['vspeed'] = get_float(loc.get('vert_speed', 0.0))
                drone_info['alt']    = get_float(loc.get('geodetic_altitude', 0.0))
                drone_info['height'] = get_float(loc.get('height_agl', 0.0))

                # remote ID extras
                drone_info['op_status']           = loc.get('op_status', "")
                drone_info['height_type']         = loc.get('height_type', "")
                drone_info['ew_dir']              = loc.get('ew_dir_segment', "")
                drone_info['direction']           = get_int(loc.get('direction', None), None)
                drone_info['speed_multiplier']    = get_float(str(loc.get('speed_multiplier', "0")).split()[0])
                drone_info['pressure_altitude']   = get_float(str(loc.get('pressure_altitude', "0")).split()[0])
                drone_info['vertical_accuracy']   = loc.get('vertical_accuracy', "")
                drone_info['horizontal_accuracy'] = loc.get('horizontal_accuracy', "")
                drone_info['baro_accuracy']       = loc.get('baro_accuracy', "")
                drone_info['speed_accuracy']      = loc.get('speed_accuracy', "")
                # RID-provided timestamp (often relative/seconds past hour); keep original key for legacy
                drone_info['rid_timestamp']       = loc.get('timestamp', "")
                drone_info['timestamp']           = loc.get('timestamp', "")
                drone_info['timestamp_accuracy']  = loc.get('timestamp_accuracy', "")

            # Self-ID Message
            if 'Self-ID Message' in item:
                drone_info['description'] = item['Self-ID Message'].get('text', "")

            # System Message
            if 'System Message' in item:
                sysm = item['System Message']
                drone_info['pilot_lat'] = get_float(sysm.get('latitude', 0.0))
                drone_info['pilot_lon'] = get_float(sysm.get('longitude', 0.0))
                drone_info['home_lat']  = get_float(sysm.get('home_lat', 0.0))
                drone_info['home_lon']  = get_float(sysm.get('home_lon', 0.0))

        return drone_info or None

    # ─── ESP32 dict format ───────────────────────────────────────────────────
    if isinstance(message, dict):
        drone_info['index']   = message.get('index', 0)
        drone_info['runtime'] = message.get('runtime', 0)

        if "AUX_ADV_IND" in message:
            if "rssi" in message["AUX_ADV_IND"]:
                drone_info['rssi'] = message["AUX_ADV_IND"]["rssi"]
            if "aext" in message and "AdvA" in message["aext"]:
                drone_info['mac'] = message["aext"]["AdvA"].split()[0]

        if 'Basic ID' in message:
            basic = message['Basic ID']
            ua_code, ua_name = _ua_code_and_name(basic.get('ua_type', None), ua_type_mapping)
            drone_info['ua_type'] = ua_code
            drone_info['ua_type_name'] = ua_name
            drone_info['id_type'] = basic.get('id_type')
            drone_info['mac']     = basic.get('MAC', drone_info.get('mac', ''))
            drone_info['rssi']    = basic.get('RSSI', drone_info.get('rssi', 0))
            if basic.get('id_type') == 'Serial Number (ANSI/CTA-2063-A)':
                drone_info['id']  = basic.get('id', 'unknown')
            elif basic.get('id_type') == 'CAA Assigned Registration ID':
                drone_info['caa'] = basic.get('id', 'unknown')

        if 'Operator ID Message' in message:
            op = message['Operator ID Message']
            drone_info['operator_id_type'] = op.get('operator_id_type', "")
            drone_info['operator_id']      = op.get('operator_id', "")

        if 'Location/Vector Message' in message:
            loc = message['Location/Vector Message']
            drone_info['lat']    = get_float(loc.get('latitude', 0.0))
            drone_info['lon']    = get_float(loc.get('longitude', 0.0))
            drone_info['speed']  = get_float(loc.get('speed', 0.0))
            drone_info['vspeed'] = get_float(loc.get('vert_speed', 0.0))
            drone_info['alt']    = get_float(loc.get('geodetic_altitude', 0.0))
            drone_info['height'] = get_float(loc.get('height_agl', 0.0))
            drone_info['op_status']           = loc.get('op_status', "")
            drone_info['height_type']         = loc.get('height_type', "")
            drone_info['ew_dir']              = loc.get('ew_dir_segment', "")
            drone_info['direction']           = get_int(loc.get('direction', None), None)
            drone_info['speed_multiplier']    = get_float(str(loc.get('speed_multiplier', "0")).split()[0])
            drone_info['pressure_altitude']   = get_float(str(loc.get('pressure_altitude', "0")).split()[0])
            drone_info['vertical_accuracy']   = loc.get('vertical_accuracy', "")
            drone_info['horizontal_accuracy'] = loc.get('horizontal_accuracy', "")
            drone_info['baro_accuracy']       = loc.get('baro_accuracy', "")
            drone_info['speed_accuracy']      = loc.get('speed_accuracy', "")
            drone_info['rid_timestamp']       = loc.get('timestamp', "")
            drone_info['timestamp']           = loc.get('timestamp', "")
            drone_info['timestamp_accuracy']  = loc.get('timestamp_accuracy', "")

        if 'Self-ID Message' in message:
            drone_info['description'] = message['Self-ID Message'].get('text', "")

        if 'System Message' in message:
            sysm = message['System Message']
            drone_info['pilot_lat'] = get_float(sysm.get('operator_lat', 0.0))
            drone_info['pilot_lon'] = get_float(sysm.get('operator_lon', 0.0))
            # ESP32 path usually lacks home_lat/home_lon

        # Frequency Message (DJI-only path may still appear in dicts)
        if 'Frequency Message' in message:
            fobj = message['Frequency Message']
            drone_info['freq'] = get_float(fobj.get('frequency', None), None)

        return drone_info or None

    # Unknown format
    logger.error("Unexpected message format; expected dict or list.")
    return None
