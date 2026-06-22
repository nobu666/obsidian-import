#!/usr/bin/env python3
"""
ドキュメント（URL または ローカルファイル）をMarkItDownで
Markdown化し、.transcripts/ に保存する。
obsidian-import スクリプトから呼ばれ、既存のClaude変換フローに合流する。

対応ソース:
  - URL: Google Docs/Slides, Slideshare, Web上のPDF, 任意のWebページ
  - ファイル: PDF, PPTX, DOCX, XLSX, 画像, 音声 等
"""

import argparse
import hashlib
import sys
import tempfile
from pathlib import Path
from urllib.parse import urlparse

from markitdown import MarkItDown

# symlink 経由（~/scripts/）で起動されても url_guard を解決できるよう実体dirを通す
sys.path.insert(0, str(Path(__file__).resolve().parent))
from url_guard import UnsafeURLError, assert_safe_url

DEFAULT_OUTPUT_DIR = Path.home() / "Documents/Obsidian/Vault/YouTube"

SUPPORTED_EXTENSIONS = {
    ".pdf", ".pptx", ".ppt", ".docx", ".doc", ".xlsx", ".xls",
    ".html", ".htm", ".csv", ".tsv", ".json", ".xml",
    ".jpg", ".jpeg", ".png", ".gif", ".bmp", ".tiff", ".webp",
    ".mp3", ".wav", ".m4a",
    ".zip",
}


def source_id(source):
    """ソース（URLまたはファイルパス）からユニークIDを生成"""
    return hashlib.md5(source.encode()).hexdigest()[:12]


def _hdr_val(v):
    """ヘッダ値の改行を除去し、本文との `---` 境界やキーの偽装注入を防ぐ"""
    return str(v).replace("\r", " ").replace("\n", " ")


def is_url(s):
    parsed = urlparse(s)
    return parsed.scheme in ("http", "https")


def title_from_url(url):
    """URLからタイトルを推測"""
    parsed = urlparse(url)
    path = parsed.path.rstrip("/")
    if path and path != "/":
        return Path(path).name or parsed.netloc
    return parsed.netloc


# zip爆弾対策の上限
ZIP_MAX_ENTRIES = 1000
ZIP_MAX_TOTAL_BYTES = 500 * 1024 * 1024   # 展開後の合計サイズ上限 500MB
ZIP_MAX_RATIO = 100                        # 1エントリの展開/圧縮比の上限


def check_zip_safe(path):
    """zip爆弾チェック。危険なら理由文字列、安全なら None を返す。"""
    import zipfile
    try:
        with zipfile.ZipFile(path) as zf:
            infos = zf.infolist()
            if len(infos) > ZIP_MAX_ENTRIES:
                return f"エントリ数が多すぎます ({len(infos)} > {ZIP_MAX_ENTRIES})"
            total = 0
            for zi in infos:
                total += zi.file_size
                if total > ZIP_MAX_TOTAL_BYTES:
                    return f"展開後の合計サイズが大きすぎます (> {ZIP_MAX_TOTAL_BYTES} bytes)"
                if zi.compress_size > 0 and zi.file_size / zi.compress_size > ZIP_MAX_RATIO:
                    return f"圧縮率が異常です（zip爆弾の疑い）: {zi.filename}"
    except zipfile.BadZipFile:
        return "不正なzipファイルです"
    return None


def convert(source, output_dir):
    """MarkItDownでソースをMarkdown化し、.transcripts/に保存"""
    transcript_dir = output_dir / ".transcripts"
    done_dir = transcript_dir / "done"
    transcript_dir.mkdir(parents=True, exist_ok=True)
    done_dir.mkdir(parents=True, exist_ok=True)

    fid = source_id(source)
    transcript_path = transcript_dir / f"{fid}.txt"

    if transcript_path.exists() or (done_dir / f"{fid}.txt").exists():
        print(f"  スキップ（処理済み）")
        return None

    if is_url(source):
        try:
            assert_safe_url(source)
        except UnsafeURLError as e:
            print(f"  アクセスをブロックしました: {e}")
            return False
    else:
        # .zip だけでなく docx/pptx/xlsx 等の OOXML も中身は ZIP アーカイブなので、
        # 拡張子でなく「中身がzipか」で判定して zip爆弾を一律に弾く。
        import zipfile
        if Path(source).is_file() and zipfile.is_zipfile(source):
            reason = check_zip_safe(source)
            if reason:
                print(f"  zip系ファイルを拒否: {reason}")
                return False

    md = MarkItDown()
    try:
        result = md.convert(source)
        text = result.text_content
    except Exception as e:
        print(f"  変換エラー: {e}")
        return False

    if not text or len(text.strip()) < 20:
        print(f"  変換失敗: 内容が空または短すぎます")
        return False

    if is_url(source):
        title = title_from_url(source)
        header = f"title: {_hdr_val(title)}\nurl: {_hdr_val(source)}\nsource: markitdown-url"
    else:
        file_path = Path(source).resolve()
        header = f"title: {_hdr_val(file_path.name)}\nurl: file://{_hdr_val(str(file_path))}\nsource: markitdown-file"

    content = f"{header}\n---\n{text}"

    tmp_fd, tmp_path = tempfile.mkstemp(dir=transcript_dir, suffix=".tmp")
    try:
        with open(tmp_fd, "w", encoding="utf-8") as f:
            f.write(content)
        Path(tmp_path).replace(transcript_path)
    except Exception:
        Path(tmp_path).unlink(missing_ok=True)
        raise

    return transcript_path


def collect_inputs(args_list):
    """引数リストからURL・ファイルを収集"""
    inputs = []
    for arg in args_list:
        if is_url(arg):
            inputs.append(arg)
        else:
            p = Path(arg).expanduser()
            if p.is_dir():
                for ext in SUPPORTED_EXTENSIONS:
                    inputs.extend(str(f) for f in p.glob(f"*{ext}"))
            elif p.exists():
                inputs.append(str(p))
            else:
                print(f"警告: 見つかりません: {arg}")
    return inputs


def main():
    parser = argparse.ArgumentParser(description="ドキュメント・URLをMarkdown化する")
    parser.add_argument("inputs", nargs="+", help="URL またはファイルパス")
    parser.add_argument("-o", "--output-dir", help="出力先ディレクトリ")
    args = parser.parse_args()

    output_dir = Path(args.output_dir).expanduser() if args.output_dir else DEFAULT_OUTPUT_DIR

    inputs = collect_inputs(args.inputs)
    if not inputs:
        print("変換対象がありません。")
        sys.exit(1)

    print(f"\n{len(inputs)}件を変換します。\n")

    done = 0
    failed = 0
    skipped = 0

    for i, source in enumerate(inputs, 1):
        label = source if is_url(source) else Path(source).name
        print(f"[{i}/{len(inputs)}] {label}")

        if not is_url(source):
            ext = Path(source).suffix.lower()
            if ext not in SUPPORTED_EXTENSIONS:
                print(f"  スキップ（未対応形式: {ext}）")
                skipped += 1
                print()
                continue

        result = convert(source, output_dir)
        if result is None:
            skipped += 1
        elif result is False:
            failed += 1
        else:
            done += 1
            print(f"  → 完了")
        print()

    print(f"\n{'='*50}")
    print(f"完了！ 新規: {done}件 / スキップ: {skipped}件 / 失敗: {failed}件")


if __name__ == "__main__":
    main()
