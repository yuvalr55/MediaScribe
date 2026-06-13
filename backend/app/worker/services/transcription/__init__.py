"""Transcriber factory.

A module-level singleton is reused across tasks within a worker process so the
model is loaded at most once per process.
"""

from __future__ import annotations

from app.config import Settings
from app.worker.services.transcription.base import Transcriber
from app.worker.services.transcription.fake import FakeTranscriber

_instance: Transcriber | None = None


def build_transcriber(settings: Settings) -> Transcriber:
    """Construct the configured transcriber (uncached)."""
    if settings.transcriber == "fake":
        return FakeTranscriber()
    if settings.transcriber == "whisper":
        from app.worker.services.transcription.whisper import WhisperTranscriber

        return WhisperTranscriber(
            settings.whisper_model,
            device=settings.whisper_device,
            default_language=settings.whisper_language,
        )
    raise ValueError(f"Unsupported transcriber: {settings.transcriber!r}")


def get_transcriber(settings: Settings) -> Transcriber:
    """Return a process-wide cached transcriber."""
    global _instance
    if _instance is None:
        _instance = build_transcriber(settings)
    return _instance
