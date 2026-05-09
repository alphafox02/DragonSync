# DragonSync v2 — Multi-Kit MQTT Implementation Notes

**Branch:** `feature/multi-kit-v2`
**Goal:** fix MQTT for multi-kit deployments. Two or more kits sharing one broker must not stomp each other's retained state. Nothing else.

This doc travels with the branch. When v2 merges, this file is deleted from main as part of the merge cleanup.

---

## Scope (tightly bounded)

**In scope — change these:**

1. `sinks/mqtt_sink.py` — make the four hardcoded topics kit-scoped, make HA system device base kit-scoped, add lazy MQTT connect
2. `dragonsync.py` — pass `kit_id_provider` to `MqttSink` constructor
3. `docs/mqtt-schema.md` — update topic table to reflect v2 schema, mark v2 as the canonical schema

**Out of scope — do NOT touch:**

- Drone topics (`wardragon/drone/<id>`, `wardragon/drones`) — already correct
- Aircraft, signal, signal subtopic publishing — already correct
- HA per-drone discovery — already correct (drone_id is unique)
- The `signal_ingest.py` multi-protocol work — already correct, MAVLink-decoded drones flow through standard publish paths
- CoT, Lattice, HTTP API — none of these touch the affected MQTT topics

---

## File-by-file changes

### 1. `sinks/mqtt_sink.py`

#### A. Add `kit_id_provider` to constructor (around line 54)

Add to `__init__` kwargs:
```python
kit_id_provider: Optional[Callable[[], Optional[str]]] = None,
```

Stash it:
```python
self._kit_id_provider = kit_id_provider
```

Add a helper method (place near `_per_drone_topic`):
```python
def _kit_id(self) -> Optional[str]:
    """Return current kit_id (slugified) or None if not yet known."""
    if self._kit_id_provider is None:
        return None
    try:
        kid = self._kit_id_provider()
    except Exception:
        return None
    if not isinstance(kid, str) or not kid:
        return None
    if kid == "wardragon-unknown":
        return None
    return _slugify(kid)
```

The `_slugify` already exists in this file (line 938 area) and handles MQTT-special chars defensively.

#### B. Lazy MQTT connect (replace current connect path around lines 195-206)

Replace the immediate `connect_async` call with a deferred one. New flow:

1. After client setup but **before** `connect_async`, do **NOT** call `will_set` immediately. Defer until kit_id is known.
2. Spawn a small background watcher thread that polls `_kit_id()` every 0.5s.
3. When `_kit_id()` returns a real value:
   - `client.will_set(f"wardragon/service/{kit_id}/availability", "offline", qos=self.qos, retain=True)`
   - `client.connect_async(host, port, keepalive=keepalive)`
   - `client.loop_start()`
4. Timeout safety net: if kit_id is still unresolved after 60 seconds, set LWT to `wardragon/service/wardragon-unknown/availability` and connect anyway. Log a warning.

The existing best-effort wait at line 200-204 (`while not self.client.is_connected() and time.time() < deadline`) becomes obsolete; remove it. Document the behavior change: MqttSink construction no longer blocks on broker connection — it returns immediately.

#### C. `_on_connect` (around line 172) — birth message

Currently publishes:
```python
self.client.publish("wardragon/service/availability", "online", qos=self.qos, retain=True)
```

Change to:
```python
kit_id = self._kit_id()
if kit_id:
    self.client.publish(f"wardragon/service/{kit_id}/availability", "online", qos=self.qos, retain=True)
```

(The legacy unscoped birth is removed. Migrating consumers will see no LWT/birth on the unscoped topic. Coordinated with John during the RC cycle.)

#### D. `publish_system` (lines 794-848) — kit-scoped topics

Replace lines 846-848:
```python
self.client.publish(f"{self._sys_base}/attrs", json.dumps(attrs), qos=self.qos, retain=False)
self.client.publish(f"{self._sys_base}/state", "online", qos=self.qos, retain=False)
self.client.publish(f"{self._sys_base}/availability", "online", qos=self.qos, retain=True)
```

with:
```python
kit_id = self._kit_id()
if not kit_id:
    return  # not ready to publish kit-scoped state yet

scoped_base = f"{self._sys_base}/{kit_id}"
self.client.publish(f"{scoped_base}/attrs", json.dumps(attrs), qos=self.qos, retain=False)
self.client.publish(f"{scoped_base}/state", "online", qos=self.qos, retain=False)
self.client.publish(f"{scoped_base}/availability", "online", qos=self.qos, retain=True)
```

Note: this is a tightening — when kit_id isn't known yet, we skip publishing rather than emitting to a `wardragon/system/wardragon-unknown/...` placeholder. Consumers don't see system telemetry until kit_id is resolved (typically within 30s of cold boot, sooner otherwise).

#### E. `close()` (lines 319-334) — graceful offline on scoped topics

Replace the unscoped offline publishes (lines 324, 328) with:

```python
kit_id = self._kit_id()
if kit_id:
    try:
        self.client.publish(f"{self._sys_base}/{kit_id}/availability", "offline", qos=self.qos, retain=True)
    except Exception:
        pass
    try:
        self.client.publish(f"wardragon/service/{kit_id}/availability", "offline", qos=self.qos, retain=True)
    except Exception:
        pass
```

(Drop the legacy unscoped offline publishes.)

#### F. HA system device discovery (`_publish_ha_system_discovery`, line 853)

Currently uses constants:
```python
device = {
    "identifiers": [f"{self.ha_device_base}:system"],
    "name": "WarDragon System",
    ...
}
unique_base = f"{self.ha_device_base}_system"
```

Change `unique_base` to include kit_id:
```python
kit_id = self._kit_id()
if not kit_id:
    return  # don't publish discovery until we know which kit we are
unique_base = f"{self.ha_device_base}_{kit_id}_system"
device = {
    "identifiers": [f"{self.ha_device_base}:{kit_id}:system"],
    "name": f"WarDragon {kit_id}",
    ...
}
```

Update the `state_topic`, `attrs_topic`, and `avail` references to point at the new kit-scoped topics:
```python
avail = f"{self._sys_base}/{kit_id}/availability"
state_topic = f"{self._sys_base}/{kit_id}/state"
attrs_topic = f"{self._sys_base}/{kit_id}/attrs"
```

The `_ha_system_announced` flag (line 121) stays — it still prevents re-announce per process lifetime.

#### G. NOT changed in `mqtt_sink.py`

- Per-drone publishes (lines 391-404) — drone topics keep their current shape
- Per-drone availability (lines 245-249, 280-282, 314-315) — keep current shape (drone-keyed, not kit-keyed)
- Pilot/home attrs (lines 268-282, 301-315) — unchanged
- Signals (lines 411-435) — already kit-scoped via `seen_by`
- Aircraft (lines 444-452) — unchanged
- HA per-drone discovery (lines 678-790) — unchanged

---

### 2. `dragonsync.py`

#### Single change: pass `kit_id_provider` to `MqttSink`

In the `MqttSink(...)` instantiation around line 1203, add:
```python
mqtt_sink = MqttSink(
    # ... all existing args ...
    aircraft_topic=config.get("mqtt_aircraft_topic", "wardragon/aircraft"),
    kit_id_provider=lambda: KIT_ID,  # NEW
)
```

Pattern matches the existing `kit_id_provider=lambda: KIT_ID` already passed to `serve_api` at line 636. The lambda captures the module-global `KIT_ID` by reference, so when MqttSink calls it later, it sees the live value updated by the system status thread at line 801.

---

### 3. `docs/mqtt-schema.md`

Update the **Topic Structure** table to reflect v2:

Replace the four legacy rows:
```
| `wardragon/service/availability` | yes | LWT — online/offline |
| `wardragon/system/attrs` | no | kit telemetry |
| `wardragon/system/state` | no | kit textual state |
| `wardragon/system/availability` | yes | online while telemetry publishing |
```

with the v2 versions:
```
| `wardragon/service/<kit_id>/availability` | yes | DragonSync LWT — online while running, offline on shutdown/crash |
| `wardragon/system/<kit_id>/attrs` | no | WarDragon kit telemetry, scoped per kit |
| `wardragon/system/<kit_id>/state` | no | Kit textual state, scoped per kit |
| `wardragon/system/<kit_id>/availability` | yes | Online while kit telemetry is publishing, scoped per kit |
```

Add a short paragraph above the table:

> **Per-kit scoping:** As of v2.0, the system and service availability topics include a `<kit_id>` segment so multiple WarDragon kits can share a single MQTT broker without colliding on retained state. The legacy unscoped forms (`wardragon/system/attrs`, etc.) are no longer published. Consumers should subscribe to `wardragon/system/+/attrs` (wildcard) to receive every kit, or to `wardragon/system/<specific-kit-id>/attrs` for one kit.

Update the HA discovery row in the same table (around the entry for `homeassistant/sensor/<unique_id>/config`):

> Each kit appears as its own HA device (`wardragon_drone_<kit_id>_system_*`). Drone-level entities (`wardragon_drone_<drone_id>_*`) remain shared across kits since drones are identified by drone ID, not kit ID.

Bump version note at top: this is the v2.0 schema, drop any "v1" references.

---

## Test plan

### Unit-level

Add or update tests in `tests/test_mqtt_sink.py`:

1. **kit_id resolution** — `_kit_id()` returns None when provider is None, returns None when KIT_ID is `wardragon-unknown`, returns slugified kit_id otherwise
2. **publish_system topic shape** — when kit_id is set, publish goes to `wardragon/system/<kit_id>/attrs`; when not set, no publish
3. **HA system discovery topic shape** — config goes to `homeassistant/.../wardragon_drone_<kit_id>_system/config`, state_topic references the scoped attrs topic
4. **close() topic shape** — graceful offline goes to scoped topics

### Integration (single kit)

1. Start DragonSync against a local broker
2. `mosquitto_sub -t 'wardragon/#' -v` — confirm:
   - First few seconds: no MQTT traffic (lazy connect waiting for kit_id)
   - Once kit_id arrives: birth on `wardragon/service/<kit_id>/availability`, attrs on `wardragon/system/<kit_id>/attrs`
   - HA discovery configs reference the kit-scoped device
3. Kill DragonSync gracefully — confirm offline on the scoped service availability topic
4. Confirm no traffic on the legacy unscoped topics (`wardragon/system/availability`, `wardragon/service/availability`) — they should be silent

### Integration (multi-kit simulation)

1. Run two DragonSync instances against one broker, each with a distinct simulated kit_id
2. `mosquitto_sub -t 'wardragon/system/+/availability' -v` — both kits visible, neither stomps the other
3. Kill kit B — kit B's availability flips to offline, kit A unaffected
4. Restart kit B — kit B comes back online, A remains online throughout

### Real-kit testing (post-implementation)

After unit + integration tests pass, deploy to a real kit and exercise:
- Cold-boot startup time (verify DragonSync starts immediately, MQTT connects within 30-60s after wardragon_monitor's first emit)
- Standard drone detection traffic continues flowing
- HA dashboard correctly shows the new per-kit device after the discovery refresh
- Lattice / TAK output is unaffected (sanity check that we didn't accidentally break adjacent paths)

---

## Done criteria

- [ ] All four hardcoded topics in `mqtt_sink.py` are kit-scoped
- [ ] HA `_publish_ha_system_discovery` produces per-kit unique IDs and references kit-scoped topics
- [ ] LWT lifecycle works correctly via lazy-connect (no startup blocking)
- [ ] `dragonsync.py` passes `kit_id_provider` to MqttSink
- [ ] `mqtt-schema.md` reflects v2 topic structure with kit-scoping note
- [ ] Unit tests pass
- [ ] Single-kit integration test passes (no regression)
- [ ] Multi-kit simulation test passes (collision-free)
- [ ] One real-kit smoke test passes
- [ ] John has tested his consumer subscription against an RC build
- [ ] Branch ready to merge as `v2.0.0`

---

## Migration note for consumers

When this lands and merges to main as v2.0:

- **MQTT consumers** who subscribed to `wardragon/system/attrs`, `wardragon/system/state`, `wardragon/system/availability`, `wardragon/service/availability` — these topics no longer publish. Subscribe to the wildcard form (`wardragon/system/+/attrs` etc.) or to a specific kit (`wardragon/system/wardragon-G6PA14100J63/attrs`).
- **Home Assistant users** — existing `wardragon_drone_system_*` entities orphan once. New `wardragon_drone_<kit_id>_system_*` entities take their place automatically. Delete orphaned entities manually.
- **Drone topics** — completely unchanged. No consumer action required.
- **Aircraft, signals, drone aggregate** — completely unchanged.
- **TAK / CoT, Lattice, HTTP API** — completely unchanged. None of these touch the affected MQTT topics.
