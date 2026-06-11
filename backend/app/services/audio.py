from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path

from fastapi import HTTPException, UploadFile, status

from app.config import get_settings


PCM_BYTES_PER_SECOND = 16_000 * 2
PCM_CONTENT_TYPES = {
    "application/octet-stream",
    "audio/pcm",
    "audio/l16",
    "audio/x-raw",
}


def _duration_seconds(pcm: bytes) -> float:
    return len(pcm) / PCM_BYTES_PER_SECOND


def _validate_pcm(pcm: bytes) -> bytes:
    settings = get_settings()
    duration = _duration_seconds(pcm)
    if duration < settings.min_audio_seconds:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="录音太短")
    if duration > settings.max_audio_seconds:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="录音超过 30 秒")
    return pcm


async def read_upload_as_pcm(upload: UploadFile) -> bytes:
    raw = await upload.read()
    if not raw:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="音频为空")

    filename = (upload.filename or "").lower()
    content_type = (upload.content_type or "").lower().split(";")[0].strip()
    if filename.endswith((".pcm", ".raw")) or content_type in PCM_CONTENT_TYPES:
        return _validate_pcm(raw)

    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg is None:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail="仅支持 16k/16bit/mono PCM；如需上传其他格式，请在后端安装 ffmpeg",
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
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="音频转码失败",
            )
        return _validate_pcm(output_path.read_bytes())
