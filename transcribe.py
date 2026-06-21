#!/usr/bin/env python3
"""
YouTube動画の音声をダウンロードし、Whisperで文字起こしする。
Web記事のテキスト抽出にも対応。
結果はObsidian Vault内の .transcripts/ に保存される。
構造化ノートへの変換は obsidian-import スクリプト経由で Claude CLI が担当する。
"""

import argparse
import hashlib
import os
import re
import subprocess
import json
import sys
import tempfile
import warnings
from pathlib import Path
from urllib.parse import urlparse

os.environ["MALLOC_STACK_LOGGING"] = ""
warnings.filterwarnings("ignore", message=".*unauthenticated.*HF Hub.*")

# === 設定 ===
DEFAULT_OUTPUT_DIR = Path.home() / "Documents/Obsidian/Vault/YouTube"
OBSIDIAN_OUTPUT_DIR = DEFAULT_OUTPUT_DIR
TRANSCRIPT_DIR = OBSIDIAN_OUTPUT_DIR / ".transcripts"
AUDIO_TMP_DIR = Path("/tmp/yt_obsidian_audio")
WHISPER_MODEL = "mlx-community/whisper-large-v3-turbo"
DONE_DIR = TRANSCRIPT_DIR / "done"

# Whisperで文字起こしするローカル音声/動画の拡張子
AUDIO_EXTS = {
    ".mp3", ".m4a", ".m4b", ".wav", ".aac", ".flac", ".ogg", ".opus",
    ".mp4", ".mov", ".m4v",
}


def is_youtube_url(url):
    host = urlparse(url).hostname or ""
    return any(h in host for h in ("youtube.com", "youtu.be", "youtube-nocookie.com"))


def is_audio_file(path):
    """ローカルの音声/動画ファイルか判定"""
    p = Path(path).expanduser()
    return p.is_file() and p.suffix.lower() in AUDIO_EXTS


def url_to_id(url):
    return hashlib.sha256(url.encode()).hexdigest()[:12]


def setup_dirs():
    TRANSCRIPT_DIR.mkdir(parents=True, exist_ok=True)
    AUDIO_TMP_DIR.mkdir(parents=True, exist_ok=True)


def get_videos(url):
    """URLから動画情報を取得（再生リストでも単体でもOK）"""
    print("動画情報を取得中...")
    result = subprocess.run(
        ["yt-dlp", "--flat-playlist", "-J", url],
        capture_output=True, text=True
    )
    if result.returncode != 0:
        print(f"エラー: 動画情報の取得失敗\n{result.stderr}")
        sys.exit(1)

    data = json.loads(result.stdout)

    # 単体動画の場合
    if "entries" not in data:
        return [{
            "id": data.get("id", "unknown"),
            "title": data.get("title", "unknown"),
            "url": url
        }]

    # 再生リストの場合
    videos = []
    for entry in data.get("entries", []):
        videos.append({
            "id": entry["id"],
            "title": entry.get("title", "unknown"),
            "url": f"https://www.youtube.com/watch?v={entry['id']}"
        })
    return videos


def download_audio(video):
    """動画の音声をダウンロード"""
    output_path = AUDIO_TMP_DIR / f"{video['id']}.mp3"
    if output_path.exists():
        print(f"  音声キャッシュあり")
        return output_path

    print(f"  音声ダウンロード中...")
    result = subprocess.run(
        ["yt-dlp", "-x", "--audio-format", "mp3", "--audio-quality", "5",
         "-o", str(output_path), video["url"]],
        capture_output=True, text=True
    )
    if result.returncode != 0:
        print(f"  ダウンロード失敗: {result.stderr[:200]}")
        return None
    return output_path


def is_hallucinated(text, threshold=0.4):
    """Whisperハルシネーション検出（同一フレーズの繰り返し）"""
    if len(text) < 50:
        return True
    # 2〜20文字の繰り返しパターンを検出
    match = re.search(r"(.{2,20})\1{4,}", text)
    if match and len(match.group(0)) / len(text) > threshold:
        return True
    # 文字種の偏り（句読点・記号だらけ）
    content_chars = re.sub(r"[\s。、…・！？!?,.\d]", "", text)
    if len(content_chars) < len(text) * 0.2:
        return True
    return False


def get_subtitles(video):
    """YouTube字幕を取得（日本語手動 → 日本語自動 → 英語手動 → 英語自動の順で試行）"""
    for lang, sub_args in [
        ("ja", ["--write-subs", "--sub-langs", "ja"]),
        ("ja", ["--write-auto-subs", "--sub-langs", "ja"]),
        ("en", ["--write-subs", "--sub-langs", "en"]),
        ("en", ["--write-auto-subs", "--sub-langs", "en"]),
    ]:
        result = subprocess.run(
            ["yt-dlp", "--skip-download", *sub_args,
             "--convert-subs", "srt", "-o", "/tmp/yt_subs_%(id)s", video["url"]],
            capture_output=True, text=True
        )
        srt_path = Path(f"/tmp/yt_subs_{video['id']}.{lang}.srt")
        if srt_path.exists():
            text = srt_path.read_text(encoding="utf-8")
            srt_path.unlink()
            lines = [l.strip() for l in text.splitlines()
                     if l.strip() and not re.match(r"^\d+$", l.strip())
                     and not re.match(r"\d{2}:\d{2}:\d{2}", l.strip())]
            source_lang = "en" if lang == "en" else None
            return " ".join(lines), source_lang
    return None, None


def get_description(video):
    """YouTube説明欄を取得"""
    result = subprocess.run(
        ["yt-dlp", "--print", "description", video["url"]],
        capture_output=True, text=True
    )
    if result.returncode == 0 and len(result.stdout.strip()) >= 50:
        return result.stdout.strip()
    return None


def save_transcript(video, text, source="whisper"):
    """文字起こしテキストをファイルに保存"""
    transcript_path = TRANSCRIPT_DIR / f"{video['id']}.txt"
    header = f"title: {video['title']}\nvideo_id: {video['id']}\nurl: {video['url']}"
    if source != "whisper":
        header += f"\nsource: {source}"
    content = f"{header}\n---\n{text}"
    tmp_fd, tmp_path = tempfile.mkstemp(dir=TRANSCRIPT_DIR, suffix=".tmp")
    try:
        with open(tmp_fd, "w", encoding="utf-8") as f:
            f.write(content)
        Path(tmp_path).replace(transcript_path)
    except Exception:
        Path(tmp_path).unlink(missing_ok=True)
        raise
    return transcript_path


def _is_js_wall(text):
    if not text:
        return False
    if "JavaScript is disabled" in text:
        return True
    stripped = re.sub(r"(Loading\.{0,3})+", "", text).strip()
    if len(stripped) < 50:
        return True
    return False


def fetch_with_trafilatura(url):
    """trafilaturaでテキスト抽出を試みる。失敗時はNone"""
    try:
        import trafilatura
    except ImportError:
        return None, None
    downloaded = trafilatura.fetch_url(url)
    if not downloaded:
        return None, None
    text = trafilatura.extract(downloaded, include_links=False, include_images=False)
    if not text or len(text.strip()) < 100 or _is_js_wall(text):
        return None, None
    meta = trafilatura.extract(downloaded, output_format="json")
    title = json.loads(meta).get("title", "") if meta else ""
    return text, title


def fetch_with_playwright(url):
    """Playwrightでヘッドレスブラウザ経由のテキスト抽出（JS必須サイト用）"""
    try:
        from playwright.sync_api import sync_playwright
        import trafilatura
    except ImportError as e:
        print(f"  フォールバック不可: {e}")
        return None, None
    print(f"  ヘッドレスブラウザで取得中...")
    try:
        cookies = _get_browser_cookies(url)
        with sync_playwright() as p:
            browser = p.chromium.launch()
            ctx = browser.new_context()
            if cookies:
                ctx.add_cookies(cookies)
            page = ctx.new_page()
            page.goto(url, wait_until="domcontentloaded", timeout=15000)
            page.wait_for_timeout(5000)
            html = page.content()
            browser.close()
        text = trafilatura.extract(html, include_links=False, include_images=False)
        if not text or len(text.strip()) < 100:
            return None, None
        meta = trafilatura.extract(html, output_format="json")
        title = json.loads(meta).get("title", "") if meta else ""
        return text, title
    except Exception as e:
        print(f"  ブラウザ取得エラー: {e}")
        return None, None


def _get_browser_cookies(url):
    """ChromeからCookieを取得（rookiepy利用、なければ空リスト）"""
    try:
        import rookiepy
    except ImportError:
        return []
    host = urlparse(url).hostname or ""
    domains = [f".{host}"]
    if host.startswith("www."):
        domains.append(f".{host[4:]}")
    # x.com / twitter.com の相互対応
    if "x.com" in host:
        domains.append(".twitter.com")
    elif "twitter.com" in host:
        domains.append(".x.com")
    try:
        raw = rookiepy.chrome(domains)
    except Exception:
        return []
    return [{
        "name": c["name"], "value": c["value"], "domain": c["domain"],
        "path": c.get("path", "/"), "secure": c.get("secure", False),
        "httpOnly": c.get("httpOnly", False),
    } for c in raw]


def resolve_article_url(url):
    """X のツイートが Article へのリンクを含む場合、Article URL を返す"""
    host = urlparse(url).hostname or ""
    if "x.com" not in host and "twitter.com" not in host:
        return url
    if "/article/" in url:
        return url
    try:
        import trafilatura
        html = trafilatura.fetch_url(url)
        if not html:
            return url
        import re as _re
        match = _re.search(r'https://t\.co/[A-Za-z0-9]+', html)
        if match:
            import requests
            resp = requests.head(match.group(), allow_redirects=True, timeout=10)
            resolved = resp.url
            if "/article/" in resolved or "/i/article/" in resolved:
                print(f"  Article URL検出: {resolved}")
                return resolved
    except Exception:
        pass
    return url


def fetch_article(url):
    """Webページからテキストを抽出して .transcripts/ に保存"""
    article_id = url_to_id(url)
    if is_processed(article_id):
        print(f"  スキップ（処理済み）")
        return None

    print(f"  記事を取得中...")
    actual_url = resolve_article_url(url)
    text, title = fetch_with_trafilatura(actual_url)
    if not text:
        text, title = fetch_with_playwright(actual_url)
    if not text:
        print(f"  テキストを抽出できませんでした")
        return None

    if not title:
        first_line = text.strip().split("\n")[0].strip().rstrip(".")
        title = first_line[:100] if len(first_line) > 10 else url
    article = {"id": article_id, "title": title, "url": url}
    path = save_transcript(article, text, source="web-article")
    print(f"  完了: {title[:60]}")
    return path


def transcribe_video(video):
    """字幕優先で文字起こし（字幕なし時のみWhisperにフォールバック）"""
    # 1. YouTube字幕を試す（高速）
    print(f"  字幕を確認中...")
    sub_text, source_lang = get_subtitles(video)
    if sub_text:
        source = "youtube-subtitles"
        if source_lang == "en":
            source = "youtube-subtitles-en"
            print(f"  英語字幕から取得しました")
        else:
            print(f"  字幕から取得しました")
        return save_transcript(video, sub_text, source=source)

    # 2. Whisperで文字起こし（低速）
    print(f"  字幕なし。Whisperで文字起こし中...")
    audio_path = download_audio(video)
    if not audio_path:
        return None

    text = None
    try:
        import mlx_whisper
        result = mlx_whisper.transcribe(
            str(audio_path),
            path_or_hf_repo=WHISPER_MODEL,
            language="ja",
            verbose=False
        )
        text = result["text"]
    except Exception as e:
        print(f"  文字起こしエラー: {e}")

    audio_path.unlink(missing_ok=True)

    if text is not None and not is_hallucinated(text):
        return save_transcript(video, text)

    if text is not None:
        print(f"  ハルシネーション検出。説明欄を確認中...")
    else:
        print(f"  説明欄を確認中...")
    desc_text = get_description(video)
    if desc_text:
        print(f"  説明欄から取得しました")
        return save_transcript(video, desc_text, source="youtube-description")

    print(f"  すべて失敗。スキップします。")
    return None


def transcribe_local_file(path):
    """ローカルの音声/動画ファイルをWhisperで文字起こし（yt-dlpを経由しない）"""
    p = Path(path).expanduser().resolve()
    uri = f"file://{p}"
    video = {"id": url_to_id(uri), "title": p.name, "url": uri}

    if is_processed(video["id"]):
        print(f"  スキップ（処理済み）")
        return None

    print(f"  Whisperで文字起こし中...")
    text = None
    try:
        import mlx_whisper
        result = mlx_whisper.transcribe(
            str(p),
            path_or_hf_repo=WHISPER_MODEL,
            language="ja",
            verbose=False
        )
        text = result["text"]
    except Exception as e:
        print(f"  文字起こしエラー: {e}")
        return None

    if text is None or is_hallucinated(text):
        print(f"  文字起こしに失敗しました（内容が読み取れません）。")
        return None

    return save_transcript(video, text, source="local-audio")


def is_processed(video_id):
    """文字起こし済み or ノート変換済み（done/に移動済み）か判定"""
    return (TRANSCRIPT_DIR / f"{video_id}.txt").exists() or (DONE_DIR / f"{video_id}.txt").exists()


def check_mlx_whisper():
    try:
        import mlx_whisper  # noqa: F401
        return True
    except ImportError:
        print("エラー: mlx-whisper がインストールされていません。")
        print("  ~/scripts/.venv/bin/pip install mlx-whisper")
        return False


def main():
    global OBSIDIAN_OUTPUT_DIR, TRANSCRIPT_DIR, DONE_DIR

    parser = argparse.ArgumentParser(description="YouTube動画の文字起こし / Web記事のテキスト抽出")
    parser.add_argument("url", help="YouTubeのURL、再生リストURL、またはWeb記事のURL")
    parser.add_argument("-o", "--output-dir", help="出力先ディレクトリ")
    args = parser.parse_args()
    url = args.url

    if args.output_dir:
        OBSIDIAN_OUTPUT_DIR = Path(args.output_dir).expanduser()
        TRANSCRIPT_DIR = OBSIDIAN_OUTPUT_DIR / ".transcripts"
        DONE_DIR = TRANSCRIPT_DIR / "done"

    setup_dirs()

    if is_audio_file(url):
        print(f"ローカル音声/動画として処理: {url}\n")
        if not check_mlx_whisper():
            sys.exit(1)
        result = transcribe_local_file(url)
        if not result:
            sys.exit(1)
        return

    if not is_youtube_url(url):
        print(f"Web記事として処理: {url}\n")
        result = fetch_article(url)
        if not result:
            sys.exit(1)
        return

    if not check_mlx_whisper():
        sys.exit(1)

    videos = get_videos(url)
    print(f"\n{len(videos)}本の動画が見つかりました。\n")

    done = 0
    failed = 0
    skipped = 0

    for i, video in enumerate(videos, 1):
        print(f"[{i}/{len(videos)}] {video['title'][:60]}")

        if is_processed(video['id']):
            print(f"  スキップ（処理済み）\n")
            skipped += 1
            continue

        result = transcribe_video(video)
        if result:
            done += 1
        else:
            failed += 1
        print()

    print(f"\n{'='*50}")
    print(f"完了！ 新規: {done}本 / スキップ: {skipped}本 / 失敗: {failed}本")

    if failed > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
