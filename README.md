# youtube-to-obsidian

YouTube動画やWeb記事をObsidianの構造化ノートに自動変換するツール。プロンプトを切り替えることで、レシピ・講義ノート・トレーニングメニュー・ツール解説・記事要約など様々な形式に対応。

## インストール

```bash
curl -fsSL https://raw.githubusercontent.com/nobu666/youtube-to-obsidian/main/install.sh | bash
```

brew（yt-dlp, ffmpeg）、Python venv（mlx-whisper）、シンボリックリンク、Claude Code スキルまで一括セットアップ。既存環境では更新のみ行う。

### 前提

- macOS（Apple Silicon）
- Python 3.10+
- [Claude Code](https://docs.claude.com/en/docs/claude-code) (`claude` コマンド)
- Obsidian Vault（ノートの保存先）

出力先を変更する場合は、各プロンプトファイル（`prompts/*.txt`）の `output_dir:` ヘッダを編集する。

## 仕組み

1. **transcribe.py** — YouTube字幕を優先取得（数秒）。字幕がない場合のみ mlx-whisper でローカル文字起こし。YouTube以外のURLはWeb記事としてテキスト抽出（trafilatura → Playwrightフォールバック）
2. **youtube-to-obsidian** — transcribe.py を実行後、Claude CLI (`claude -p`) で文字起こし/記事テキストを構造化ノートに変換

## 使い方

```bash
# デフォルト（汎用ノート形式）
~/scripts/youtube-to-obsidian https://www.youtube.com/watch?v=XXXXX

# プロンプトを指定
~/scripts/youtube-to-obsidian -p recipe https://www.youtube.com/watch?v=XXXXX

# 再生リストをまとめて処理
~/scripts/youtube-to-obsidian -p lecture https://www.youtube.com/playlist?list=XXXXX

# 出力先を一時的に上書き
~/scripts/youtube-to-obsidian -p tool -o ~/notes https://www.youtube.com/watch?v=XXXXX

# Web記事をノート化（X Article、ブログ記事など）
~/scripts/youtube-to-obsidian -p article https://x.com/user/status/XXXXX
~/scripts/youtube-to-obsidian -p article https://example.com/blog/post

# 文字起こし/テキスト抽出だけ（ノート変換なし）
~/scripts/.venv/bin/python3 ~/scripts/transcribe.py https://www.youtube.com/watch?v=XXXXX
~/scripts/.venv/bin/python3 ~/scripts/transcribe.py https://x.com/user/status/XXXXX
```

## プロンプト一覧

各プロンプトは `prompts/` ディレクトリに格納。`output_dir:` ヘッダでプロンプトごとに出力先が決まる（フォルダは自動作成）。

| プロンプト | 用途 | 出力先 |
|---|---|---|
| `default` | 汎用（構造化ノート） | `Vault/YouTube/` |
| `recipe` | 料理動画 → レシピ | `Vault/YouTube/レシピ/` |
| `lecture` | 講義・セミナー → 要約ノート | `Vault/YouTube/講義/` |
| `workout` | 筋トレ・ヨガ → メニュー表 | `Vault/YouTube/トレーニング/` |
| `tool` | ツール解説 → 手順書 | `Vault/YouTube/ツール/` |
| `article` | Web記事 → 日本語要約ノート | `Vault/YouTube/` |

`prompts/` にファイルを追加すればさらに用途を増やせる。

### プロンプトファイルの形式

```
output_dir: ~/Documents/Obsidian/Vault/YouTube/講義
---
上の文字起こしをObsidian講義ノート形式に変換して {{OUTPUT_DIR}} に保存して。
...
```

`output_dir:` ヘッダで出力先を指定し、`---` 以降がClaudeに渡されるプロンプト本文。`{{OUTPUT_DIR}}` は実行時に実際のパスに置換される。

## 運用の流れ

1. YouTubeの再生リストにノート化したい動画を追加していく
2. `~/scripts/youtube-to-obsidian -p <prompt>` を実行
3. 完了後、最後に表示される処理結果を確認
4. 問題なければ再生リストから処理済みの動画を削除

### 失敗した動画のリトライ

失敗した文字起こしは `.transcripts/` に残るので、そのまま再実行すればノート変換だけリトライされる。

```bash
~/scripts/youtube-to-obsidian -p recipe
```

文字起こし自体の品質が悪かった場合は、文字起こしファイルを削除してからやり直す。

```bash
# 特定の動画を文字起こしからやり直し
rm "<vault>/.transcripts/<video_id>.txt"
~/scripts/youtube-to-obsidian -p recipe "https://www.youtube.com/watch?v=<video_id>"
```

### ファイルの状態

| 場所 | 意味 |
|------|------|
| `.transcripts/*.txt` | 未処理 or ノート変換に失敗した文字起こし |
| `.transcripts/done/*.txt` | ノート変換済みの文字起こし（参照用に保持） |
| `<output_dir>/*.md` | 完成したノート |

## Claude Code スキル

`SKILL.md` を `~/.claude/commands/youtube-to-obsidian.md` に配置すると、Claude Code のどのセッションからでも `/youtube-to-obsidian` コマンドでノート変換を実行できる。`.transcripts/` 内の文字起こしファイルを読み取り、対話的にノート化する。

```bash
# インストール
cp ~/repos/youtube-to-obsidian/SKILL.md ~/.claude/commands/youtube-to-obsidian.md
```

## 注意点

- mlx-whisper は Apple Silicon 専用。Intel Mac では動かない
- 文字起こしはYouTube字幕（手動→自動生成）を優先取得する。字幕がない動画のみ Whisper large-v3-turbo（約3GB）にフォールバック
- Whisperのハルシネーション（同一フレーズの繰り返し）は自動検出し、説明欄でフォールバックする
- Web記事の取得は trafilatura → Playwright（Chromeの Cookie 付き）の順でフォールバック。X Article などJS必須サイトは Playwright が必要
- 処理済みの動画/記事はスキップされるので、中断しても再開可能
- `MallocStackLogging` の警告が出ることがあるが無害
