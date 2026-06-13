"""Transcription abstraction.

The rest of the system depends only on this Protocol — never on Whisper directly.
Swapping models (whisper-base -> large-v3, or an entirely different engine) is a
configuration change, and tests inject a deterministic fake so they run without a
GPU or any model download.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol, runtime_checkable


@dataclass
class TranscriptionSegment:
    start: float
    end: float
    text: str


@dataclass
class TranscriptionResult:
    text: str
    language: str | None = None
    segments: list[TranscriptionSegment] = field(default_factory=list)


@runtime_checkable
class Transcriber(Protocol):
    """Transcribes a single audio file into text with timestamped segments."""

    def transcribe(
        self, audio_path: Path, *, language: str | None = None
    ) -> TranscriptionResult:
        """Transcribe `audio_path`.

        Implementations are synchronous and CPU/GPU-bound on purpose: they run
        inside Celery worker *processes*, never on the API event loop.
        """
        ...
