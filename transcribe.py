#!/usr/bin/env python3
"""
YouTube動画の音声をダウンロードし、Whisperで文字起こしする。
結果はObsidian Vault内の .transcripts/ に保存される。
構造化ノートへの変換は recipe スクリプト経由で Claude CLI が担当する。
"""

import os
import re
import subprocess
import json
import sys
import tempfile
import warnings
from pathlib import Path

os.environ["MALLOC_STACK_LOGGING"] = ""
warnings.filterwarnings("ignore", message=".*unauthenticated.*HF Hub.*")

# === 設定 ===
OBSIDIAN_RECIPE_DIR = Path.home() / "Library/Mobile Documents/com~apple~CloudDocs/Obsidian/Vault/レシピ"
TRANSCRIPT_DIR = OBSIDIAN_RECIPE_DIR / ".transcripts"
AUDIO_TMP_DIR = Path("/tmp/yt_recipe_audio")
WHISPER_MODEL = "mlx-community/whisper-large-v3-mlx"
DONE_DIR = TRANSCRIPT_DIR / "done"


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
    """YouTube字幕を取得（手動字幕 → 自動生成の順で試行）"""
    for sub_args in [
        ["--write-subs", "--sub-langs", "ja"],
        ["--write-auto-subs", "--sub-langs", "ja"],
    ]:
        result = subprocess.run(
            ["yt-dlp", "--skip-download", *sub_args,
             "--convert-subs", "srt", "-o", "/tmp/yt_subs_%(id)s", video["url"]],
            capture_output=True, text=True
        )
        srt_path = Path(f"/tmp/yt_subs_{video['id']}.ja.srt")
        if srt_path.exists():
            text = srt_path.read_text(encoding="utf-8")
            srt_path.unlink()
            lines = [l.strip() for l in text.splitlines()
                     if l.strip() and not re.match(r"^\d+$", l.strip())
                     and not re.match(r"\d{2}:\d{2}:\d{2}", l.strip())]
            return " ".join(lines)
    return None


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


def transcribe_audio(audio_path, video):
    """Whisperで文字起こし（失敗時は字幕・説明欄にフォールバック）"""
    print(f"  文字起こし中...")
    whisper_failed = False
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
        whisper_failed = True

    if not whisper_failed and not is_hallucinated(text):
        return save_transcript(video, text)

    if not whisper_failed:
        print(f"  ハルシネーション検出。フォールバックを試行...")

    print(f"  字幕を確認中...")
    sub_text = get_subtitles(video)
    if sub_text:
        print(f"  字幕から取得しました")
        return save_transcript(video, sub_text, source="youtube-subtitles")

    print(f"  説明欄を確認中...")
    desc_text = get_description(video)
    if desc_text:
        print(f"  説明欄から取得しました")
        return save_transcript(video, desc_text, source="youtube-description")

    print(f"  フォールバックも失敗。スキップします。")
    return None


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
    setup_dirs()

    if len(sys.argv) > 1:
        url = sys.argv[1]
    else:
        print("使い方: ~/scripts/.venv/bin/python3 transcribe.py <YouTubeのURLまたは再生リストURL>")
        sys.exit(1)

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

        audio_path = download_audio(video)
        if not audio_path:
            failed += 1
            print()
            continue

        result = transcribe_audio(audio_path, video)
        if result:
            done += 1
            audio_path.unlink(missing_ok=True)
        else:
            failed += 1
        print()

    print(f"\n{'='*50}")
    print(f"完了！ 新規: {done}本 / スキップ: {skipped}本 / 失敗: {failed}本")

    if failed > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
