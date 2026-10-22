"""Main-thread POSIX deadlines and a persistent, fail-closed sequence lease."""

from __future__ import annotations

import json
import os
import signal
import threading
import time
from contextlib import contextmanager
from pathlib import Path


class CaptureTimeout(BaseException):
    """Not Exception: collectors must not swallow the cleanup-triggering deadline."""


class CaptureInterrupted(BaseException):
    """Catchable termination; SIGKILL/process crashes cannot execute cleanup."""


class Deadline:
    def __init__(self, seconds: float):
        self.seconds = seconds

    def __enter__(self):
        if threading.current_thread() is not threading.main_thread() or not hasattr(
            signal, "setitimer"
        ):
            raise RuntimeError("Capture deadlines require the POSIX main thread")
        if self.seconds <= 0:
            raise CaptureTimeout("Capture deadline expired")
        self.started = time.monotonic()
        self.previous_handler = signal.getsignal(signal.SIGALRM)
        self.previous_timer = signal.getitimer(signal.ITIMER_REAL)
        remaining = self.previous_timer[0]
        signal.signal(signal.SIGALRM, self._expired)
        signal.setitimer(
            signal.ITIMER_REAL, min(self.seconds, remaining) if remaining else self.seconds
        )
        return self

    @staticmethod
    def _expired(signum, frame):
        raise CaptureTimeout("Bounded capture deadline expired")

    def __exit__(self, exc_type, exc_value, traceback):
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, self.previous_handler)
        if self.previous_timer[0]:
            remaining = self.previous_timer[0] - (time.monotonic() - self.started)
            if remaining > 0:
                signal.setitimer(signal.ITIMER_REAL, remaining, self.previous_timer[1])
            elif exc_type is None:
                raise CaptureTimeout("Outer capture deadline expired")


def write_json(path: Path, value: dict) -> None:
    """Publish complete artifacts atomically; interrupted writes are never final files."""
    temporary = path.with_suffix(".pending")
    with temporary.open("w", encoding="utf-8") as stream:
        json.dump(value, stream, sort_keys=True, indent=2, allow_nan=False)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


@contextmanager
def termination_cleanup():
    if threading.current_thread() is not threading.main_thread():
        raise RuntimeError("Capture must run on the main thread")
    previous = signal.getsignal(signal.SIGTERM)

    def interrupted(signum, frame):
        raise CaptureInterrupted("SIGTERM requested capture cleanup")

    signal.signal(signal.SIGTERM, interrupted)
    try:
        yield
    finally:
        signal.signal(signal.SIGTERM, previous)
