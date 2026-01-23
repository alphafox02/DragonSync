# DragonSync Testing Tools

This directory contains tools for testing DragonSync without requiring live drone hardware or detections.

## Overview

The testing workflow consists of three main tools:

1. **`generate_scenario.py`** - Generate realistic drone flight scenarios
2. **`run_test_scenario.sh`** - Run test scenarios (disables ZMQ-Decoder to free up port until sim is exited)
3. **`verify_scenario.py`** - Verify scenario files meet constraints

## Quick Start

```bash
# 1. Generate a scenario at your location
python3 generate_scenario.py --lat 41.901 --lon -70.678

# 2. Run the test scenario
./run_test_scenario.sh --scenario scenario_4190_-7067.json --mode simulate --loop

# 3. Watch DragonSync process the simulated drones
# (DragonSync should be running in another terminal)
```

---

## Tool 1: generate_scenario.py

Generates realistic drone flight scenarios with randomized flight paths.

### Features

- **3 flight patterns**: Grid, Circular, Point-to-Point
- **Realistic constraints**:
  - Home locations: Within 1 mile of center coordinates
  - Pilot locations: Within 100 feet of home
  - Flight paths: 50-5000 feet from home point
  - Altitudes: 50-400 feet AGL (each drone different)
  - Speeds: 5-25 m/s
  - Duration: 2-4 minutes
- **Realistic identifiers**: Serial numbers, MAC addresses, operator IDs
- **Reproducible**: Use `--seed` for deterministic generation

### Usage

```bash
# Generate scenario at specific coordinates
python3 generate_scenario.py --lat 41.901 --lon -70.678

# Generate with seed for reproducibility
python3 generate_scenario.py --lat 41.901 --lon -70.678 --seed 12345

# Specify custom output filename
python3 generate_scenario.py --lat 37.7749 --lon -122.4194 --output my_scenario.json
```

### Output

Creates a JSON file compatible with `test_drone_generator.py`:

```
scenario_4190_-7067.json  (coordinates truncated to 4 digits)
```

File contains 3 drones with different flight patterns:
- **Drone 1**: Grid pattern (lawn mower survey)
- **Drone 2**: Circular pattern (orbit)
- **Drone 3**: Point-to-point pattern (waypoint navigation)

### Examples

```bash
# San Francisco
python3 generate_scenario.py --lat 37.7749 --lon -122.4194

# New York
python3 generate_scenario.py --lat 40.7128 --lon -74.0060

# Miami
python3 generate_scenario.py --lat 25.7617 --lon -80.1918
```

---

## Tool 2: run_test_scenario.sh

Wrapper script that manages the `zmq-decoder` service to avoid port conflicts.
If the scenario JSON includes an `fpv` block, it also launches the FPV generator.

### What it does

1. Stops `zmq-decoder.service` (frees port 4224)
2. Runs `test_drone_generator.py` with your arguments
3. Automatically restarts `zmq-decoder.service` when done (even if interrupted)

### Usage

```bash
# Run simulated drone flight (looping)
./run_test_scenario.sh --scenario scenario_4190_-7067.json --mode simulate --loop

# Run once (no loop)
./run_test_scenario.sh --scenario scenario_4190_-7067.json --mode simulate

# Dry run (no ZMQ, just print to console)
./run_test_scenario.sh --scenario scenario_4190_-7067.json --mode simulate --dry-run

# Show help
./run_test_scenario.sh --help
```

### Test Modes

**Simulate Mode** (recommended for testing flight paths):
```bash
./run_test_scenario.sh --scenario scenario_4190_-7067.json --mode simulate --loop
```
- Animates drones along flight paths
- Updates every 1 second
- Interpolates between waypoints
- Loops indefinitely (with `--loop`)

**Replay Mode** (for testing static detections):
```bash
./run_test_scenario.sh --scenario test_scenarios.json --mode replay --interval 2.0
```
- Sends static detection messages
- Customizable interval between messages

### Important Notes

- **Requires sudo**: The script needs sudo to stop/start the systemd service
- **Auto-cleanup**: Service is restarted even if you Ctrl+C
- **No manual service management**: Everything is automated

---

## Tool 3: verify_scenario.py

Verifies that generated scenario files meet all constraints.

### Usage

```bash
python3 verify_scenario.py scenario_4190_-7067.json
```

### Output Example

```
Verifying: scenario_4190_-7067.json

Drone 1: Parrot ANAFI - Grid Pattern
  Pilot distance from home: 71.1 ft (should be < 100 ft)
  Flight path distance from home: 124.6 - 1966.5 ft
    (should be between 50 - 5000 ft)
  Altitude: 377 ft AGL (should be 50-400 ft)
  Speed: 19.8 m/s (should be 5-25 m/s)
  Estimated flight time: 2.2 min (should be 2-4 min)
  Waypoints: 10

Drone 2: Skydio X2 - Circular Pattern
  ...
```

Use this to:
- Verify generated scenarios are valid
- Debug custom scenario files
- Ensure constraints are met

---

## Complete Testing Workflow

### 1. Generate a Test Scenario

```bash
cd tests/
python3 generate_scenario.py --lat 41.90 --lon -70.67
# Creates: scenario_4190_-7067.json
```

### 2. Verify the Scenario (Optional)

```bash
python3 verify_scenario.py scenario_4190_-7067.json
```

### 3. Start DragonSync (if not already running)

```bash
# In another terminal
cd ..
python3 dragonsync.py
```

### 4. Run the Test Scenario

```bash
./run_test_scenario.sh --scenario scenario_4190_-7067.json --mode simulate --loop
```

### 5. Observe DragonSync Processing

Watch DragonSync logs to see:
- Drone detections
- CoT messages sent to TAK
- MQTT messages published
- Lattice entity updates (if enabled)

### 6. Stop the Test (Ctrl+C)

The wrapper script will automatically restart `zmq-decoder.service`

---

## Manual Testing (Alternative)

If you prefer to manage services manually:

### Step 1: Stop zmq-decoder

```bash
sudo systemctl stop zmq-decoder.service
```

### Step 2: Run test generator

```bash
python3 test_drone_generator.py --scenario scenario_4190_-7067.json --mode simulate --loop
```

### Step 3: Restart zmq-decoder (when done)

```bash
sudo systemctl start zmq-decoder.service
```

---

## Advanced Usage

### Custom Flight Patterns

Edit generated JSON files to customize:
- Waypoint locations
- Speeds
- Altitudes
- Dwell times
- Flight paths

### Dry Run Testing

Test scenario generation without ZMQ:

```bash
./run_test_scenario.sh --scenario scenario_4190_-7067.json --mode simulate --dry-run
```

Output shows drone positions and status without publishing to ZMQ.

### Multiple Scenarios

Generate multiple scenarios for different test cases:

```bash
python3 generate_scenario.py --lat 41.901 --lon -70.678 --seed 1 --output urban.json
python3 generate_scenario.py --lat 41.901 --lon -70.678 --seed 2 --output suburban.json
python3 generate_scenario.py --lat 41.901 --lon -70.678 --seed 3 --output rural.json
```

### Debugging with ZMQ Listener

Use the included listener to debug ZMQ messages:

```bash
# Terminal 1: Start listener
python3 test_zmq_listener.py --verbose

# Terminal 2: Run test
./run_test_scenario.sh --scenario sscenario_4190_-7067.json --mode simulate
```

---

## Troubleshooting

### Port 4224 Already in Use

If you see `ZMQError: Address already in use`:

**Solution 1**: Use the wrapper script (recommended)
```bash
./run_test_scenario.sh --scenario scenario.json --mode simulate --loop
```

**Solution 2**: Use a different port
```bash
python3 test_drone_generator.py --zmq-port 4226 --scenario scenario.json
# Then update DragonSync config.ini: zmq_port = 4226
```

**Solution 3**: Manually stop the service
```bash
sudo systemctl stop zmq-decoder.service
python3 test_drone_generator.py --scenario scenario.json --mode simulate
sudo systemctl start zmq-decoder.service  # Don't forget!
```

### Service Won't Restart

If `zmq-decoder.service` won't restart after testing:

```bash
# Check service status
sudo systemctl status zmq-decoder.service

# View logs
sudo journalctl -u zmq-decoder.service -n 50

# Manually restart
sudo systemctl restart zmq-decoder.service
```

### DragonSync Not Receiving Messages

1. Verify DragonSync is running: `ps aux | grep dragonsync`
2. Check DragonSync config: `zmq_port = 4224` in `config.ini`
3. Verify test generator is publishing:
   ```bash
   # Use dry-run to see messages
   ./run_test_scenario.sh --scenario scenario.json --mode simulate --dry-run
   ```
4. Test with ZMQ listener:
   ```bash
   python3 test_zmq_listener.py
   ```

### Generated Scenarios Invalid

If scenarios don't meet constraints:

```bash
# Verify the scenario
python3 verify_scenario.py scenario_4190_-7067.json

# Regenerate with different seed
python3 generate_scenario.py --lat 41.901 --lon -70.678 --seed 999
```

### Permission Denied on Wrapper Script

```bash
chmod +x run_test_scenario.sh
./run_test_scenario.sh --scenario scenario.json --mode simulate
```

---

## File Reference

| File | Purpose |
|------|---------|
| `generate_scenario.py` | Generate drone flight scenarios |
| `run_test_scenario.sh` | Wrapper to run tests (manages services) |
| `test_drone_generator.py` | Publishes drone telemetry to ZMQ |
| `test_fpv_generator.py` | Publishes FPV signal alerts to ZMQ |
| `test_zmq_listener.py` | Debug tool to view ZMQ messages |
| `verify_scenario.py` | Validate scenario files |
| `test_scenarios.json` | Example scenario file with static/animated tracks |

---

## Tips

- **Use `--loop`** for continuous testing
- **Use `--dry-run`** to verify scenarios without ZMQ
- **Use `--seed`** for reproducible test scenarios
- **Use `verify_scenario.py`** before running tests
- **Keep scenarios small** (2-4 minute flights) for faster testing
- **Monitor DragonSync logs** to verify integration

---

## Example: Full Test Session

```bash
# Generate scenario for Boston area
python3 generate_scenario.py --lat 42.3601 --lon -71.0589

# Generate scenario with FPV alerts
python3 generate_scenario.py --lat 42.3601 --lon -71.0589 --fpv

# Verify it's valid
python3 verify_scenario.py scenario_4236_-7106.json

# Run the test (in another terminal, have DragonSync running)
./run_test_scenario.sh --scenario scenario_4236_-7106.json --mode simulate --loop

# Watch DragonSync process the drones
# Press Ctrl+C when done
# zmq-decoder service automatically restarts
```

---

## Example: FPV Signal Test

```bash
# In one terminal, run DragonSync with fpv_enabled=true
python3 test_fpv_generator.py --zmq-host 127.0.0.1 --zmq-port 4226 --source energy --interval 2

# Optional confirm alert (default ingest only takes confirm)
python3 test_fpv_generator.py --zmq-host 127.0.0.1 --zmq-port 4226 --source confirm --interval 2
```

---

## Contributing

When creating new test scenarios:
1. Use `generate_scenario.py` as a template
2. Follow the JSON structure in `test_scenarios.json`
3. Verify with `verify_scenario.py`
4. Test with `run_test_scenario.sh`

---

## License

MIT License - See main DragonSync LICENSE file
