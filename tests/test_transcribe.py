import json
import subprocess
import sys
import types
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import transcribe


@pytest.fixture(autouse=True)
def override_dirs(tmp_path, monkeypatch):
    transcript_dir = tmp_path / "_transcripts"
    transcript_dir.mkdir()
    audio_dir = tmp_path / "audio"
    audio_dir.mkdir()

    monkeypatch.setattr(transcribe, "OBSIDIAN_RECIPE_DIR", tmp_path)
    monkeypatch.setattr(transcribe, "TRANSCRIPT_DIR", transcript_dir)
    monkeypatch.setattr(transcribe, "AUDIO_TMP_DIR", audio_dir)


# --- get_videos ---


def _make_run_result(stdout, returncode=0, stderr=""):
    return subprocess.CompletedProcess([], returncode, stdout=stdout, stderr=stderr)


class TestGetVideos:
    def test_single_video(self, monkeypatch):
        data = {"id": "abc123", "title": "テスト動画"}
        monkeypatch.setattr(
            subprocess, "run",
            lambda *a, **kw: _make_run_result(json.dumps(data)),
        )
        videos = transcribe.get_videos("https://www.youtube.com/watch?v=abc123")
        assert len(videos) == 1
        assert videos[0]["id"] == "abc123"
        assert videos[0]["url"] == "https://www.youtube.com/watch?v=abc123"

    def test_playlist(self, monkeypatch):
        data = {
            "entries": [
                {"id": "v1", "title": "動画1"},
                {"id": "v2", "title": "動画2"},
            ]
        }
        monkeypatch.setattr(
            subprocess, "run",
            lambda *a, **kw: _make_run_result(json.dumps(data)),
        )
        videos = transcribe.get_videos("https://www.youtube.com/playlist?list=PL123")
        assert len(videos) == 2
        assert videos[1]["url"] == "https://www.youtube.com/watch?v=v2"

    def test_yt_dlp_failure(self, monkeypatch):
        monkeypatch.setattr(
            subprocess, "run",
            lambda *a, **kw: _make_run_result("", returncode=1, stderr="not found"),
        )
        with pytest.raises(SystemExit):
            transcribe.get_videos("https://invalid")


# --- is_processed ---


class TestIsProcessed:
    def test_not_processed(self):
        assert transcribe.is_processed("new_video") is False

    def test_transcript_exists(self):
        (transcribe.TRANSCRIPT_DIR / "vid1.txt").write_text("test")
        assert transcribe.is_processed("vid1") is True



# --- download_audio ---


class TestDownloadAudio:
    def test_cached(self):
        video = {"id": "cached1", "url": "https://example.com"}
        cached_path = transcribe.AUDIO_TMP_DIR / "cached1.mp3"
        cached_path.write_text("fake audio")
        result = transcribe.download_audio(video)
        assert result == cached_path

    def test_success(self, monkeypatch):
        video = {"id": "dl1", "url": "https://example.com"}
        expected_path = transcribe.AUDIO_TMP_DIR / "dl1.mp3"

        def fake_run(cmd, **kw):
            expected_path.write_text("audio data")
            return _make_run_result("")

        monkeypatch.setattr(subprocess, "run", fake_run)
        result = transcribe.download_audio(video)
        assert result == expected_path

    def test_failure(self, monkeypatch):
        video = {"id": "fail1", "url": "https://example.com"}
        monkeypatch.setattr(
            subprocess, "run",
            lambda *a, **kw: _make_run_result("", returncode=1, stderr="error"),
        )
        assert transcribe.download_audio(video) is None


# --- transcribe_audio ---


class TestTranscribeAudio:
    def _mock_mlx_whisper(self, monkeypatch, text="こんにちは"):
        mock_module = types.ModuleType("mlx_whisper")
        mock_module.transcribe = MagicMock(return_value={"text": text})
        monkeypatch.setitem(sys.modules, "mlx_whisper", mock_module)
        return mock_module

    def test_success(self, monkeypatch):
        self._mock_mlx_whisper(monkeypatch, text="材料：卵2個")
        audio_path = transcribe.AUDIO_TMP_DIR / "t1.mp3"
        audio_path.write_text("fake")
        video = {"id": "t1", "title": "卵焼き", "url": "https://example.com/t1"}

        result = transcribe.transcribe_audio(audio_path, video)

        assert result is not None
        assert result.exists()
        content = result.read_text()
        assert "title: 卵焼き" in content
        assert "video_id: t1" in content
        assert "材料：卵2個" in content

    def test_atomic_write_no_partial_on_failure(self, monkeypatch):
        self._mock_mlx_whisper(monkeypatch)
        audio_path = transcribe.AUDIO_TMP_DIR / "t2.mp3"
        audio_path.write_text("fake")
        video = {"id": "t2", "title": "test", "url": "https://example.com"}

        with patch("builtins.open", side_effect=OSError("disk full")):
            with pytest.raises(OSError):
                transcribe.transcribe_audio(audio_path, video)

        transcript = transcribe.TRANSCRIPT_DIR / "t2.txt"
        assert not transcript.exists()
        tmp_files = list(transcribe.TRANSCRIPT_DIR.glob("*.tmp"))
        assert len(tmp_files) == 0

    def test_whisper_error_returns_none(self, monkeypatch):
        mock_module = types.ModuleType("mlx_whisper")
        mock_module.transcribe = MagicMock(side_effect=RuntimeError("GPU error"))
        monkeypatch.setitem(sys.modules, "mlx_whisper", mock_module)

        audio_path = transcribe.AUDIO_TMP_DIR / "t3.mp3"
        audio_path.write_text("fake")
        video = {"id": "t3", "title": "test", "url": "https://example.com"}

        assert transcribe.transcribe_audio(audio_path, video) is None


# --- check_mlx_whisper ---


class TestCheckMlxWhisper:
    def test_available(self, monkeypatch):
        monkeypatch.setitem(sys.modules, "mlx_whisper", types.ModuleType("mlx_whisper"))
        assert transcribe.check_mlx_whisper() is True

    def test_missing(self, monkeypatch):
        monkeypatch.delitem(sys.modules, "mlx_whisper", raising=False)
        with patch.dict(sys.modules, {"mlx_whisper": None}):
            # importing a module mapped to None in sys.modules raises ImportError
            assert transcribe.check_mlx_whisper() is False


# --- main ---


class TestMain:
    def _setup_mocks(self, monkeypatch, videos, transcribe_results=None):
        monkeypatch.setattr(transcribe, "check_mlx_whisper", lambda: True)
        monkeypatch.setattr(transcribe, "get_videos", lambda url: videos)
        if transcribe_results is None:
            transcribe_results = [True] * len(videos)

        download_calls = iter(videos)
        def fake_download(video):
            path = transcribe.AUDIO_TMP_DIR / f"{video['id']}.mp3"
            path.write_text("fake")
            return path
        monkeypatch.setattr(transcribe, "download_audio", fake_download)

        results_iter = iter(transcribe_results)
        def fake_transcribe(audio_path, video):
            if next(results_iter):
                path = transcribe.TRANSCRIPT_DIR / f"{video['id']}.txt"
                path.write_text("content")
                return path
            return None
        monkeypatch.setattr(transcribe, "transcribe_audio", fake_transcribe)

    def test_all_success(self, monkeypatch):
        videos = [{"id": "v1", "title": "t1", "url": "u1"}]
        self._setup_mocks(monkeypatch, videos)
        monkeypatch.setattr(sys, "argv", ["transcribe.py", "https://example.com"])
        # main() should return normally on full success
        transcribe.main()

    def test_partial_failure_exits_1(self, monkeypatch):
        videos = [
            {"id": "v1", "title": "t1", "url": "u1"},
            {"id": "v2", "title": "t2", "url": "u2"},
        ]
        self._setup_mocks(monkeypatch, videos, transcribe_results=[True, False])
        monkeypatch.setattr(sys, "argv", ["transcribe.py", "https://example.com"])
        with pytest.raises(SystemExit) as exc_info:
            transcribe.main()
        assert exc_info.value.code == 1

    def test_skips_processed(self, monkeypatch):
        videos = [{"id": "already", "title": "t", "url": "u"}]
        (transcribe.TRANSCRIPT_DIR / "already.txt").write_text("done")
        self._setup_mocks(monkeypatch, videos)
        monkeypatch.setattr(sys, "argv", ["transcribe.py", "https://example.com"])
        transcribe.main()

    def test_no_args_exits(self, monkeypatch):
        monkeypatch.setattr(sys, "argv", ["transcribe.py"])
        with pytest.raises(SystemExit) as exc_info:
            transcribe.main()
        assert exc_info.value.code == 1

    def test_missing_mlx_whisper_exits(self, monkeypatch):
        monkeypatch.setattr(transcribe, "check_mlx_whisper", lambda: False)
        monkeypatch.setattr(sys, "argv", ["transcribe.py", "https://example.com"])
        with pytest.raises(SystemExit) as exc_info:
            transcribe.main()
        assert exc_info.value.code == 1
