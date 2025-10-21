# MIT License
#
# Copyright (c) 2024 cemaxecuter
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in all
# copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.

from __future__ import annotations

import logging
import time
from typing import Optional, Dict, Any
import datetime as dt
import os

# ────────────────────────────────────────────────────────────────────────────────
# Anduril SDK imports
# ────────────────────────────────────────────────────────────────────────────────
try:
    import anduril as _anduril_mod  # for __version__
    from anduril import Lattice
    from anduril import (
        Location, Position, MilView, Ontology, Provenance, Aliases, Classification, ClassificationInformation,
        Health, ComponentHealth, ComponentMessage, VisualDetails, RangeRings, Quaternion, 
        Relationships, Relationship, RelationshipType, TrackedBy, Sensors, Sensor 
    )
    # Optional enum (names differ across SDKs; used only for AIR)
    try:
        from anduril.entities.types.mil_view import Environment as MilEnvironment  # type: ignore
    except Exception:
        MilEnvironment = None  # type: ignore

    # Optional: per-request extra headers in some SDKs
    try:
        from anduril.core.request_options import RequestOptions  # type: ignore
    except Exception:
        RequestOptions = None  # type: ignore

except Exception as e:
    _IMPORT_ERROR = e
    Lattice = None  # type: ignore
    Location = Position = MilView = Ontology = Provenance = Aliases = None  # type: ignore
    Classification = ClassificationInformation = None  # type: ignore
    MilEnvironment = None  # type: ignore
    RequestOptions = None  # type: ignore
    Relationships = None  # type: ignore
    _SDK_VERSION = "unknown"
else:
    _IMPORT_ERROR = None
    _SDK_VERSION = getattr(_anduril_mod, "__version__", "unknown")

_log = logging.getLogger(__name__)

# ────────────────────────────────────────────────────────────────────────────────
# Helpers
# ────────────────────────────────────────────────────────────────────────────────
def _now_utc() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)

def _valid_latlon(lat: Optional[float], lon: Optional[float]) -> bool:
    try:
        if lat is None or lon is None:
            return False
        return -90.0 <= float(lat) <= 90.0 and -180.0 <= float(lon) <= 180.0
    except Exception:
        return False

def _air_env_value():
    """
    Return a value acceptable to MilView.environment for 'AIR'.
    Prefer enum if present; fall back to a known-good string.
    """
    if MilEnvironment is not None:
        for attr in ("MIL_VIEW_ENVIRONMENT_AIR", "ENVIRONMENT_AIR"):
            if hasattr(MilEnvironment, attr):
                return getattr(MilEnvironment, attr)
    return "ENVIRONMENT_AIR"

def _bearing_to_enu_quaternion(bearing_deg: float) -> Quaternion:
    """
    Convert a bearing (degrees clockwise from true north) to an ENU quaternion.

    Note: this is a simple conversion assuming zero roll/pitch. More complex
    attitude data would require a full conversion.
    """
    import math

    # Convert bearing to radians and adjust for ENU frame
    yaw_rad = math.radians((450.0 - bearing_deg) % 360.0)
    cy = math.cos(yaw_rad * 0.5)
    sy = math.sin(yaw_rad * 0.5)

    # Assuming roll = pitch = 0
    return Quaternion(
        w=cy,
        x=0.0,
        y=0.0,
        z=sy
    )

# ────────────────────────────────────────────────────────────────────────────────
# LatticeSink (minimal publish)
# ────────────────────────────────────────────────────────────────────────────────
class LatticeSink:
    """
    Minimal publisher for entities via the Anduril Lattice SDK.

    - Uses the environment token (Authorization) and optional sandbox token
      via 'anduril-sandbox-authorization: Bearer <token>'.
    - WarDragon/pilot/home: omit environment to avoid enum quirks; disposition
      only where we know it's safe.
    - Drone: set environment=AIR and disposition=NEUTRAL.
    """

    def __init__(
        self,
        *,
        token: str,
        base_url: Optional[str] = None,
        drone_hz: float = 1.0,
        wardragon_hz: float = 0.2,
        source_name: str = "DragonSync",
        sandbox_token: Optional[str] = None,
    ) -> None:
        if _IMPORT_ERROR is not None:
            raise RuntimeError(f"anduril SDK import failed: {_IMPORT_ERROR}") from _IMPORT_ERROR

        token = (token or "").strip()
        base_url = (base_url or "").strip() or None
        self._sandbox_token = (sandbox_token or "").strip() or None
        self.source_name = source_name

        headers = {"anduril-sandbox-authorization": f"Bearer {self._sandbox_token}"} if self._sandbox_token else None
        self._req_opts = None
        try:
            if base_url:
                self.client = Lattice(token=token, base_url=base_url, headers=headers)  # type: ignore
            else:
                self.client = Lattice(token=token, headers=headers)  # type: ignore
            _log.info("LatticeSink ACTIVE. file=%s", os.path.abspath(__file__))
            _log.info("Anduril Lattice SDK version: %s", _SDK_VERSION)
        except TypeError:
            if base_url:
                self.client = Lattice(token=token, base_url=base_url)  # type: ignore
            else:
                self.client = Lattice(token=token)  # type: ignore
            if self._sandbox_token and RequestOptions is not None:
                self._req_opts = RequestOptions(
                    additional_headers={"anduril-sandbox-authorization": f"Bearer {self._sandbox_token}"}
                )
            _log.info("LatticeSink ACTIVE (fallback headers). file=%s", os.path.abspath(__file__))
            _log.info("anduril SDK version: %s", _SDK_VERSION)

        # Simple rate limits
        self._periods = {
            "drone": 1.0 / max(drone_hz, 1e-6),
            "wd": 1.0 / max(wardragon_hz, 1e-6),
            "pilot": 1.0,  # 1 Hz cap
            "home": 1.0,
        }
        self._last_send = {k: 0.0 for k in self._periods.keys()}

        # Store system entity_id for use in relationships
        self._system_entity_id: Optional[str] = None

    def _rate_ok(self, key: str) -> bool:
        now = time.time()
        if now - self._last_send.get(key, 0.0) >= self._periods.get(key, 0.0):
            self._last_send[key] = now
            return True
        return False

    # ───────────────────────────── WarDragon (ground sensor) ─────────────────────────────
    def publish_system(self, s: Dict[str, Any]) -> None:
        """
        Publish WarDragon position as a Lattice asset entity.
        """
        if not self._rate_ok("wd"):
            return


        serial = str(s.get("serial_number", "unknown")) or "unknown"
        gps = s.get("gps_data", {}) or {}
        lat = gps.get("latitude")
        lon = gps.get("longitude")
        hae = gps.get("altitude")
        stats = s.get("system_stats", {}) or {}
        cpu_usage = stats.get("cpu_usage")
        memory = stats.get("memory", {}) or {}
        mem_percent = memory.get("percent")
        disk = stats.get("disk", {}) or {}
        disk_percent = disk.get("percent")
        temperature = stats.get("temperature")
        if isinstance(stats.get("uptime"), (int, float)):
            uptime = int(stats.get("uptime")/60) # in minutes
        else:
            uptime = "unknown"
        
        ant_pluto_temp = None
        ant_zynq_temp = None
        ant_sdr_temps = s.get("ant_sdr_temps", {}) or {}
        if isinstance(ant_sdr_temps.get("pluto_temp"), (int, float)):
            ant_pluto_temp = ant_sdr_temps.get("pluto_temp")
        if isinstance(ant_sdr_temps.get("zynq_temp"), (int, float)):
            ant_zynq_temp = ant_sdr_temps.get("zynq_temp")


        if not _valid_latlon(lat, lon):
            return

        entity_id = f"wardragon-{serial}"
        alias_name = f"WarDragon {serial}"

        # Store system entity_id for use in entity relationships
        self._system_entity_id = entity_id

        location = Location(
            position=Position(
                latitude_degrees=float(lat),
                longitude_degrees=float(lon)
            )   
        )
        try:
            if hae is not None:
                location.position.height_above_ellipsoid_meters = float(hae)  # type: ignore[attr-defined]
        except Exception:
            pass


        ontology = Ontology(
            template="TEMPLATE_ASSET", 
            platform_type="Antenna"
        )
        # Keep only disposition; omit environment to avoid enum mismatches
        mil_view = MilView(
            disposition="DISPOSITION_FRIENDLY"
        )

        provenance = Provenance(
            data_type="wardragon-sensor",
            integration_name=self.source_name,
            source_update_time=_now_utc().isoformat(),
        )
        aliases = Aliases(
            name=alias_name
        )
        expiry_time = _now_utc() + dt.timedelta(minutes=10)

        # publish wardragon system health
        health=Health(
            connection_status="CONNECTION_STATUS_ONLINE",
            health_status="HEALTH_STATUS_HEALTHY",
            components=[
                ComponentHealth(
                    id="cpu",
                    name="CPU",
                    health="HEALTH_STATUS_HEALTHY",
                    messages=[
                        ComponentMessage(
                            status="HEALTH_STATUS_HEALTHY",
                            message=(f"{cpu_usage}%")
                        )
                    ],
                    update_time=_now_utc()
                ),
                ComponentHealth(
                    id="memory",
                    name="Memory Percent",
                    health="HEALTH_STATUS_HEALTHY",
                    messages=[
                        ComponentMessage(
                            status="HEALTH_STATUS_HEALTHY",
                            message=(f"{mem_percent}%")
                        )
                    ],
                    update_time=_now_utc()
                ),
                ComponentHealth(
                    id="disk_percent",
                    name="Disk",
                    health="HEALTH_STATUS_HEALTHY",
                    messages=[
                        ComponentMessage(
                            status="HEALTH_STATUS_HEALTHY",
                            message=(f"{disk_percent}%")
                        )
                    ],
                    update_time=_now_utc()
                ),
                ComponentHealth(
                    id="temperature",
                    name="Temperature",
                    health="HEALTH_STATUS_HEALTHY",
                    messages=[
                        ComponentMessage(
                            status="HEALTH_STATUS_HEALTHY",
                            message=(f"{temperature}ºC")
                        )
                    ],
                    update_time=_now_utc()
                ),
                ComponentHealth(
                    id="uptime",
                    name="Uptime",
                    health="HEALTH_STATUS_HEALTHY",
                    messages=[
                        ComponentMessage(
                            status="HEALTH_STATUS_HEALTHY",
                            message=(f"{uptime} minutes")
                        )
                    ],
                    update_time=_now_utc()
                ),
                ComponentHealth(
                    id="ant_pluto_temp",
                    name="Ant Pluto Temp",
                    health="HEALTH_STATUS_HEALTHY",
                    messages=[
                        ComponentMessage(
                            status="HEALTH_STATUS_HEALTHY",
                            message=(f"{ant_pluto_temp}ºC")
                        )
                    ],
                    update_time=_now_utc()
                ),
                ComponentHealth(
                    id="ant_zynq_temp",
                    name="Ant Zynq Temp",
                    health="HEALTH_STATUS_HEALTHY",
                    messages=[
                        ComponentMessage(
                            status="HEALTH_STATUS_HEALTHY",
                            message=(f"{ant_zynq_temp}ºC")
                        )
                    ],
                    update_time=_now_utc()
                ) 
            ]
        )

        try:
            self.client.entities.publish_entity(
                entity_id=entity_id,
                is_live=True,
                location=location,
                ontology=ontology,
                mil_view=mil_view,
                provenance=provenance,
                aliases=aliases,
                health=health,
                expiry_time=expiry_time,
                data_classification=(
                    Classification(
                        default=ClassificationInformation(
                            level="CLASSIFICATION_LEVELS_UNCLASSIFIED"
                        )
                    ) if Classification is not None and ClassificationInformation is not None else None
                ),
                request_options=self._req_opts,
            )
        except Exception as e:
            _log.warning("Lattice publish_system failed for %s: %s", entity_id, e)

    # ───────────────────────────── Drone (air) ────────────────────────────────────
    def publish_drone(self, d: Any) -> None:
        """
        Publish/refresh a drone entity (minimal). Accepts dict or object with attrs.
        """
        if not self._rate_ok("drone"):
            return

        def g(key, default=None):
            if isinstance(d, dict):
                return d.get(key, default)
            return getattr(d, key, default)

        entity_id = str(g("id", "unknown")) or "unknown"
        id_type = str(g("id_type", "Unknown")) or "Unknown"
        caa = str(g("caa", "") or "").strip()
        alias = f"{id_type}: {caa}"
        mac = str(g("mac", "") or "").strip()
        rssi = g("rssi")
        ua_type = str(g("ua_type_name", "Unknown")) or "Unknown"
        ua_type_name = str(g("ua_type_name", "Unknown")) or "Unknown"
        speed = g("speed")
        vspeed = g("vspeed")
        alt = g("alt")
        height = g("height")
        op_status = str(g("op_status", "") or "").strip()
        height_type = str(g("height_type", "") or "").strip()
        speed_multiplier = g("speed_multiplier")
        operator_id = str(g("operator_id", "") or "").strip()
        operator_id_type = str(g("operator_id_type", "") or "").strip()
        operator = ""
        if operator_id and operator_id_type:
            operator = f"Operator {operator_id_type}: {operator_id}"
        
        freq = g("freq")
    
        lat = g("lat")
        lon = g("lon")
        hae = g("alt")
        _log.info(f"Drone altitude: alt={alt}, hae={hae}, height={height}")
        if not _valid_latlon(lat, lon):
            return


#     "operator_id_type": "Operator ID",
#     "operator_id": ""
# }

        _log.info(f"drone speed reported: {speed}")
        speed_mps = 0.0
        if isinstance(speed, (int, float)) and speed >= 0.0:
            speed_mps = float(speed)

        direction = g("direction")
        _log.info(f"drone direction reported: {direction}")
        heading = Quaternion(x=0.0, y=0.0)
        if isinstance(direction, (int, float)) and 0.0 <= float(direction) <= 360.0:
            heading = _bearing_to_enu_quaternion(direction)
        _log.info(f"calculated heading_enu from direction: x={heading.x}, y={heading.y}")

        # Create position with altitude if available
        position_kwargs = {
            "latitude_degrees": float(lat),
            "longitude_degrees": float(lon)
        }
        if hae is not None:
            try:
                position_kwargs["altitude_hae_meters"] = float(hae)
                _log.info(f"Setting altitude_hae_meters to {float(hae)}")
            except Exception as e:
                _log.warning(f"Failed to set altitude: {e}")

        position = Position(**position_kwargs)

        location = Location(
            position=position,
            speed_mps=speed_mps,
            attitude_enu=heading
        )

        aliases = Aliases(name=alias)
        ontology = Ontology(
            template="TEMPLATE_TRACK", 
            platform_type="Small UAS"
        )

        mil_view = MilView(
            environment=_air_env_value(),
            disposition="DISPOSITION_NEUTRAL",
        )

        provenance = Provenance(
            data_type="wardragon-detection",
            integration_name=self.source_name,
            source_update_time=_now_utc().isoformat()
        )
        expiry_time = _now_utc() + dt.timedelta(minutes=5)

        # Add relationship to system if available
        relationships = None
        if self._system_entity_id and Relationships is not None:
            try:
                relationships=Relationships(
                    relationships=[
                        Relationship(
                            related_entity_id=self._system_entity_id,
                            relationship_type=RelationshipType(
                                tracked_by=TrackedBy(
                                    actively_tracking_sensors=Sensors(
                                        sensors=[
                                            Sensor(
                                                sensor_id="wardragon-antenna",
                                                operational_state="OPERATIONAL_STATE_OPERATIONAL",
                                                sensor_type="SENSOR_TYPE_RF",
                                                sensor_description="WarDragon Antenna"
                                            )
                                        ]
                                    )
                                )
                            )
                        )
                    ]
                )
            except Exception as e:
                _log.debug("Could not create relationship for drone: %s", e)

        try:
            self.client.entities.publish_entity(
                entity_id=entity_id,
                is_live=True,
                location=location,
                ontology=ontology,
                mil_view=mil_view,
                provenance=provenance,
                aliases=aliases,
                expiry_time=expiry_time,
                relationships=relationships,
                data_classification=Classification(
                    default=ClassificationInformation(level="CLASSIFICATION_LEVELS_UNCLASSIFIED")
                ),
                request_options=self._req_opts,
            )
        except Exception as e:
            _log.warning("Lattice publish_drone failed for %s: %s", entity_id, e)

    # ───────────────────────────── Pilot (ground) ─────────────────────────────────
    def publish_pilot(self, entity_base_id: str, lat: float, lon: float, *args, **kwargs) -> None:
        """
        Publish/refresh the pilot entity (minimal).

        Compatible call forms:
            publish_pilot(id, lat, lon)
            publish_pilot(id, lat, lon, "Pilot Name")
            publish_pilot(id, lat, lon, 123.4)            # altitude (HAE m)
            publish_pilot(id, lat, lon, name="Pilot X")
            publish_pilot(id, lat, lon, display_name="Pilot X")
            publish_pilot(id, lat, lon, altitude=123.4)   # or hae=123.4
        """
        if not self._rate_ok("pilot"):
            return
        if not _valid_latlon(lat, lon):
            return

        display_name = kwargs.get("display_name") or kwargs.get("name")
        hae = kwargs.get("altitude", kwargs.get("hae"))

        if args:
            extra = args[0]
            if isinstance(extra, str) and not display_name:
                display_name = extra
            else:
                try:
                    if hae is None:
                        hae = float(extra)
                except Exception:
                    pass

        entity_id = f"{entity_base_id}-pilot"
        if not display_name:
            display_name = f"Pilot of {entity_base_id}"

        location = Location(position=Position(latitude_degrees=float(lat), longitude_degrees=float(lon)))
        try:
            if hae is not None:
                location.position.height_above_ellipsoid_meters = float(hae)  # type: ignore
        except Exception:
            pass

        ontology = Ontology(template="TEMPLATE_TRACK", platform_type="Operator")
        mil_view = MilView()  # omit env & disposition for max compatibility

        provenance = Provenance(
            data_type="wardragon-detection",
            integration_name=self.source_name,
            source_update_time=_now_utc(),
        )
        expiry_time = _now_utc() + dt.timedelta(minutes=30)

        # Add relationship to system if available
        relationships = None
        if self._system_entity_id and Relationships is not None:
            try:
                relationships=Relationships(
                    relationships=[
                        Relationship(
                            related_entity_id=self._system_entity_id,
                            relationship_type=RelationshipType(
                                tracked_by=TrackedBy(
                                    actively_tracking_sensors=Sensors(
                                        sensors=[
                                            Sensor(
                                                sensor_id="wardragon-antenna",
                                                operational_state="OPERATIONAL_STATE_OPERATIONAL",
                                                sensor_type="SENSOR_TYPE_RF",
                                                sensor_description="WarDragon Antenna"
                                            )
                                        ]
                                    )
                                )
                            )
                        )
                    ]
                )
            except Exception as e:
                _log.debug("Could not create relationship for pilot: %s", e)

        try:
            self.client.entities.publish_entity(
                entity_id=entity_id,
                is_live=True,
                location=location,
                ontology=ontology,
                mil_view=mil_view,
                provenance=provenance,
                aliases=Aliases(name=str(display_name)),
                expiry_time=expiry_time,
                relationships=relationships,
                data_classification=Classification(
                    default=ClassificationInformation(level="CLASSIFICATION_LEVELS_UNCLASSIFIED")
                ),
                request_options=self._req_opts,
            )
        except Exception as e:
            _log.warning("Lattice publish_pilot failed for %s: %s", entity_id, e)

    # ───────────────────────────── Home (ground) ──────────────────────────────────
    def publish_home(self, entity_base_id: str, lat: float, lon: float, *args, **kwargs) -> None:
        """
        Publish/refresh the home point entity (minimal).

        Compatible call forms:
            publish_home(id, lat, lon)
            publish_home(id, lat, lon, "Home Label")
            publish_home(id, lat, lon, 123.4)             # altitude (HAE m)
            publish_home(id, lat, lon, name="Home of X")
            publish_home(id, lat, lon, display_name="Home of X")
            publish_home(id, lat, lon, altitude=123.4)    # or hae=123.4
        """
        if not self._rate_ok("home"):
            return
        if not _valid_latlon(lat, lon):
            return

        display_name = kwargs.get("display_name") or kwargs.get("name")
        hae = kwargs.get("altitude", kwargs.get("hae"))

        if args:
            extra = args[0]
            if isinstance(extra, str) and not display_name:
                display_name = extra
            else:
                try:
                    if hae is None:
                        hae = float(extra)
                except Exception:
                    pass

        entity_id = f"{entity_base_id}-home"
        if not display_name:
            display_name = f"Home of {entity_base_id}"

        location = Location(position=Position(latitude_degrees=float(lat), longitude_degrees=float(lon)))
        try:
            if hae is not None:
                location.position.height_above_ellipsoid_meters = float(hae)  # type: ignore
        except Exception:
            pass

        ontology = Ontology(template="TEMPLATE_TRACK", platform_type="Home Point")
        mil_view = MilView()  # omit env & disposition

        provenance = Provenance(
            data_type="wardragon-detection",
            integration_name=self.source_name,
            source_update_time=_now_utc().isoformat(),
        )
        expiry_time = _now_utc() + dt.timedelta(hours=4)

        # Add relationship to system if available
        relationships = None
        if self._system_entity_id and Relationships is not None:
            try:
                 relationships=Relationships(
                    relationships=[
                        Relationship(
                            related_entity_id=self._system_entity_id,
                            relationship_type=RelationshipType(
                                tracked_by=TrackedBy(
                                    actively_tracking_sensors=Sensors(
                                        sensors=[
                                            Sensor(
                                                sensor_id="wardragon-antenna",
                                                operational_state="OPERATIONAL_STATE_OPERATIONAL",
                                                sensor_type="SENSOR_TYPE_RF",
                                                sensor_description="WarDragon Antenna"
                                            )
                                        ]
                                    )
                                )
                            )
                        )
                    ]
                )
            except Exception as e:
                _log.debug("Could not create relationship for home: %s", e)

        try:
            self.client.entities.publish_entity(
                entity_id=entity_id,
                is_live=True,
                location=location,
                ontology=ontology,
                mil_view=mil_view,
                provenance=provenance,
                aliases=Aliases(name=str(display_name)),
                expiry_time=expiry_time,
                relationships=relationships,
                data_classification=Classification(
                    default=ClassificationInformation(level="CLASSIFICATION_LEVELS_UNCLASSIFIED")
                ),
                request_options=self._req_opts,
            )
        except Exception as e:
            _log.warning("Lattice publish_home failed for %s: %s", entity_id, e)