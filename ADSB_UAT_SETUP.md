# ADS-B and UAT Integration for DragonSync

This guide explains how to integrate two Nooelec NESDR Nano 2+ SDRs for ADS-B (1090 MHz) and UAT (978 MHz) aircraft detection with DragonSync.

## Overview

The integration adds aircraft tracking capabilities to your WarDragon kit using:
- **1090 MHz ADS-B**: Commercial and general aviation aircraft (worldwide)
- **978 MHz UAT**: General aviation aircraft equipped with ADS-B Out (USA only)

### Architecture

```
SDR 1 (1090 MHz) → dump1090-fa → JSON → ADS-B ZMQ Bridge → DragonSync
                                         (port 30047)     (port 4226)

SDR 2 (978 MHz)  → dump978-fa  → JSON → UAT ZMQ Bridge   → DragonSync
                                         (port 30979)     (port 4227)

DragonSync → CoT/TAK + MQTT + Lattice Sinks
```

## Hardware Requirements

- 2x Nooelec NESDR Nano 2+ SDR dongles
- USB ports (preferably on a powered hub for better performance)
- Suitable antennas for 1090 MHz and 978 MHz

## Software Installation

### 1. Install Dependencies

```bash
# Activate virtual environment
source /home/dragon/WarDragon/.venv-dragon/bin/activate

# Install required Python packages
pip install pyzmq requests
```

### 2. Install readsb (ADS-B Decoder) - Recommended

**readsb** is the modern, actively-maintained alternative to dump1090-fa:

```bash
# Install readsb using the automatic installation script
sudo bash -c "$(wget -O - https://github.com/wiedehopf/adsb-scripts/raw/master/readsb-install.sh)"

# Reboot (only needed on first install)
sudo reboot
```

**Alternative: Manual Installation from Repository**

If you prefer manual control or the script doesn't work:

```bash
# Install build dependencies
sudo apt install -y build-essential debhelper librtlsdr-dev pkg-config \
  libusb-1.0-0-dev libncurses5-dev libbladerf-dev

# Clone and build readsb
git clone https://github.com/wiedehopf/readsb.git
cd readsb
make
sudo make install
```

### 3. Install dump978-fa (UAT Decoder)

**Option A: From FlightAware Repository (if available for your architecture)**

```bash
# Try the FlightAware repository
wget https://flightaware.com/adsb/piaware/files/packages/pool/piaware/f/flightaware-apt-repository/flightaware-apt-repository_1.1_all.deb
sudo dpkg -i flightaware-apt-repository_1.1_all.deb
sudo apt update
sudo apt install -y dump978-fa
```

**Option B: Build from Source**

If the repository doesn't work for your architecture:

```bash
# Install dependencies
sudo apt install -y build-essential debhelper librtlsdr-dev pkg-config \
  libusb-1.0-0-dev libsoapysdr-dev soapysdr-module-rtlsdr

# Clone and build dump978
git clone https://github.com/flightaware/dump978.git
cd dump978
make
sudo make install
```

### 4. Configure SDR Devices

Identify your SDR devices and assign serial numbers to prevent confusion:

```bash
# List connected RTL-SDR devices
rtl_test

# Set serial numbers for each SDR
# SDR 1 (for 1090 MHz ADS-B)
rtl_eeprom -d 0 -s 00001090

# SDR 2 (for 978 MHz UAT)
rtl_eeprom -d 1 -s 00000978

# Reboot or replug SDRs for changes to take effect
```

### 5. Configure readsb (ADS-B Decoder)

**If using automatic installation script:**

The readsb installation script sets things up automatically. To configure:

```bash
# Set your location (latitude/longitude)
sudo readsb-set-location <latitude> <longitude>

# Set gain (automatic gain control)
sudo readsb-gain autogain

# Or set specific gain value (0-49.6)
sudo readsb-gain 49.6
```

**If installed manually, create `/etc/default/readsb`:**

```bash
sudo nano /etc/default/readsb
```

Add:

```
# Use specific SDR device
RECEIVER_OPTIONS="--device 00001090 --gain -10 --net --fix"

# Enable JSON output on port 30047
NET_OPTIONS="--net-bi-port 30005 --net-bo-port 30004 --net-sbs-port 30003"

# Location
LAT=your_latitude
LON=your_longitude
```

**Note:** readsb automatically provides JSON on port 30047 (same as dump1090-fa)

### 6. Configure dump978-fa

Edit `/etc/default/dump978-fa`:

```bash
sudo nano /etc/default/dump978-fa
```

Add/modify these lines:

```
# Use specific SDR device
DEVICE="00000978"

# Enable JSON output on port 30979
RECEIVER_OPTIONS="--sdr driver=rtlsdr,serial=00000978 --raw-port 30978 --json-port 30979"
```

### 7. Configure DragonSync

The configuration has already been added to `config.ini`. Verify the settings:

```ini
# ADS-B and UAT Configuration
adsb_enabled = true
adsb_zmq_port = 4226
uat_enabled = true
uat_zmq_port = 4227
```

To disable either source, set `adsb_enabled` or `uat_enabled` to `false`.

## Service Installation

### 1. Copy Service Files

```bash
# Copy systemd service files
sudo cp /home/dragon/WarDragon/DragonSync/services/adsb-bridge.service /etc/systemd/system/
sudo cp /home/dragon/WarDragon/DragonSync/services/uat-bridge.service /etc/systemd/system/

# Reload systemd
sudo systemctl daemon-reload
```

### 2. Enable Services

```bash
# Enable readsb for ADS-B (if using automatic script, it's already enabled)
sudo systemctl enable readsb
sudo systemctl start readsb

# Enable dump978-fa for UAT
sudo systemctl enable dump978-fa
sudo systemctl start dump978-fa

# Enable ADS-B bridge
sudo systemctl enable adsb-bridge
sudo systemctl start adsb-bridge

# Enable UAT bridge
sudo systemctl enable uat-bridge
sudo systemctl start uat-bridge

# Restart DragonSync to pick up new sources
sudo systemctl restart dragonsync
```

## Verification

### 1. Check Decoder Status

```bash
# Check readsb
sudo systemctl status readsb
curl http://localhost:30047/data/aircraft.json

# Check dump978-fa
sudo systemctl status dump978-fa
curl http://localhost:30979/data/aircraft.json
```

### 2. Check Bridge Status

```bash
# Check ADS-B bridge
sudo systemctl status adsb-bridge
sudo journalctl -u adsb-bridge -f

# Check UAT bridge
sudo systemctl status uat-bridge
sudo journalctl -u uat-bridge -f
```

### 3. Check DragonSync Logs

```bash
sudo journalctl -u dragonsync -f | grep -E "ADS-B|UAT|aircraft"
```

You should see log entries like:
```
INFO - Connected to ADS-B ZMQ socket at tcp://127.0.0.1:4226
INFO - Connected to UAT ZMQ socket at tcp://127.0.0.1:4227
INFO - Added new ADS-B aircraft: aircraft-A12345 (UAL123)
INFO - Added new UAT aircraft: uat-A98765 (N12345)
```

## Troubleshooting

### No Aircraft Detected

1. **Check SDR devices are recognized:**
   ```bash
   lsusb | grep RTL
   rtl_test
   ```

2. **Verify decoders are receiving data:**
   ```bash
   # Check readsb messages
   sudo journalctl -u readsb -n 50

   # Check dump978-fa messages
   sudo journalctl -u dump978-fa -n 50
   ```

3. **Check antenna connections and positioning:**
   - Antennas should be mounted as high as possible
   - 1090 MHz antenna should be vertical
   - 978 MHz antenna should be vertical
   - Keep antennas away from metal objects

### Bridge Not Connecting

1. **Verify decoder JSON ports are accessible:**
   ```bash
   curl http://localhost:30047/data/aircraft.json
   curl http://localhost:30979/data/aircraft.json
   ```

2. **Check bridge logs:**
   ```bash
   sudo journalctl -u adsb-bridge -n 100
   sudo journalctl -u uat-bridge -n 100
   ```

3. **Test bridges manually:**
   ```bash
   source /home/dragon/WarDragon/.venv-dragon/bin/activate
   cd /home/dragon/WarDragon/DragonSync

   # Test ADS-B bridge
   python3 adsb_zmq_bridge.py --debug

   # Test UAT bridge (in another terminal)
   python3 uat_zmq_bridge.py --debug
   ```

### Performance Issues

1. **USB power issues:**
   - Use a powered USB hub
   - Avoid USB 3.0 ports (they can cause interference)

2. **CPU usage:**
   - Reduce poll interval in bridge services (default is 1.0 second)
   - Adjust max_drones limit in DragonSync config

3. **Decoder optimization:**
   ```bash
   # For readsb, adjust gain settings
   sudo readsb-gain autogain  # Automatic gain adjustment
   # Or:
   sudo readsb-gain 49.6     # Specific gain value

   # Check status
   sudo systemctl status readsb
   ```

## Advanced Configuration

### Custom ZMQ Ports

Edit the service files to use different ports:

```bash
sudo nano /etc/systemd/system/adsb-bridge.service
# Change --zmq-bind tcp://127.0.0.1:4226 to desired port

sudo nano /etc/systemd/system/uat-bridge.service
# Change --zmq-bind tcp://127.0.0.1:4227 to desired port

# Update config.ini accordingly
sudo nano /home/dragon/WarDragon/DragonSync/config.ini

sudo systemctl daemon-reload
sudo systemctl restart adsb-bridge uat-bridge dragonsync
```

### Polling Interval Adjustment

Modify the `--poll-interval` parameter in the service files:

```bash
# Faster updates (higher CPU usage)
--poll-interval 0.5

# Slower updates (lower CPU usage)
--poll-interval 2.0
```

### Position Filtering

Adjust position age filters to reduce duplicate messages:

```bash
# In service file, add:
--min-position-age 1.0   # Minimum time between position updates (seconds)
--max-position-age 60.0  # Maximum age of position data to accept (seconds)
```

## Integration with TAK/ATAK

Aircraft detected via ADS-B and UAT will automatically appear in TAK/ATAK if you have configured the TAK server settings in `config.ini`.

Aircraft will appear with:
- **ID**: `aircraft-<ICAO>` for ADS-B, `uat-<address>` for UAT
- **Type**: Aircraft icon based on category
- **Callsign**: Flight number or registration
- **Altitude**: In meters (converted from feet)
- **Speed**: In m/s (converted from knots)
- **Track**: Direction of travel

## Antenna Recommendations

### 1090 MHz ADS-B
- **Type**: 1/4 wave ground plane or collinear
- **Length**: ~69mm radiator
- **Connector**: SMA male
- **Recommended**: FlightAware 1090 MHz antenna or DIY coaxial collinear

### 978 MHz UAT
- **Type**: 1/4 wave ground plane
- **Length**: ~76mm radiator
- **Connector**: SMA male
- **Note**: Less critical than 1090 MHz as UAT range is typically shorter

## Data Output

Aircraft data is published to the same sinks as drone data:
- **CoT/TAK**: Real-time aircraft tracking in TAK/ATAK
- **MQTT**: Aircraft JSON messages (if MQTT is enabled)
- **Lattice**: Aircraft entity data (if Lattice is enabled)

Aircraft will be tracked with the same rate limiting and inactivity timeout as drones.

## Uninstallation

To remove ADS-B/UAT integration:

```bash
# Stop and disable services
sudo systemctl stop adsb-bridge uat-bridge readsb dump978-fa
sudo systemctl disable adsb-bridge uat-bridge readsb dump978-fa

# Remove service files
sudo rm /etc/systemd/system/adsb-bridge.service
sudo rm /etc/systemd/system/uat-bridge.service

# Disable in config
sudo nano /home/dragon/WarDragon/DragonSync/config.ini
# Set adsb_enabled = false and uat_enabled = false

# Restart DragonSync
sudo systemctl restart dragonsync
```

## Additional Resources

- **readsb Documentation**: https://github.com/wiedehopf/readsb
- **readsb Installation Scripts**: https://github.com/wiedehopf/adsb-scripts
- **dump978-fa Documentation**: https://github.com/flightaware/dump978
- **ADS-B Explained**: https://mode-s.org/decode/
- **RTL-SDR Setup**: https://www.rtl-sdr.com/
- **FlightAware Forum**: https://discussions.flightaware.com/

## License

This integration maintains the same MIT License as DragonSync.

Copyright (c) 2025 cemaxecuter
