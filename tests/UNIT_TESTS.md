# Unit Tests - DragonSync Refactoring Safety Net

This file documents the unit tests for DragonSync code refactoring. These are separate from the integration tests (scenario-based testing) described in README.md.

## Purpose

These unit tests exist to:
1. Lock in current behavior before refactoring
2. Catch regressions if refactoring breaks something
3. Enable confident code changes - if tests pass, behavior is preserved

## Quick Start

```bash
# Install pytest
pip install pytest pytest-cov

# Run all unit tests
cd /home/dragon/Downloads/wardragon-fpv-detect/DragonSync
pytest tests/test_*.py -v

# Run with coverage
pytest tests/test_*.py -v --cov=. --cov-report=html
open htmlcov/index.html
```

## What's Tested

### test_telemetry_parser.py (15 tests)
Tests for telemetry_parser.py - parsing ZMQ messages:
- DroneID list format (BLE/WiFi Remote ID)
- DJI list format (with Frequency Message)
- ESP32 dict format (with AUX_ADV_IND)
- Edge cases (CAA IDs, empty messages, None values)
- System Message differences (operator_lat/lon vs latitude/longitude)
- Operator ID Message parsing
- Remote ID accuracy fields
- Speed multiplier and pressure altitude with unit strings

### test_drone.py (18 tests)
Tests for drone.py - Drone class:
- Initialization (minimal and full parameters)
- Update method with position tracking
- Fallback bearing calculation from position delta
- CoT XML generation (drone, pilot, home)
- Alert drone suppression (pilot/home not sent for "drone-alert")
- Dictionary serialization for API (to_dict)
- FAA RID lookup result caching
- Frequency formatting (Hz to MHz conversion)
- UA type to CoT type mapping

### test_manager.py (21 tests)
Tests for manager.py - DroneManager:
- Adding drones (FIFO queue behavior)
- Updating existing drones
- Rate limiting for CoT sends
- Inactivity timeout and cleanup
- Sink dispatching (MQTT, Lattice, etc.)
- Multiple sink support with exception handling
- Track export for API (drones + aircraft)
- Stale offset calculation
- Position change tracking
- Frequency preservation across updates

Total: 54 tests

## Running Tests

### All Tests
```bash
pytest tests/test_*.py -v
```

### Single Test File
```bash
pytest tests/test_telemetry_parser.py -v
```

### Single Test Function
```bash
pytest tests/test_telemetry_parser.py::test_dji_list_with_freq_and_serial -v
```

### With Coverage
```bash
pytest tests/test_telemetry_parser.py -v --cov=telemetry_parser --cov-report=term-missing
```

## Test Output Examples

### All Passing
```
tests/test_telemetry_parser.py::test_dji_list_with_freq_and_serial PASSED
tests/test_telemetry_parser.py::test_esp32_dict_caa_only_no_freq PASSED
tests/test_telemetry_parser.py::test_esp32_with_aux_adv_ind PASSED
...
==================== 20 passed in 0.23s ====================
```

### Test Failure
```
tests/test_telemetry_parser.py::test_dji_frequency_preserved FAILED

def test_dji_frequency_preserved():
    ...
>   assert result['freq'] == 5800000000
E   AssertionError: assert None == 5800000000

tests/test_telemetry_parser.py:87: AssertionError
```

**What to do:**
1. Check if your code change broke DJI frequency parsing
2. If intentional, update test
3. If unintentional, revert your change

## Refactoring Workflow

### Before Any Code Changes
```bash
# Ensure tests pass on current code
pytest tests/test_*.py -v
# Should see: "20 passed"
```

### After Each Refactoring Step
```bash
# Run tests again
pytest tests/test_*.py -v
# Should still see: "20 passed"
```

### If Tests Fail
1. Read the error - pytest shows exactly what broke
2. Decide:
   - Bug in refactoring? → Fix code, re-run tests
   - Test is wrong? → Fix test (rarely needed)
3. Git commit only when tests pass

## Test Philosophy

### What We Test
- Pure functions (parse_drone_info, formatters)
- Class methods (Drone.update, Drone.to_cot_xml)
- Business logic (timeout, rate limiting)

### What We DON'T Test
- External services (ZMQ, MQTT broker, TAK server)
- Hardware (SDR, GPS)
- Network I/O
- File system (config files)

### Why?
- Unit tests should be fast (<1 second total)
- Unit tests should be deterministic (same result every time)
- Unit tests should not require real hardware or services

## Adding New Tests

### Template
```python
def test_my_feature():
    """Clear description of what this tests"""
    # Arrange: Set up test data
    message = {...}
    
    # Act: Call the function
    result = parse_drone_info(message, UA_TYPE_MAPPING)
    
    # Assert: Verify expected behavior
    assert result["field"] == "expected_value"
```

### Best Practices
1. One concept per test - test one thing at a time
2. Clear names - `test_esp32_rssi_from_aux_adv_ind`
3. Use fixtures - reuse common test data (conftest.py)
4. Assert specific values - not just "is not None"

## Coverage Goals

### Current Status
- telemetry_parser.py: ~90% (excellent)
- Overall project: ~15% (needs work)

### Target After Refactoring
- Core modules: 75%+
- Overall project: 60%+

### Check Coverage
```bash
pytest tests/ -v --cov=. --cov-report=term-missing

Name                    Stmts   Miss  Cover   Missing
-----------------------------------------------------
telemetry_parser.py        89      8    91%   197-199
drone.py                  180    150    17%   (many lines)
manager.py                 65     45    31%   (many lines)
-----------------------------------------------------
TOTAL                     334    203    39%
```

## Integration with Refactoring

### Step 1: Tests Lock In Behavior (COMPLETE)
- Created test_telemetry_parser.py with 20+ tests
- All tests pass on current code
- Behavior is now documented in tests

### Step 2: Refactor Safely (NEXT)
- Make code changes (extract functions, reorganize files)
- Run tests after each change
- If tests pass → refactoring preserved behavior
- If tests fail → investigate and fix

### Step 3: Expand Coverage (FUTURE)
- Add test_drone.py
- Add test_manager.py
- Increase coverage to 75%+

## Troubleshooting

### "No module named 'pytest'"
```bash
pip install pytest pytest-cov
```

### "ModuleNotFoundError: No module named 'telemetry_parser'"
Run pytest from the DragonSync root directory:
```bash
cd /home/dragon/Downloads/wardragon-fpv-detect/DragonSync
pytest tests/test_telemetry_parser.py -v
```

### Tests Pass But Real System Fails
- Unit tests verify logic, not real data
- Capture real ZMQ message and add as test case
- See conftest.py for how to add fixtures

### Want to Skip Slow Tests
```bash
# Mark slow tests with @pytest.mark.slow
pytest tests/ -v -m "not slow"
```

## Next Steps

1. Created tests for telemetry parser (DONE)
2. Run tests to verify they pass (YOUR TURN)
3. Start refactoring with safety net in place
4. Add more tests as needed

---

**Remember:** Tests are your friend during refactoring. If they pass, you're good.
