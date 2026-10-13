"""Local detector subprocess interface. No torch or detector framework imports here."""

from .client import DetectorClient, detect, readiness, stop_worker

__all__ = ["DetectorClient", "detect", "readiness", "stop_worker"]
