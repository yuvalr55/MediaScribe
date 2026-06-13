"""Audio chunking strategies.

Two implementations are provided:

FixedWindowChunker  — fixed-length overlapping windows (simple, no I/O).
VadChunker          — snaps each target boundary to the nearest silence point
                      detected by ffmpeg's silencedetect filter. Chunks never
                      cut mid-utterance, so no overlap or post-stitch merging is
                      needed. Falls back to the fixed boundary when no silence is
                      found within the search radius.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable


@dataclass(frozen=True)
class ChunkSpec:
    """A planned chunk: its index and time window on the global timeline."""

    index: int
    start_seconds: float
    end_seconds: float

    @property
    def duration_seconds(self) -> float:
        return self.end_seconds - self.start_seconds


@runtime_checkable
class ChunkingStrategy(Protocol):
    def plan(self, total_seconds: float) -> list[ChunkSpec]:
        """Return the chunk windows covering `[0, total_seconds]`."""
        ...


class FixedWindowChunker(ChunkingStrategy):
    """Fixed-length windows with a constant overlap between neighbours."""

    def __init__(self, window_seconds: float, overlap_seconds: float) -> None:
        if window_seconds <= 0:
            raise ValueError("window_seconds must be positive")
        if not 0 <= overlap_seconds < window_seconds:
            raise ValueError("overlap must be in [0, window)")
        self._window = window_seconds
        self._overlap = overlap_seconds

    def plan(self, total_seconds: float) -> list[ChunkSpec]:
        if total_seconds <= 0:
            return []
        step = self._window - self._overlap
        specs: list[ChunkSpec] = []
        start = 0.0
        index = 0
        while start < total_seconds:
            end = min(start + self._window, total_seconds)
            specs.append(ChunkSpec(index=index, start_seconds=start, end_seconds=end))
            if end >= total_seconds:
                break
            start += step
            index += 1
        return specs


class VadChunker(ChunkingStrategy):
    """Splits at silence points near each target boundary.

    For each ideal boundary (multiples of `window_seconds`), searches within
    ±`search_radius` seconds for the nearest detected silence midpoint and uses
    that as the actual split. Falls back to the ideal boundary when no silence
    is found. Because splits land in silent gaps, no overlap is needed and no
    sentence will ever be cut mid-utterance.
    """

    # Minimum chunk size: prevents degenerate slivers if silences cluster.
    _MIN_CHUNK_SECONDS = 5.0

    def __init__(
        self,
        window_seconds: float,
        silence_points: list[float],
        *,
        search_radius: float = 5.0,
    ) -> None:
        if window_seconds <= 0:
            raise ValueError("window_seconds must be positive")
        self._window = window_seconds
        self._silence = sorted(silence_points)
        self._radius = search_radius

    def _nearest_silence(self, target: float, lo: float, hi: float) -> float | None:
        """Return the silence midpoint closest to `target` in (lo, hi), or None."""
        candidates = [s for s in self._silence if lo < s < hi]
        if not candidates:
            return None
        return min(candidates, key=lambda s: abs(s - target))

    def plan(self, total_seconds: float) -> list[ChunkSpec]:
        if total_seconds <= 0:
            return []

        # Build the ideal split targets (exclude 0 and total).
        targets: list[float] = []
        t = self._window
        while t < total_seconds:
            targets.append(t)
            t += self._window

        # Snap each target to a nearby silence or keep the ideal boundary.
        boundaries = [0.0]
        for tgt in targets:
            prev = boundaries[-1]
            lo = max(prev + self._MIN_CHUNK_SECONDS, tgt - self._radius)
            hi = min(total_seconds - self._MIN_CHUNK_SECONDS, tgt + self._radius)
            if lo >= hi:
                # Not enough room to search — use ideal boundary if valid.
                if tgt > prev + self._MIN_CHUNK_SECONDS:
                    boundaries.append(tgt)
                continue
            split = self._nearest_silence(tgt, lo, hi) or tgt
            if split > prev + self._MIN_CHUNK_SECONDS:
                boundaries.append(split)
        boundaries.append(total_seconds)

        return [
            ChunkSpec(index=i, start_seconds=boundaries[i], end_seconds=boundaries[i + 1])
            for i in range(len(boundaries) - 1)
        ]
