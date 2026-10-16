"""Speech to text for voice messages, run locally with faster-whisper (no API key needed).

The first transcription downloads the Whisper "base" model (about 140 MB) from Hugging Face
and loads it; it is cached on disk and kept in memory after that.
"""

import asyncio
import io
from functools import lru_cache

import av
import numpy as np
from fastapi import UploadFile
from faster_whisper import WhisperModel
from faster_whisper.audio import decode_audio

from app.core.exceptions import BadRequestError, PayloadTooLargeError

MAX_AUDIO_BYTES = 10 * 1024 * 1024
MODEL_SIZE = "base"


@lru_cache
def _model() -> WhisperModel:
    return WhisperModel(MODEL_SIZE, device="cpu", compute_type="int8")


def decode(data: bytes) -> np.ndarray:
    """16 kHz mono samples from any format ffmpeg reads (webm/opus, mp4/aac, wav...)."""
    try:
        samples = decode_audio(io.BytesIO(data))
    except (av.FFmpegError, ValueError, OSError) as exc:
        raise BadRequestError("The recording could not be read") from exc
    if not samples.size:
        raise BadRequestError("The recording has no audio")
    return samples


def transcribe_audio(data: bytes) -> str:
    """The spoken text, language auto-detected. Empty when nobody spoke."""
    # Without the VAD filter Whisper turns silence into "..." segments.
    segments, _ = _model().transcribe(decode(data), vad_filter=True)
    return " ".join(segment.text.strip() for segment in segments).strip()


async def transcribe_upload(upload: UploadFile) -> str:
    """Read an uploaded recording (max 10 MB) and transcribe it in a worker thread."""
    data = await upload.read(MAX_AUDIO_BYTES + 1)
    if len(data) > MAX_AUDIO_BYTES:
        raise PayloadTooLargeError("Recordings can be at most 10 MB")
    if not data:
        raise BadRequestError("The recording is empty")
    return await asyncio.to_thread(transcribe_audio, data)
