import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import convert


@pytest.fixture(autouse=True)
def override_dirs(tmp_path, monkeypatch):
    monkeypatch.setattr(convert, "DEFAULT_OUTPUT_DIR", tmp_path)


# --- source_id ---


class TestSourceId:
    def test_deterministic(self):
        assert convert.source_id("https://example.com") == convert.source_id("https://example.com")

    def test_different_for_different_sources(self):
        assert convert.source_id("https://a.com") != convert.source_id("https://b.com")

    def test_length(self):
        assert len(convert.source_id("test")) == 12


# --- is_url ---


class TestIsUrl:
    def test_http(self):
        assert convert.is_url("https://example.com/doc.pdf") is True

    def test_http_no_s(self):
        assert convert.is_url("http://example.com") is True

    def test_file_path(self):
        assert convert.is_url("/tmp/test.pdf") is False

    def test_relative_path(self):
        assert convert.is_url("slides.pptx") is False


# --- title_from_url ---


class TestTitleFromUrl:
    def test_with_path(self):
        assert convert.title_from_url("https://example.com/paper.pdf") == "paper.pdf"

    def test_with_nested_path(self):
        assert convert.title_from_url("https://slideshare.net/user/my-slides") == "my-slides"

    def test_root_only(self):
        assert convert.title_from_url("https://example.com/") == "example.com"

    def test_no_path(self):
        assert convert.title_from_url("https://example.com") == "example.com"


# --- convert ---


class TestConvert:
    def _mock_markitdown(self, monkeypatch, text="これはテスト用のMarkdown変換結果です。十分な長さのテキストが必要です。"):
        mock_md = MagicMock()
        mock_result = MagicMock()
        mock_result.text_content = text
        mock_md.convert.return_value = mock_result
        monkeypatch.setattr(convert, "MarkItDown", lambda: mock_md)
        return mock_md

    def test_url_success(self, monkeypatch, tmp_path):
        self._mock_markitdown(monkeypatch)
        result = convert.convert("https://example.com/doc.pdf", tmp_path)
        assert result is not None and result is not False
        content = result.read_text()
        assert "url: https://example.com/doc.pdf" in content
        assert "source: markitdown-url" in content

    def test_file_success(self, monkeypatch, tmp_path):
        self._mock_markitdown(monkeypatch)
        test_file = tmp_path / "test.pdf"
        test_file.write_text("dummy")
        result = convert.convert(str(test_file), tmp_path)
        assert result is not None and result is not False
        content = result.read_text()
        assert "title: test.pdf" in content
        assert "source: markitdown-file" in content

    def test_skip_processed(self, monkeypatch, tmp_path):
        self._mock_markitdown(monkeypatch)
        source = "https://example.com/doc.pdf"
        fid = convert.source_id(source)
        transcript_dir = tmp_path / ".transcripts"
        transcript_dir.mkdir()
        (transcript_dir / "done").mkdir()
        (transcript_dir / f"{fid}.txt").write_text("already done")
        assert convert.convert(source, tmp_path) is None

    def test_skip_done(self, monkeypatch, tmp_path):
        self._mock_markitdown(monkeypatch)
        source = "https://example.com/doc.pdf"
        fid = convert.source_id(source)
        transcript_dir = tmp_path / ".transcripts"
        transcript_dir.mkdir()
        done_dir = transcript_dir / "done"
        done_dir.mkdir()
        (done_dir / f"{fid}.txt").write_text("already done")
        assert convert.convert(source, tmp_path) is None

    def test_empty_content(self, monkeypatch, tmp_path):
        self._mock_markitdown(monkeypatch, text="")
        assert convert.convert("https://example.com/empty.pdf", tmp_path) is False

    def test_short_content(self, monkeypatch, tmp_path):
        self._mock_markitdown(monkeypatch, text="短い")
        assert convert.convert("https://example.com/short.pdf", tmp_path) is False

    def test_none_content(self, monkeypatch, tmp_path):
        self._mock_markitdown(monkeypatch, text=None)
        assert convert.convert("https://example.com/null.pdf", tmp_path) is False

    def test_markitdown_exception(self, monkeypatch, tmp_path):
        mock_md = MagicMock()
        mock_md.convert.side_effect = RuntimeError("parse error")
        monkeypatch.setattr(convert, "MarkItDown", lambda: mock_md)
        assert convert.convert("https://example.com/bad.pdf", tmp_path) is False


# --- collect_inputs ---


class TestCollectInputs:
    def test_url(self):
        inputs = convert.collect_inputs(["https://example.com/doc.pdf"])
        assert inputs == ["https://example.com/doc.pdf"]

    def test_file(self, tmp_path):
        f = tmp_path / "test.pdf"
        f.write_text("dummy")
        inputs = convert.collect_inputs([str(f)])
        assert str(f) in inputs[0]

    def test_directory(self, tmp_path):
        (tmp_path / "a.pdf").write_text("dummy")
        (tmp_path / "b.pptx").write_text("dummy")
        (tmp_path / "c.txt").write_text("dummy")
        inputs = convert.collect_inputs([str(tmp_path)])
        assert len(inputs) == 2

    def test_missing_file(self):
        inputs = convert.collect_inputs(["/nonexistent/file.pdf"])
        assert inputs == []

    def test_mixed(self, tmp_path):
        f = tmp_path / "local.pdf"
        f.write_text("dummy")
        inputs = convert.collect_inputs(["https://example.com", str(f)])
        assert len(inputs) == 2


# --- main ---


class TestMain:
    def test_no_args_exits(self, monkeypatch):
        monkeypatch.setattr(sys, "argv", ["convert.py"])
        with pytest.raises(SystemExit) as exc_info:
            convert.main()
        assert exc_info.value.code == 2

    def test_no_valid_inputs_exits(self, monkeypatch):
        monkeypatch.setattr(sys, "argv", ["convert.py", "/nonexistent/file.pdf"])
        with pytest.raises(SystemExit) as exc_info:
            convert.main()
        assert exc_info.value.code == 1

    def test_success(self, monkeypatch, tmp_path):
        mock_md = MagicMock()
        mock_result = MagicMock()
        mock_result.text_content = "変換されたMarkdownテキストです。十分な長さが必要なのでもう少し書きます。"
        mock_md.convert.return_value = mock_result
        monkeypatch.setattr(convert, "MarkItDown", lambda: mock_md)
        monkeypatch.setattr(sys, "argv", ["convert.py", "-o", str(tmp_path), "https://example.com/doc.pdf"])
        convert.main()
        transcript_dir = tmp_path / ".transcripts"
        assert len(list(transcript_dir.glob("*.txt"))) == 1
