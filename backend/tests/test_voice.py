from __future__ import annotations

import asyncio
import base64
import json
import os
import struct
import subprocess
import sys
import tempfile
import unittest
import wave
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import imageio_ffmpeg

ROOT = os.path.dirname(os.path.dirname(__file__))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from fastapi import HTTPException  # noqa: E402
from starlette.responses import Response  # noqa: E402

from app.config import get_settings  # noqa: E402
from app.routers.voice import create_todos_from_transcript  # noqa: E402
from app.schemas import AiCreateRequest  # noqa: E402
from app.services.asr import VolcAsrError, pcm_to_wav, recognize_pcm  # noqa: E402
from app.services.audio import PCM_BYTES_PER_SECOND, read_upload_as_pcm  # noqa: E402
from app.services.deepseek import NoTodoParsedError  # noqa: E402


def _pcm_silence(seconds: float) -> bytes:
    return b"\0" * int(PCM_BYTES_PER_SECOND * seconds)


class FakeUpload:
    def __init__(self, raw: bytes, filename: str, content_type: str) -> None:
        self.raw = raw
        self.filename = filename
        self.content_type = content_type

    async def read(self) -> bytes:
        return self.raw


def _make_mp3(seconds: float) -> bytes:
    """用 imageio-ffmpeg 内置 ffmpeg 从 WAV 静音生成测试 mp3。"""
    with tempfile.TemporaryDirectory() as tmpdir:
        wav_path = os.path.join(tmpdir, "in.wav")
        mp3_path = os.path.join(tmpdir, "out.mp3")
        with wave.open(wav_path, "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(16000)
            w.writeframes(_pcm_silence(seconds))
        subprocess.run(
            [
                imageio_ffmpeg.get_ffmpeg_exe(),
                "-y",
                "-hide_banner",
                "-loglevel",
                "error",
                "-i",
                wav_path,
                mp3_path,
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        with open(mp3_path, "rb") as f:
            return f.read()


# ---------------------------------------------------------------------------
# ASR service tests
# ---------------------------------------------------------------------------


class VolcAsrServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.env = patch.dict(
            os.environ,
            {"VOLC_API_KEY": "test-api-key"},
            clear=False,
        )
        self.env.start()
        get_settings.cache_clear()

    def tearDown(self) -> None:
        self.env.stop()
        get_settings.cache_clear()

    def test_pcm_to_wav_produces_valid_wav_header(self) -> None:
        pcm = b"\1" * 3200  # 100ms @ 16kHz/16bit/mono
        wav = pcm_to_wav(pcm)

        # RIFF header
        self.assertEqual(wav[0:4], b"RIFF")
        # File size = data_size + 36
        expected_size = len(pcm) + 36
        self.assertEqual(struct.unpack_from("<I", wav, 4)[0], expected_size)
        # WAVE fmt
        self.assertEqual(wav[8:16], b"WAVEfmt ")
        # Subchunk1Size = 16
        self.assertEqual(struct.unpack_from("<I", wav, 16)[0], 16)
        # AudioFormat = 1 (PCM)
        self.assertEqual(struct.unpack_from("<H", wav, 20)[0], 1)
        # NumChannels = 1
        self.assertEqual(struct.unpack_from("<H", wav, 22)[0], 1)
        # SampleRate = 16000
        self.assertEqual(struct.unpack_from("<I", wav, 24)[0], 16000)
        # BitsPerSample = 16
        self.assertEqual(struct.unpack_from("<H", wav, 34)[0], 16)
        # data chunk
        self.assertEqual(wav[36:40], b"data")
        self.assertEqual(struct.unpack_from("<I", wav, 40)[0], len(pcm))
        # PCM payload follows header
        self.assertEqual(wav[44:], pcm)

    def test_recognize_pcm_returns_text_on_success(self) -> None:
        async def run():
            mock_response = SimpleNamespace(
                headers={
                    "X-Api-Status-Code": "20000000",
                    "X-Tt-Logid": "test-logid",
                },
                text='{"result": {"text": "今天去买菜"}}',
            )
            mock_response.json = lambda: json.loads(mock_response.text)

            with patch(
                "app.services.asr._get_client",
                return_value=SimpleNamespace(
                    post=AsyncMock(return_value=mock_response)
                ),
            ):
                result = await recognize_pcm(_pcm_silence(1))
                return result

        text = asyncio.run(run())
        self.assertEqual(text, "今天去买菜")

    def test_recognize_pcm_raises_on_silence_audio(self) -> None:
        async def run():
            mock_response = SimpleNamespace(
                headers={
                    "X-Api-Status-Code": "20000003",
                    "X-Tt-Logid": "test-logid",
                },
                text="",
            )

            with patch(
                "app.services.asr._get_client",
                return_value=SimpleNamespace(
                    post=AsyncMock(return_value=mock_response)
                ),
            ):
                with self.assertRaises(VolcAsrError) as raised:
                    await recognize_pcm(_pcm_silence(1))

            self.assertIn("静音", str(raised.exception))

        asyncio.run(run())

    def test_recognize_pcm_raises_on_http_error(self) -> None:
        async def run():
            import httpx

            with patch(
                "app.services.asr._get_client",
                return_value=SimpleNamespace(
                    post=AsyncMock(side_effect=httpx.ConnectError("connection refused"))
                ),
            ):
                with self.assertRaises(VolcAsrError) as raised:
                    await recognize_pcm(_pcm_silence(1))

            self.assertIn("请求失败", str(raised.exception))

        asyncio.run(run())


# ---------------------------------------------------------------------------
# Audio upload tests
# ---------------------------------------------------------------------------


class AudioUploadTests(unittest.TestCase):
    def setUp(self) -> None:
        self.env = patch.dict(
            os.environ,
            {"MIN_AUDIO_SECONDS": "0.5", "MAX_AUDIO_SECONDS": "30"},
            clear=False,
        )
        self.env.start()
        get_settings.cache_clear()

    def tearDown(self) -> None:
        self.env.stop()
        get_settings.cache_clear()

    def test_pcm_upload_is_accepted_without_transcoding(self) -> None:
        raw = b"\0" * PCM_BYTES_PER_SECOND
        upload = FakeUpload(raw, "recording.pcm", "audio/pcm")

        result = asyncio.run(read_upload_as_pcm(upload))
        self.assertEqual(result, raw)

    def test_too_short_pcm_is_rejected(self) -> None:
        raw = b"\0" * (PCM_BYTES_PER_SECOND // 10)
        upload = FakeUpload(raw, "recording.pcm", "audio/pcm")

        with self.assertRaises(HTTPException) as raised:
            asyncio.run(read_upload_as_pcm(upload))

        self.assertEqual(raised.exception.status_code, 400)
        self.assertEqual(raised.exception.detail["code"], "recording_too_short")
        self.assertEqual(raised.exception.detail["message"], "录音太短")

    def test_too_long_pcm_is_rejected(self) -> None:
        raw = b"\0" * (PCM_BYTES_PER_SECOND * 31)
        upload = FakeUpload(raw, "recording.pcm", "audio/pcm")

        with self.assertRaises(HTTPException) as raised:
            asyncio.run(read_upload_as_pcm(upload))

        self.assertEqual(raised.exception.status_code, 400)
        self.assertEqual(raised.exception.detail["code"], "recording_too_long")
        max_seconds = get_settings().max_audio_seconds
        self.assertEqual(raised.exception.detail["message"], f"录音超过 {max_seconds:.0f} 秒")

    def test_mp3_upload_is_transcoded_to_pcm(self) -> None:
        upload = FakeUpload(_make_mp3(2.0), "recording.mp3", "audio/mpeg")

        result = asyncio.run(read_upload_as_pcm(upload))
        duration = len(result) / PCM_BYTES_PER_SECOND
        self.assertAlmostEqual(duration, 2.0, delta=0.2)


# ---------------------------------------------------------------------------
# AI todo route tests
# ---------------------------------------------------------------------------


class AiCreateRequestSchemaTests(unittest.TestCase):
    def test_source_defaults_to_voice(self) -> None:
        req = AiCreateRequest(transcript="明天买菜")
        self.assertEqual(req.source, "voice")

    def test_source_accepts_text(self) -> None:
        req = AiCreateRequest(transcript="明天买菜", source="text")
        self.assertEqual(req.source, "text")

    def test_source_rejects_unknown_value(self) -> None:
        from pydantic import ValidationError

        with self.assertRaises(ValidationError):
            AiCreateRequest(transcript="明天买菜", source="keyboard")


class AiTodoRouteTests(unittest.TestCase):
    def test_no_todo_parse_result_returns_empty_success_response(self) -> None:
        async def no_todo(_transcript):
            raise NoTodoParsedError("没有识别到需要新增的待办")

        async def run_route():
            response = Response()
            with patch("app.routers.voice.parse_todos_with_deepseek", no_todo):
                result = await create_todos_from_transcript(
                    AiCreateRequest(transcript="今天天气不错"),
                    response=response,
                    db=SimpleNamespace(),
                    user={"id": 1},
                )
            return response, result

        response, result = asyncio.run(run_route())

        self.assertEqual(response.status_code, 200)
        self.assertEqual(result.items, [])
        self.assertEqual(result.message, "没有识别到需要新增的待办")


if __name__ == "__main__":
    unittest.main()
