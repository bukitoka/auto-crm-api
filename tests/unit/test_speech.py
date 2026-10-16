import io
import wave
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import UploadFile

from app.core.exceptions import BadRequestError, PayloadTooLargeError
from app.modules.assistant import speech


def wav(seconds: float = 0.1) -> bytes:
    output = io.BytesIO()
    with wave.open(output, "wb") as file:
        file.setnchannels(1)
        file.setsampwidth(2)
        file.setframerate(16000)
        file.writeframes(b"\0\0" * int(16000 * seconds))
    return output.getvalue()


class FakeModel:
    def __init__(self, *texts: str) -> None:
        self.texts = texts
        self.options: dict[str, Any] = {}

    def transcribe(self, audio: Any, **options: Any):
        self.options = options
        return (SimpleNamespace(text=text) for text in self.texts), None


@pytest.fixture
def model(monkeypatch: pytest.MonkeyPatch) -> FakeModel:
    fake = FakeModel(" Call Dana", " tomorrow at ten. ")
    monkeypatch.setattr(speech, "_model", lambda: fake)
    return fake


def test_decode_reads_a_recording() -> None:
    assert speech.decode(wav(0.1)).size == 1600


@pytest.mark.parametrize("data", [b"not audio at all" * 10, b"RIFF0000WAVE"])
def test_decode_rejects_unreadable_audio(data: bytes) -> None:
    with pytest.raises(BadRequestError, match="could not be read"):
        speech.decode(data)


def test_decode_rejects_a_recording_without_samples() -> None:
    with pytest.raises(BadRequestError, match="no audio"):
        speech.decode(wav(0))


def test_transcribe_joins_segments_and_filters_silence(model: FakeModel) -> None:
    assert speech.transcribe_audio(wav()) == "Call Dana tomorrow at ten."
    assert model.options["vad_filter"] is True


def test_transcribe_is_empty_without_speech(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(speech, "_model", lambda: FakeModel())
    assert speech.transcribe_audio(wav()) == ""


async def test_upload_is_transcribed(model: FakeModel) -> None:
    upload = UploadFile(io.BytesIO(wav()), filename="voice.webm")
    assert await speech.transcribe_upload(upload) == "Call Dana tomorrow at ten."


async def test_upload_must_not_be_empty() -> None:
    with pytest.raises(BadRequestError, match="empty"):
        await speech.transcribe_upload(UploadFile(io.BytesIO(b""), filename="voice.webm"))


async def test_upload_size_is_limited(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(speech, "MAX_AUDIO_BYTES", 10)
    with pytest.raises(PayloadTooLargeError):
        await speech.transcribe_upload(UploadFile(io.BytesIO(b"x" * 11), filename="voice.webm"))
