#!/usr/bin/env python3
"""
Optional sinks for DragonSync (MQTT, Lattice, etc.).

Sinks are lazy-imported to avoid dependency errors when optional packages aren't installed.
"""

__all__ = ['MqttSink', 'LatticeSink']
