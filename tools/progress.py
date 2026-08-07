from __future__ import annotations

import shutil
import sys
import threading
import time
from dataclasses import dataclass, field
from typing import TextIO


def _format_duration(seconds: float) -> str:
    seconds = max(0, round(seconds))
    minutes, sec = divmod(seconds, 60)
    hours, minute = divmod(minutes, 60)
    if hours:
        return f"{hours:d}:{minute:02d}:{sec:02d}"
    return f"{minute:02d}:{sec:02d}"


@dataclass
class ProgressBar:
    """Dependency-free terminal progress bar with elapsed time and ETA."""

    total: int
    label: str
    stream: TextIO = field(default_factory=lambda: sys.stderr)
    min_log_interval: float = 15.0
    _started: float = field(default_factory=time.monotonic, init=False)
    _last_log: float = field(default=0.0, init=False)
    _last_bucket: int = field(default=-1, init=False)
    _last_line_length: int = field(default=0, init=False)
    _current: int = field(default=0, init=False)
    _closed: bool = field(default=False, init=False)

    def __post_init__(self) -> None:
        if self.total < 0:
            raise ValueError("total must be non-negative")
        self.update(0, force=True)

    @property
    def interactive(self) -> bool:
        return bool(getattr(self.stream, "isatty", lambda: False)())

    def update(self, current: int, *, detail: str = "", force: bool = False) -> None:
        if self._closed:
            return
        current = min(max(current, 0), self.total)
        self._current = current
        now = time.monotonic()
        elapsed = now - self._started
        fraction = current / self.total if self.total else 1.0
        bucket = int(fraction * 10)

        if not self.interactive and not force:
            if bucket == self._last_bucket and now - self._last_log < self.min_log_interval:
                return

        rate = current / elapsed if current and elapsed > 0 else 0.0
        eta = (self.total - current) / rate if rate else None
        timing = f"elapsed {_format_duration(elapsed)}"
        if eta is not None and current < self.total:
            timing += f" / ETA {_format_duration(eta)}"

        if self.interactive:
            columns = shutil.get_terminal_size(fallback=(80, 24)).columns
            suffix = f" {current}/{self.total} {fraction:6.1%}  {timing}"
            if detail:
                suffix += f"  {detail}"
            bar_width = max(10, min(40, columns - len(self.label) - len(suffix) - 5))
            filled = round(bar_width * fraction)
            line = f"{self.label} [{'#' * filled}{'-' * (bar_width - filled)}]{suffix}"
            padding = " " * max(0, self._last_line_length - len(line))
            self.stream.write(f"\r{line}{padding}")
            self.stream.flush()
            self._last_line_length = len(line)
        else:
            detail_text = f" ({detail})" if detail else ""
            self.stream.write(
                f"[progress] {self.label}: {current}/{self.total} "
                f"({fraction:.0%}), {timing}{detail_text}\n"
            )
            self.stream.flush()

        self._last_log = now
        self._last_bucket = bucket

    def close(self, *, detail: str = "done") -> None:
        if self._closed:
            return
        if self._current < self.total:
            self.update(self.total, detail=detail, force=True)
        if self.interactive:
            self.stream.write("\n")
            self.stream.flush()
        self._closed = True

    def __enter__(self) -> "ProgressBar":
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        if exc_type is None:
            self.close()
        elif self.interactive:
            self.stream.write("\n")
            self.stream.flush()
            self._closed = True


@dataclass
class ProgressSpinner:
    """Show activity and elapsed time while the amount of work is unknown."""

    label: str
    stream: TextIO = field(default_factory=lambda: sys.stderr)
    interval: float = 0.2
    log_interval: float = 15.0
    _started: float = field(default_factory=time.monotonic, init=False)
    _stop_event: threading.Event = field(default_factory=threading.Event, init=False)
    _thread: threading.Thread | None = field(default=None, init=False)
    _last_line_length: int = field(default=0, init=False)

    @property
    def interactive(self) -> bool:
        return bool(getattr(self.stream, "isatty", lambda: False)())

    def _render(self, frame: str = "") -> None:
        elapsed = _format_duration(time.monotonic() - self._started)
        if self.interactive:
            line = f"{self.label} {frame}  elapsed {elapsed}"
            padding = " " * max(0, self._last_line_length - len(line))
            self.stream.write(f"\r{line}{padding}")
            self.stream.flush()
            self._last_line_length = len(line)
        else:
            self.stream.write(f"[progress] {self.label}: running, elapsed {elapsed}\n")
            self.stream.flush()

    def _run(self) -> None:
        frames = "|/-\\"
        index = 0
        next_log = time.monotonic() + self.log_interval
        while not self._stop_event.wait(self.interval):
            if self.interactive:
                self._render(frames[index % len(frames)])
                index += 1
            elif time.monotonic() >= next_log:
                self._render()
                next_log = time.monotonic() + self.log_interval

    def __enter__(self) -> "ProgressSpinner":
        self._render("|")
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=max(1.0, self.interval * 2))
        elapsed = _format_duration(time.monotonic() - self._started)
        status = "done" if exc_type is None else "failed"
        if self.interactive:
            line = f"{self.label} {status}  elapsed {elapsed}"
            padding = " " * max(0, self._last_line_length - len(line))
            self.stream.write(f"\r{line}{padding}\n")
        else:
            self.stream.write(f"[progress] {self.label}: {status}, elapsed {elapsed}\n")
        self.stream.flush()
