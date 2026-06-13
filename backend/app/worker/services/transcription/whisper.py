"""faster-whisper transcriber (CTranslate2 backend).

3-4x faster than the HuggingFace transformers implementation on CPU with
identical accuracy. The model is loaded lazily on first use and reused for
the lifetime of the worker process.

Hallucination guards
--------------------
- RMS silence check: chunks below -60 dBFS are skipped without calling the
  model.
- Compression-ratio check: repetitive output (crowd noise, music, silence)
  is discarded after inference.
"""

from __future__ import annotations

import struct
import wave
import zlib
from pathlib import Path
from threading import Lock

from app.core.logging import get_logger
from app.worker.services.transcription.base import (
    Transcriber,
    TranscriptionResult,
    TranscriptionSegment,
)

logger = get_logger(__name__)

_SILENCE_RMS_THRESHOLD = 0.001
_COMPRESSION_RATIO_THRESHOLD = 2.4


def _rms_of_wav(path: Path) -> float:
    try:
        with wave.open(str(path), "rb") as wf:
            n_frames = wf.getnframes()
            if n_frames == 0:
                return 0.0
            raw = wf.readframes(n_frames)
            if wf.getsampwidth() == 2:
                samples = struct.unpack(f"<{len(raw)//2}h", raw)
                return (sum(s * s for s in samples) / len(samples)) ** 0.5 / 32768.0
    except Exception:
        pass
    return 1.0


def _compression_ratio(text: str) -> float:
    encoded = text.encode()
    return len(encoded) / len(zlib.compress(encoded)) if encoded else 0.0


def _wav_duration(path: Path) -> float:
    try:
        with wave.open(str(path), "rb") as wf:
            return wf.getnframes() / wf.getframerate()
    except Exception:
        return 0.0


class WhisperTranscriber(Transcriber):
    def __init__(
        self,
        model_name: str,
        *,
        device: str = "cpu",
        default_language: str | None = None,
    ) -> None:
        # faster-whisper uses short names: "base", "small", etc.
        # Accept both "openai/whisper-base" and "base".
        self._model_name = model_name.split("/")[-1].replace("whisper-", "")
        self._device = device
        self._default_language = default_language
        self._model = None
        self._lock = Lock()

    def _ensure_model(self):
        if self._model is not None:
            return self._model
        with self._lock:
            if self._model is None:
                from faster_whisper import WhisperModel

                logger.info(
                    "Loading faster-whisper model",
                    extra={"fields": {"model": self._model_name, "device": self._device}},
                )
                # int8 quantization on CPU gives another ~2x speedup with
                # negligible quality loss for base/small models.
                compute_type = "int8" if self._device == "cpu" else "float16"
                self._model = WhisperModel(
                    self._model_name,
                    device=self._device,
                    compute_type=compute_type,
                )
        return self._model

    def transcribe(
        self, audio_path: Path, *, language: str | None = None
    ) -> TranscriptionResult:
        model = self._ensure_model()
        lang = language or self._default_language

        rms = _rms_of_wav(audio_path) if audio_path.suffix.lower() == ".wav" else 1.0
        if rms < _SILENCE_RMS_THRESHOLD:
            logger.info(
                "Silent chunk — skipping transcription",
                extra={"fields": {"path": str(audio_path), "rms": round(rms, 6)}},
            )
            return TranscriptionResult(text="", language=lang, segments=[])

        segments_iter, info = model.transcribe(
            str(audio_path),
            language=lang,
            beam_size=5,
            vad_filter=True,
            vad_parameters={"min_silence_duration_ms": 500},
        )
        # info.duration comes from faster-whisper and is valid for any format.
        audio_duration = info.duration or _wav_duration(audio_path)

        segments: list[TranscriptionSegment] = []
        full_text_parts: list[str] = []

        for seg in segments_iter:
            text = seg.text.strip()
            if not text:
                continue
            seg_end = seg.end if seg.end > seg.start else audio_duration
            segments.append(TranscriptionSegment(
                start=seg.start,
                end=seg_end,
                text=text,
            ))
            full_text_parts.append(text)

        full_text = " ".join(full_text_parts)

        if _compression_ratio(full_text) > _COMPRESSION_RATIO_THRESHOLD:
            logger.warning(
                "Discarding hallucinated output (high compression ratio)",
                extra={"fields": {
                    "path": str(audio_path),
                    "ratio": round(_compression_ratio(full_text), 2),
                    "preview": full_text[:80],
                }},
            )
            return TranscriptionResult(text="", language=lang, segments=[])

        detected_lang = info.language if lang is None else lang
        return TranscriptionResult(
            text=full_text,
            language=detected_lang,
            segments=segments,
        )
