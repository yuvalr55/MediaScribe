"""JobsService._validate_content_type — extension fallback and rejection."""

from __future__ import annotations

import pytest

from app.api.services.jobs_service import JobsService
from app.core.exceptions import UnsupportedMediaTypeError


def _service(settings, storage):
    return JobsService(settings, storage, lambda _: None)


# ---------------------------------------------------------------------------
# Allowed content-type passes immediately
# ---------------------------------------------------------------------------

def test_allowed_content_type_passes(settings, storage):
    svc = _service(settings, storage)
    svc._validate_content_type("audio/wav", "clip.wav")  # should not raise


# ---------------------------------------------------------------------------
# Extension fallback (browsers send application/octet-stream)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("filename", [
    "recording.mp3",
    "video.mp4",
    "audio.m4a",
    "clip.wav",
    "call.ogg",
    "podcast.flac",
    "interview.webm",
])
def test_octet_stream_accepted_for_valid_extension(settings, storage, filename):
    svc = _service(settings, storage)
    svc._validate_content_type("application/octet-stream", filename)  # no raise


# ---------------------------------------------------------------------------
# Unknown extension is rejected
# ---------------------------------------------------------------------------

def test_unknown_extension_rejected(settings, storage):
    svc = _service(settings, storage)
    with pytest.raises(UnsupportedMediaTypeError):
        svc._validate_content_type("application/octet-stream", "document.pdf")


def test_no_extension_rejected(settings, storage):
    svc = _service(settings, storage)
    with pytest.raises(UnsupportedMediaTypeError):
        svc._validate_content_type("application/octet-stream", "noextension")


def test_text_content_type_with_valid_extension_rejected(settings, storage):
    svc = _service(settings, storage)
    with pytest.raises(UnsupportedMediaTypeError):
        svc._validate_content_type("text/plain", "audio.mp3")


def test_text_content_type_with_invalid_extension_rejected(settings, storage):
    svc = _service(settings, storage)
    with pytest.raises(UnsupportedMediaTypeError):
        svc._validate_content_type("text/plain", "document.txt")


def test_error_details_contain_extension(settings, storage):
    svc = _service(settings, storage)
    with pytest.raises(UnsupportedMediaTypeError) as exc_info:
        svc._validate_content_type("application/octet-stream", "file.xyz")
    assert exc_info.value.details["extension"] == "xyz"


def test_no_extension_details_is_none(settings, storage):
    svc = _service(settings, storage)
    with pytest.raises(UnsupportedMediaTypeError) as exc_info:
        svc._validate_content_type("application/octet-stream", "noext")
    assert exc_info.value.details["extension"] is None
