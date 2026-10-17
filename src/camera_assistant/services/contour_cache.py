"""Small process-local cache of immutable contour JSON; no photos or disk I/O."""
from __future__ import annotations

from collections import OrderedDict
from threading import Lock


class MemoryContourCache:
    def __init__(self, *, max_entries: int = 16, max_bytes: int = 8 * 1024 * 1024):
        self.max_entries = max_entries
        self.max_bytes = max_bytes
        self._values: OrderedDict[bytes, bytes] = OrderedDict()
        self._size_bytes = 0
        self._lock = Lock()

    def get(self, key: bytes) -> bytes | None:
        with self._lock:
            value = self._values.get(key)
            if value is not None:
                self._values.move_to_end(key)
            return value

    def put(self, key: bytes, value: bytes) -> None:
        # JSON bytes are immutable and have a known memory bound. Mutable model
        # trees are never shared; callers parse their own independent result.
        if self.max_entries < 1 or len(value) > self.max_bytes:
            return
        with self._lock:
            previous = self._values.pop(key, None)
            if previous is not None:
                self._size_bytes -= len(previous)
            self._values[key] = value
            self._size_bytes += len(value)
            while len(self._values) > self.max_entries or self._size_bytes > self.max_bytes:
                _, evicted = self._values.popitem(last=False)
                self._size_bytes -= len(evicted)

    def clear(self) -> None:
        with self._lock:
            self._values.clear()
            self._size_bytes = 0

    def __len__(self) -> int:
        with self._lock:
            return len(self._values)

    @property
    def size_bytes(self) -> int:
        with self._lock:
            return self._size_bytes
