#!/bin/bash
#
# Wrapper script for running test_drone_generator.py
#
# This script manages the zmq-decoder service to free up port 4224
# for test_drone_generator.py to publish simulated drone telemetry.
#
# Usage:
#   ./run_test_scenario.sh --scenario scenario_4222_-7090.json --mode simulate --loop
#   ./run_test_scenario.sh --scenario my_test.json --mode replay
#

set -e  # Exit on error

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Service name
SERVICE_NAME="zmq-decoder.service"

# Track if we stopped the service
SERVICE_WAS_RUNNING=false
SERVICE_STOPPED=false

# Cleanup function - ensures service is restarted
cleanup() {
    local exit_code=$?

    if [ "$SERVICE_STOPPED" = true ]; then
        echo ""
        echo -e "${YELLOW}Restarting ${SERVICE_NAME}...${NC}"
        if sudo systemctl start "$SERVICE_NAME"; then
            echo -e "${GREEN}✓ Service restarted successfully${NC}"
        else
            echo -e "${RED}✗ Failed to restart service${NC}"
            echo -e "${YELLOW}Please manually restart: sudo systemctl start ${SERVICE_NAME}${NC}"
            exit 1
        fi
    fi

    exit $exit_code
}

# Set up trap to ensure cleanup runs on exit
trap cleanup EXIT INT TERM

# Print usage
usage() {
    echo "Usage: $0 [test_drone_generator.py arguments]"
    echo ""
    echo "Examples:"
    echo "  $0 --scenario scenario_4222_-7090.json --mode simulate --loop"
    echo "  $0 --scenario test.json --mode replay --dry-run"
    echo "  $0 --help"
    echo ""
    echo "This script:"
    echo "  1. Stops zmq-decoder service (to free port 4224)"
    echo "  2. Runs test_drone_generator.py with your arguments"
    echo "  3. Automatically restarts zmq-decoder when done"
    exit 1
}

# Check if help requested
if [ "$1" = "-h" ] || [ "$1" = "--help" ]; then
    usage
fi

# Check if running with sudo (we need it for systemctl)
if [ "$EUID" -eq 0 ]; then
    echo -e "${RED}✗ Do not run this script with sudo${NC}"
    echo "The script will prompt for sudo password when needed."
    exit 1
fi

# Check if systemctl is available
if ! command -v systemctl &> /dev/null; then
    echo -e "${RED}✗ systemctl not found${NC}"
    echo "This script requires systemd to manage the zmq-decoder service."
    exit 1
fi

# Check if test_drone_generator.py exists
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
GENERATOR_SCRIPT="$SCRIPT_DIR/test_drone_generator.py"

if [ ! -f "$GENERATOR_SCRIPT" ]; then
    echo -e "${RED}✗ test_drone_generator.py not found in $SCRIPT_DIR${NC}"
    exit 1
fi

echo -e "${GREEN}DragonSync Test Scenario Runner${NC}"
echo "========================================"
echo ""

# Check if service exists
if ! systemctl list-unit-files | grep -q "$SERVICE_NAME"; then
    echo -e "${YELLOW}⚠ Warning: ${SERVICE_NAME} not found${NC}"
    echo "Proceeding without stopping service..."
    echo ""
else
    # Check if service is running
    if systemctl is-active --quiet "$SERVICE_NAME"; then
        SERVICE_WAS_RUNNING=true
        echo -e "${YELLOW}Stopping ${SERVICE_NAME} to free port 4224...${NC}"

        if sudo systemctl stop "$SERVICE_NAME"; then
            SERVICE_STOPPED=true
            echo -e "${GREEN}✓ Service stopped${NC}"
            echo ""
            sleep 1  # Give the port time to be released
        else
            echo -e "${RED}✗ Failed to stop service${NC}"
            exit 1
        fi
    else
        echo -e "${GREEN}✓ ${SERVICE_NAME} is not running${NC}"
        echo ""
    fi
fi

# Run test_drone_generator.py with all arguments
echo -e "${GREEN}Starting test_drone_generator.py...${NC}"
echo "Arguments: $@"
echo ""
echo "Press Ctrl+C to stop the generator"
echo "========================================"
echo ""

python3 "$GENERATOR_SCRIPT" "$@"

# Cleanup will run automatically via trap
