# WarDragon Services

Systemd service files for the WarDragon kit.

> **Note**: The `zmq-decoder.service` file is owned and installed by the [droneid-go](https://github.com/alphafox02/droneid-go) repo via its `install.sh` script. Do not maintain a copy here — it will get out of sync. To update the service, update it in the droneid-go repo and re-run `sudo ./install.sh` on the kit.

## Service Map

| Service | Binary / Script | Source Repo | ZMQ Port | Description |
|---------|----------------|-------------|----------|-------------|
| `zmq-decoder` | `/home/dragon/WarDragon/droneid-go/droneid` | [droneid-go](https://github.com/alphafox02/droneid-go) | **pub 4224** | Unified Open Drone ID receiver (WiFi + BLE + UART + DJI) |
| `dji-receiver` | `/home/dragon/WarDragon/antsdr_dji_droneid/dji_receiver.py` | [antsdr_dji_droneid](https://github.com/alphafox02/antsdr_dji_droneid) | **pub 4221** | AntSDR DJI DroneID receiver |
| `dragonsync` | `/home/dragon/WarDragon/DragonSync/dragonsync.py` | [DragonSync](https://github.com/alphafox02/DragonSync) | sub 4224, 4225 | Gateway to TAK/CoT, MQTT, Lattice |
| `wardragon-monitor` | `/home/dragon/WarDragon/DragonSync/wardragon_monitor.py` | [DragonSync](https://github.com/alphafox02/DragonSync) | **pub 4225** | GPS and system health monitor |

## Data Flow

```
AntSDR E200                    Sniffle Dongle     Panda WiFi      ESP32 UART
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
