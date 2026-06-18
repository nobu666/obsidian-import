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
    done_dir = transcript_dir / "done"
    done_dir.mkdir()
    audio_dir = tmp_path / "audio"
    audio_dir.mkdir()

    monkeypatch.setattr(transcribe, "DEFAULT_OUTPUT_DIR", tmp_path)
    monkeypatch.setattr(transcribe, "OBSIDIAN_OUTPUT_DIR", tmp_path)
    monkeypatch.setattr(transcribe, "TRANSCRIPT_DIR", transcript_dir)
    monkeypatch.setattr(transcribe, "DONE_DIR", done_dir)
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

    def test_done_exists(self):
        (transcribe.DONE_DIR / "vid2.txt").write_text("test")
        assert transcribe.is_processed("vid2") is True



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


# --- is_hallucinated ---


class TestIsHallucinated:
    def test_normal_text(self):
        text = "今日は鶏肉を使った料理を紹介します。材料は鶏もも肉二枚と塩コショウです。まず鶏肉を一口大に切って、塩コショウで下味をつけます。フライパンに油を熱して中火で焼いていきます。"
        assert transcribe.is_hallucinated(text) is False

    def test_repeated_phrase(self):
        assert transcribe.is_hallucinated("なんなん" * 50) is True

    def test_repeated_dots(self):
        assert transcribe.is_hallucinated("222" * 100) is True

    def test_too_short(self):
        assert transcribe.is_hallucinated("短い") is True

    def test_mostly_punctuation(self):
        text = "。、…・！？" * 30 + "あ"
        assert transcribe.is_hallucinated(text) is True


# --- transcribe_audio ---


class TestGetSubtitles:
    def test_found(self, monkeypatch, tmp_path):
        video = {"id": "sub1", "url": "https://example.com"}
        srt_content = "1\n00:00:01,000 --> 00:00:03,000\nこんにちは\n\n2\n00:00:03,000 --> 00:00:05,000\n今日は料理します\n"

        def fake_run(cmd, **kw):
            Path(f"/tmp/yt_subs_{video['id']}.ja.srt").write_text(srt_content)
            return _make_run_result("")

        monkeypatch.setattr(subprocess, "run", fake_run)
        text, lang = transcribe.get_subtitles(video)
        assert "こんにちは" in text
        assert "今日は料理します" in text
        assert lang is None

    def test_found_english(self, monkeypatch, tmp_path):
        video = {"id": "sub_en", "url": "https://example.com"}
        srt_content = "1\n00:00:01,000 --> 00:00:03,000\nHello\n\n2\n00:00:03,000 --> 00:00:05,000\nToday we cook\n"

        def fake_run(cmd, **kw):
            if "en" in cmd:
                Path(f"/tmp/yt_subs_{video['id']}.en.srt").write_text(srt_content)
            return _make_run_result("")

        monkeypatch.setattr(subprocess, "run", fake_run)
        text, lang = transcribe.get_subtitles(video)
        assert "Hello" in text
        assert lang == "en"

    def test_not_found(self, monkeypatch):
        video = {"id": "nosub1", "url": "https://example.com"}
        monkeypatch.setattr(
            subprocess, "run",
            lambda *a, **kw: _make_run_result(""),
        )
        text, lang = transcribe.get_subtitles(video)
        assert text is None
        assert lang is None


class TestGetDescription:
    def test_found(self, monkeypatch):
        video = {"id": "desc1", "url": "https://example.com"}
        desc = "材料：もずく280g、お酢大さじ2、黒糖粉大さじ1、醤油大さじ1、塩小さじ1/3、かつお出汁大さじ4"
        monkeypatch.setattr(
            subprocess, "run",
            lambda *a, **kw: _make_run_result(desc),
        )
        assert transcribe.get_description(video) == desc

    def test_too_short(self, monkeypatch):
        video = {"id": "desc2", "url": "https://example.com"}
        monkeypatch.setattr(
            subprocess, "run",
            lambda *a, **kw: _make_run_result("短い"),
        )
        assert transcribe.get_description(video) is None


class TestSaveTranscript:
    def test_save_whisper(self):
        video = {"id": "sv1", "title": "テスト", "url": "https://example.com"}
        result = transcribe.save_transcript(video, "テキスト内容")
        assert result.exists()
        content = result.read_text()
        assert "title: テスト" in content
        assert "source:" not in content
        assert "テキスト内容" in content

    def test_save_with_source(self):
        video = {"id": "sv2", "title": "テスト", "url": "https://example.com"}
        result = transcribe.save_transcript(video, "説明欄", source="youtube-description")
        content = result.read_text()
        assert "source: youtube-description" in content


class TestTranscribeVideo:
    def _mock_mlx_whisper(self, monkeypatch, text="今日は鶏肉を使った料理を紹介します。材料は鶏もも肉二枚と塩コショウです。まず鶏肉を一口大に切ってフライパンで焼いていきます。"):
        mock_module = types.ModuleType("mlx_whisper")
        mock_module.transcribe = MagicMock(return_value={"text": text})
        monkeypatch.setitem(sys.modules, "mlx_whisper", mock_module)
        return mock_module

    def _mock_download(self, monkeypatch):
        def fake_download(video):
            path = transcribe.AUDIO_TMP_DIR / f"{video['id']}.mp3"
            path.write_text("fake")
            return path
        monkeypatch.setattr(transcribe, "download_audio", fake_download)

    def test_subtitles_preferred(self, monkeypatch):
        """字幕があればWhisperを使わず字幕を使う"""
        video = {"id": "t_sub", "title": "テスト", "url": "https://example.com"}
        sub_text = "字幕からの内容です。今日はもずく酢を作ります。材料はもずく280グラムとお酢大さじ2です。"
        monkeypatch.setattr(transcribe, "get_subtitles", lambda v: (sub_text, None))

        result = transcribe.transcribe_video(video)
        assert result is not None
        content = result.read_text()
        assert "source: youtube-subtitles" in content
        assert "字幕からの内容" in content

    def test_whisper_fallback_on_no_subtitles(self, monkeypatch):
        """字幕がない場合はWhisperにフォールバック"""
        self._mock_mlx_whisper(monkeypatch, text="材料は卵2個と砂糖大さじ1と醤油小さじ1です。まず卵をボウルに割り入れてよく溶きほぐします。フライパンに油を熱して中火で焼いていきます。表面が固まったら巻いていきましょう。")
        self._mock_download(monkeypatch)
        monkeypatch.setattr(transcribe, "get_subtitles", lambda v: (None, None))
        video = {"id": "t1", "title": "卵焼き", "url": "https://example.com/t1"}

        result = transcribe.transcribe_video(video)
        assert result is not None
        content = result.read_text()
        assert "title: 卵焼き" in content
        assert "材料は卵2個" in content

    def test_hallucination_fallback_to_description(self, monkeypatch):
        """Whisperがハルシネーションした場合は説明欄にフォールバック"""
        self._mock_mlx_whisper(monkeypatch, text="なんなん" * 50)
        self._mock_download(monkeypatch)
        monkeypatch.setattr(transcribe, "get_subtitles", lambda v: (None, None))
        desc = "説明欄の内容です。材料：もずく280g、お酢大さじ2、黒糖粉大さじ1、醤油大さじ1"
        monkeypatch.setattr(transcribe, "get_description", lambda v: desc)
        video = {"id": "t_desc", "title": "test", "url": "https://example.com"}

        result = transcribe.transcribe_video(video)
        assert result is not None
        assert "source: youtube-description" in result.read_text()

    def test_all_fallbacks_fail(self, monkeypatch):
        """字幕なし・Whisperハルシネーション・説明欄なし → None"""
        self._mock_mlx_whisper(monkeypatch, text="なんなん" * 50)
        self._mock_download(monkeypatch)
        monkeypatch.setattr(transcribe, "get_subtitles", lambda v: (None, None))
        monkeypatch.setattr(transcribe, "get_description", lambda v: None)
        video = {"id": "t_fail", "title": "test", "url": "https://example.com"}

        assert transcribe.transcribe_video(video) is None

    def test_whisper_error_fallback(self, monkeypatch):
        """Whisperエラー時は説明欄にフォールバック"""
        mock_module = types.ModuleType("mlx_whisper")
        mock_module.transcribe = MagicMock(side_effect=RuntimeError("GPU error"))
        monkeypatch.setitem(sys.modules, "mlx_whisper", mock_module)
        self._mock_download(monkeypatch)
        monkeypatch.setattr(transcribe, "get_subtitles", lambda v: (None, None))
        desc = "説明欄フォールバック。材料：もずく280g、お酢大さじ2、黒糖粉大さじ1、醤油大さじ1"
        monkeypatch.setattr(transcribe, "get_description", lambda v: desc)
        video = {"id": "t3", "title": "test", "url": "https://example.com"}

        result = transcribe.transcribe_video(video)
        assert result is not None
        assert "source: youtube-description" in result.read_text()


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

        results_iter = iter(transcribe_results)
        def fake_transcribe(video):
            if next(results_iter):
                path = transcribe.TRANSCRIPT_DIR / f"{video['id']}.txt"
                path.write_text("content")
                return path
            return None
        monkeypatch.setattr(transcribe, "transcribe_video", fake_transcribe)

    def test_all_success(self, monkeypatch):
        videos = [{"id": "v1", "title": "t1", "url": "u1"}]
        self._setup_mocks(monkeypatch, videos)
        monkeypatch.setattr(sys, "argv", ["transcribe.py", "https://www.youtube.com/watch?v=test"])
        # main() should return normally on full success
        transcribe.main()

    def test_partial_failure_exits_1(self, monkeypatch):
        videos = [
            {"id": "v1", "title": "t1", "url": "u1"},
            {"id": "v2", "title": "t2", "url": "u2"},
        ]
        self._setup_mocks(monkeypatch, videos, transcribe_results=[True, False])
        monkeypatch.setattr(sys, "argv", ["transcribe.py", "https://www.youtube.com/watch?v=test"])
        with pytest.raises(SystemExit) as exc_info:
            transcribe.main()
        assert exc_info.value.code == 1

    def test_skips_processed(self, monkeypatch):
        videos = [{"id": "already", "title": "t", "url": "u"}]
        (transcribe.TRANSCRIPT_DIR / "already.txt").write_text("done")
        self._setup_mocks(monkeypatch, videos)
        monkeypatch.setattr(sys, "argv", ["transcribe.py", "https://www.youtube.com/watch?v=test"])
        transcribe.main()

    def test_no_args_exits(self, monkeypatch):
        monkeypatch.setattr(sys, "argv", ["transcribe.py"])
        with pytest.raises(SystemExit) as exc_info:
            transcribe.main()
        assert exc_info.value.code == 2

    def test_missing_mlx_whisper_exits(self, monkeypatch):
        monkeypatch.setattr(transcribe, "check_mlx_whisper", lambda: False)
        monkeypatch.setattr(sys, "argv", ["transcribe.py", "https://www.youtube.com/watch?v=test"])
        with pytest.raises(SystemExit) as exc_info:
            transcribe.main()
        assert exc_info.value.code == 1
