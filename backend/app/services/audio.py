from __future__ import annotations

import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

import imageio_ffmpeg
from fastapi import UploadFile, status

from app.config import get_settings
from app.errors import raise_api_error


PCM_BYTES_PER_SECOND = 16_000 * 2
PCM_CONTENT_TYPES = {
    "application/octet-stream",
    "audio/pcm",
    "audio/l16",
    "audio/x-raw",
}
MP3_CONTENT_TYPES = {"audio/mpeg", "audio/mp3"}


@dataclass(frozen=True)
class PreparedAudio:
    """Validated audio plus the bytes that should be sent upstream."""

    pcm: bytes
    upstream_data: bytes | None
    source_format: str
    source_bytes: int


def _duration_seconds(pcm: bytes) -> float:
    return len(pcm) / PCM_BYTES_PER_SECOND


def _validate_pcm(pcm: bytes) -> bytes:
    settings = get_settings()
    duration = _duration_seconds(pcm)
    if duration < settings.min_audio_seconds:
        raise_api_error(status.HTTP_400_BAD_REQUEST, "recording_too_short", "录音太短")
    if duration > settings.max_audio_seconds:
        raise_api_error(
            status.HTTP_400_BAD_REQUEST,
            "recording_too_long",
            f"录音超过 {settings.max_audio_seconds:.0f} 秒",
        )
    return pcm


def _decode_to_pcm(raw: bytes, filename: str) -> bytes:
    """Decode a supported compressed upload for duration/quota validation."""
    # 系统 ffmpeg 优先，否则用 imageio-ffmpeg 内置的静态二进制
    try:
        ffmpeg = shutil.which("ffmpeg") or imageio_ffmpeg.get_ffmpeg_exe()
    except RuntimeError:
        ffmpeg = None
    if ffmpeg is None:
        raise_api_error(
            status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            "unsupported_audio",
            "仅支持 16k/16bit/mono PCM；如需上传其他格式，请在后端安装 ffmpeg",
        )

    suffix = Path(filename).suffix or ".audio"
    with tempfile.TemporaryDirectory() as tmpdir:
        input_path = Path(tmpdir) / f"input{suffix}"
        output_path = Path(tmpdir) / "output.pcm"
        input_path.write_bytes(raw)
        command = [
            ffmpeg,
            "-hide_banner",
            "-loglevel",
            "error",
            "-i",
            str(input_path),
            "-ac",
            "1",
            "-ar",
            "16000",
            "-f",
            "s16le",
            str(output_path),
        ]
        completed = subprocess.run(command, check=False, capture_output=True, text=True)
        if completed.returncode != 0 or not output_path.exists():
            raise_api_error(status.HTTP_400_BAD_REQUEST, "audio_transcode_failed", "音频转码失败")
        return _validate_pcm(output_path.read_bytes())


async def prepare_upload_for_asr(upload: UploadFile) -> PreparedAudio:
    raw = await upload.read()
    if not raw:
        raise_api_error(status.HTTP_400_BAD_REQUEST, "audio_empty", "音频为空")

    filename = (upload.filename or "").lower()
    content_type = (upload.content_type or "").lower().split(";")[0].strip()
    is_mp3 = filename.endswith(".mp3") or content_type in MP3_CONTENT_TYPES
    if is_mp3:
        pcm = _decode_to_pcm(raw, filename)
        return PreparedAudio(
            pcm=pcm,
            upstream_data=raw,
            source_format="mp3",
            source_bytes=len(raw),
        )

    if filename.endswith((".pcm", ".raw")) or content_type in PCM_CONTENT_TYPES:
        pcm = _validate_pcm(raw)
        return PreparedAudio(
            pcm=pcm,
            upstream_data=None,
            source_format="pcm",
            source_bytes=len(raw),
        )

    pcm = _decode_to_pcm(raw, filename)
    return PreparedAudio(
        pcm=pcm,
        # Volc's flash endpoint accepts MP3 directly. Other compressed formats
        # retain the established PCM -> WAV compatibility path.
        upstream_data=None,
        source_format="transcoded",
        source_bytes=len(raw),
    )


async def read_upload_as_pcm(upload: UploadFile) -> bytes:
    """Compatibility helper for callers that only need normalized PCM."""
    return (await prepare_upload_for_asr(upload)).pcm
