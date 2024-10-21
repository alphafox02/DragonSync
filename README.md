# DragonSync

## Features

- Leverages DroneID [DroneID GitHub](https://github.com/alphafox02/DroneID). Thanks to bkerler
- Supports ZeroMQ (ZMQ) for data transmission.
- Converts ZMQ messages to Cursor on Target (CoT) format.
- Provides integration with ATAK devices for Bluetooth Remote ID drone detection and monitoring.

## Requirements

- Sniffle compatible dongle
- ATAK device
- Python 3

## Setup and Usage

### Clone DroneID

```sh
git clone https://github.com/alphafox02/DroneID
cd DroneID
git submodule init
git submodule update
```

### Run the Sniffle Receiver

```sh
python3 DroneID/python_cli/sniff_receiver.py -l -e -a -z
```

This command configures the Sniffle dongle to look for Bluetooth 5 long range extended packets and forwards them via ZeroMQ (ZMQ).

```sh
python3 DroneID/zmq_decoder.py -z 
```

This starts the decoder, connects to the zmq server started by the receiver, and in turn offers decoded info over zmq on port 4224

### Start the SniffleToTAK Proxy with the Correct ZMQ Details

#### Without TAK Server Information (Multicast Only)

```sh
python3 sniffletotak.py --zmq-host 0.0.0.0 --zmq-port 4224
```

#### With TAK Server Information

```sh
python3 sniffletotak.py --zmq-host 0.0.0.0 --zmq-port 4224 --tak-host <tak_host> --tak-port <tak_port>
```

#### Enable Debug Logging

```sh
python3 sniffletotak.py --zmq-host 0.0.0.0 --zmq-port 4224 -d
```

Replace `<tak_host>` and `<tak_port>` with the appropriate values for your setup.

### Verify Multicast Reception on ATAK

Ensure that your ATAK device is connected to the same network as the machine running SniffleToTAK. If configured correctly, ATAK should receive the multicast CoT messages and display the drone information on the map.

## How It Works

1. The Sniffle compatible dongle captures Bluetooth 5 long range extended packets.
2. The captured packets are sent to the Sniffle receiver script which forwards them via ZeroMQ (ZMQ).
3. The SniffleToTAK proxy receives the ZMQ messages and translates them into CoT format.
4. The CoT messages are sent to a TAK server or multicast to the network for ATAK devices to detect and monitor drones.

## Example Command

To start the SniffleToTAK application with ZMQ server running on `127.0.0.1` port `4224`, sending multicast to ATAK:

```sh
python3 sniffletotak.py --zmq-host 127.0.0.1 --zmq-port 4224
```

## Troubleshooting

- **No Data on ATAK**:
  - Ensure the ATAK device is on the same network as the SniffleToTAK machine.
  - Verify that multicast traffic is allowed on your network.
  - Check if the correct ZMQ host and port are used.

- **Debugging**:
  - Use the `-d` flag to enable debug logging for more detailed output.
  - Use network monitoring tools like Wireshark to verify multicast traffic.

## License

```
MIT License

© 2024 cemaxecuter

Permission is hereby granted, free of charge, to any person obtaining a copy of this software and associated documentation files (the "Software"), to deal in the Software without restriction, including without limitation the rights to use, copy, modify, merge, publish, distribute, sublicense, and/or sell copies of the Software, and to permit persons to whom the Software is furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```
