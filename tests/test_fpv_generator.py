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

import argparse
import time
from typing import List, Dict, Any

import zmq


def build_message(
    center_hz: float,
    bandwidth_hz: float,
    source: str,
    lat: float,
    lon: float,
    alt: float,
    pal: float,
    ntsc: float,
) -> List[Dict[str, Any]]:
    alert_id = f"fpv-alert-{center_hz/1e6:.3f}MHz"
    return [
        {
            "Basic ID": {
                "id_type": "Serial Number (ANSI/CTA-2063-A)",
                "id": alert_id,
                "description": "FPV Signal",
            }
        },
        {
            "Location/Vector Message": {
                "latitude": lat,
                "longitude": lon,
                "geodetic_altitude": alt,
                "height_agl": 0.0,
                "speed": 0.0,
                "vert_speed": 0.0,
            }
        },
        {
            "Self-ID Message": {
                "text": f"FPV alert ({source})",
            }
        },
        {
            "Frequency Message": {
                "frequency": center_hz,
            }
        },
        {
            "Signal Info": {
                "source": source,
                "center_hz": center_hz,
                "bandwidth_hz": bandwidth_hz,
                "pal_conf": pal,
                "ntsc_conf": ntsc,
            }
        },
    ]


def main() -> None:
    parser = argparse.ArgumentParser(description="Publish simulated FPV alert messages to ZMQ.")
    parser.add_argument("--zmq-host", default="127.0.0.1")
    parser.add_argument("--zmq-port", type=int, default=4226)
    parser.add_argument("--interval", type=float, default=2.0)
    parser.add_argument("--count", type=int, default=0, help="0 = run forever")
    parser.add_argument("--center-hz", type=float, default=5785000000.0)
    parser.add_argument("--bandwidth-hz", type=float, default=6000000.0)
    parser.add_argument("--source", choices=["energy", "confirm"], default="energy")
    parser.add_argument("--lat", type=float, default=34.0)
    parser.add_argument("--lon", type=float, default=-117.0)
    parser.add_argument("--alt", type=float, default=300.0)
    parser.add_argument("--pal", type=float, default=65.0)
    parser.add_argument("--ntsc", type=float, default=20.0)
    args = parser.parse_args()

    ctx = zmq.Context()
    socket = ctx.socket(zmq.PUB)
    socket.bind(f"tcp://{args.zmq_host}:{args.zmq_port}")
    time.sleep(0.5)

    msg = build_message(
        center_hz=args.center_hz,
        bandwidth_hz=args.bandwidth_hz,
        source=args.source,
        lat=args.lat,
        lon=args.lon,
        alt=args.alt,
        pal=args.pal,
        ntsc=args.ntsc,
    )

    sent = 0
    try:
        while True:
            socket.send_json(msg)
            sent += 1
            if args.count and sent >= args.count:
                break
            time.sleep(args.interval)
    finally:
        socket.close(0)
        ctx.term()


if __name__ == "__main__":
    main()
