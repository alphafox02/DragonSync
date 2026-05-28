# WarDragon Services

Systemd service files for the WarDragon kit.

> **Note**: The `zmq-decoder.service` file is owned and installed by the [droneid-go](https://github.com/alphafox02/droneid-go) repo via its `install.sh` script. Do not maintain a copy here — it will get out of sync. To update the service, update it in the droneid-go repo and re-run `sudo ./install.sh` on the kit.

> **Note**: The `dji-receiver.service` file is owned by the [dragonsdr_dji_droneid](https://github.com/alphafox02/antsdr_dji_droneid) repo. Do not maintain a copy here — install it directly from that repo. See the dragonsdr_dji_droneid README for installation instructions.

## Service Map

| Service | Binary / Script | Source Repo | ZMQ Port | Description |
|---------|----------------|-------------|----------|-------------|
| `zmq-decoder` | `/home/dragon/WarDragon/droneid-go/droneid` | [droneid-go](https://github.com/alphafox02/droneid-go) | **pub 4224** | Unified Open Drone ID receiver (WiFi + BLE + UART + DJI) |
| `dji-receiver` | `/home/dragon/WarDragon/dragonsdr_dji_droneid/dji_receiver.py` | [dragonsdr_dji_droneid](https://github.com/alphafox02/antsdr_dji_droneid) | **pub 4221** | DragonSDR DJI DroneID receiver |
| `dragonsync` | `/home/dragon/WarDragon/DragonSync/dragonsync.py` | [DragonSync](https://github.com/alphafox02/DragonSync) | sub 4224, 4225 | Gateway to TAK/CoT, MQTT, Lattice |
| `wardragon-monitor` | `/home/dragon/WarDragon/DragonSync/wardragon_monitor.py` | [DragonSync](https://github.com/alphafox02/DragonSync) | **pub 4225** | GPS and system health monitor |

## Data Flow

```
DragonSDR                      Sniffle Dongle     Panda WiFi      ESP32 UART
     |                              |                  |               |
dji_receiver.py              droneid (native)    droneid (-g)    droneid (-uart)
  ZMQ 4221                         |                  |               |
     |                             +------------------+---------------+
     +-----------------------------+
                                   |
                            droneid-go (zmq-decoder)
                              ZMQ pub 4224
                                   |
                            DragonSync (sub 4224 + 4225)
                                   |
                         TAK / MQTT / Lattice / CoT
```

## Optional Services

| Service | Binary / Script | Source Repo | ZMQ Port | Description |
|---------|----------------|-------------|----------|-------------|
| `drone-logger` | `/home/dragon/WarDragon/DragonSync/utils/drone_logger.py` | [DragonSync](https://github.com/alphafox02/DragonSync) | sub 4224, 4225 | Offline SQLite/CSV drone logger (for `utils/log_viewer.py`) |

`drone-logger` is **opt-in and not enabled by default** — it duplicates telemetry to a local SQLite database for offline review with `utils/log_viewer.py`. The shipped unit logs to `logs/drones.sqlite` with daily rotation (7-day retention) and reads the status port (4225) so the `seen_by` column is populated with this kit's serial.

To enable it on a kit:

```bash
sudo cp services/drone-logger.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now drone-logger
```

Add `--rid-enabled` (and optionally `--rid-api`) to the `ExecStart` line to enrich rows with FAA Remote ID make/model — requires the `faa-rid-lookup` submodule (`git submodule update --init`).

## Legacy Services (zmqToTar1090)

| Service | Description |
|---------|-------------|
| `zmqtotar1090` | ZMQ to tar1090 bridge (not recommended for production) |
| `djizmqtotar1090` | DJI ZMQ to tar1090 bridge (not recommended for production) |

## Replaced Services

The following legacy Python services have been replaced by `droneid-go` (`zmq-decoder`):

- `sniff-receiver` — BLE capture via Python sniffle (now: `droneid -ble auto`)
- `wifi-receiver` — WiFi Remote ID capture via Python (now: `droneid -g`)
- `zmq-decoder` (old) — Python ZMQ aggregator (now: single Go binary)

The `droneid-go` installer (`install.sh`) automatically stops and disables these legacy services during installation.
