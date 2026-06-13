"""Deterministic fake transcriber for tests and local smoke runs.

Selected via ``TRANSCRIBER=fake``. Produces a stable, predictable result without
loading any model — this is what lets the entire test suite run in CI in seconds
with no GPU and no network.
"""

from __future__ import annotations

from pathlib import Path

from app.worker.services.transcription.base import (
    Transcriber,
    TranscriptionResult,
    TranscriptionSegment,
)


class FakeTranscriber(Transcriber):
    def transcribe(
        self, audio_path: Path, *, language: str | None = None
    ) -> TranscriptionResult:
        text = f"transcript of {audio_path.name}"
        return TranscriptionResult(
            text=text,
            language=language or "en",
            segments=[TranscriptionSegment(start=0.0, end=1.0, text=text)],
        )
