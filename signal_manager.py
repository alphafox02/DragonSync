#!/usr/bin/env python3
"""
Copyright 2025-2026 CEMAXECUTER LLC.

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

import threading
import time
from collections import deque
from typing import Dict, List, Optional


class SignalManager:
    """Tracks short-lived signal alerts for API export."""

    def __init__(self, ttl_s: float = 60.0, max_signals: int = 200):
        self.ttl_s = float(ttl_s)
        self.max_signals = max_signals
        self._lock = threading.Lock()
        self._signals: Dict[str, dict] = {}
        self._order: deque[str] = deque(maxlen=max_signals)

    def add_signal(self, signal: Dict) -> None:
        now = time.time()
        uid = signal.get("uid")
        if not uid:
            return

        signal["observed_at"] = now
        signal["expires_at"] = now + self.ttl_s

        with self._lock:
            self._signals[uid] = signal
            if uid in self._order:
                try:
                    self._order.remove(uid)
                except ValueError:
                    pass
            self._order.append(uid)
            self._prune_locked(now)

    def _prune_locked(self, now: Optional[float] = None) -> None:
        if now is None:
            now = time.time()
        expired = [uid for uid, sig in self._signals.items() if sig.get("expires_at", 0) <= now]
        for uid in expired:
            self._signals.pop(uid, None)
            try:
                self._order.remove(uid)
            except ValueError:
                pass
        while len(self._signals) > self.max_signals:
            try:
                uid = self._order.popleft()
            except IndexError:
                break
            self._signals.pop(uid, None)

    def export_signals(self) -> List[Dict]:
        now = time.time()
        with self._lock:
            self._prune_locked(now)
            return [dict(self._signals[uid]) for uid in list(self._order)]
