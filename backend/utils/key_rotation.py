"""Round-robin API key rotation.

Lets SERP/Gemini calls cycle across multiple keys and advance to the next when
one hits a rate limit / quota error. Thread-safe (workers + API threads).
"""
from __future__ import annotations

import threading


def parse_keys(multi: str, single: str = "") -> list[str]:
    """Build a key list from a comma-separated string, falling back to a single key."""
    keys = [k.strip() for k in (multi or "").split(",") if k.strip()]
    if not keys and (single or "").strip():
        keys = [single.strip()]
    # de-dup, preserve order
    seen: set[str] = set()
    out: list[str] = []
    for k in keys:
        if k not in seen:
            seen.add(k)
            out.append(k)
    return out


class KeyRotator:
    def __init__(self, keys: list[str]):
        self._keys = keys
        self._lock = threading.Lock()
        self._i = 0

    def __bool__(self) -> bool:
        return bool(self._keys)

    def __len__(self) -> int:
        return len(self._keys)

    @property
    def keys(self) -> list[str]:
        return list(self._keys)

    def current(self) -> str:
        with self._lock:
            return self._keys[self._i] if self._keys else ""

    def advance(self) -> str:
        """Move to the next key and return it."""
        with self._lock:
            if not self._keys:
                return ""
            self._i = (self._i + 1) % len(self._keys)
            return self._keys[self._i]

    def ordered_from_current(self) -> list[str]:
        """Keys starting at the current index — for trying each once per request.
        Takes a consistent snapshot under the lock so concurrent advance() calls
        can't make a single pass skip or repeat keys."""
        with self._lock:
            keys = list(self._keys)
            start = self._i
        if not keys:
            return []
        n = len(keys)
        return [keys[(start + offset) % n] for offset in range(n)]
