# youtube-to-obsidian

YouTube動画の音声を文字起こしし、Obsidianの構造化ノートに自動変換するツール。現在はレシピノートの生成に使用中。

## インストール

```bash
curl -fsSL https://raw.githubusercontent.com/nobu666/youtube-to-obsidian/main/install.sh | bash
```

brew、venv、シンボリックリンク、Claude Code スキルまで一括セットアップ。既存環境では更新のみ行う。

## 仕組み

1. **transcribe.py** — yt-dlp で音声抽出 → mlx-whisper でローカル文字起こし → `.transcripts/` に保存
2. **youtube-to-obsidian** — transcribe.py を実行後、Claude CLI (`claude -p`) で文字起こしを構造化ノートに変換（現在はレシピ形式）

## 必要なもの

- macOS（Apple Silicon）
- Python 3.10+
- [Claude Code](https://docs.claude.com/en/docs/claude-code) (`claude` コマンド)
- Obsidian Vault（ノートの保存先）

## セットアップ

```bash
# ツールのインストール
brew install yt-dlp ffmpeg python@3.12

# リポジトリのクローン
git clone https://github.com/nobu666/youtube-to-obsidian.git ~/repos/youtube-to-obsidian

# venv 作成と mlx-whisper インストール
python3.12 -m venv ~/scripts/.venv
~/scripts/.venv/bin/pip install mlx-whisper

# シンボリックリンクを作成
mkdir -p ~/scripts
ln -s ~/repos/youtube-to-obsidian/youtube-to-obsidian ~/scripts/youtube-to-obsidian
ln -s ~/repos/youtube-to-obsidian/transcribe.py ~/scripts/transcribe.py

# Claude Code のスキルをインストール（任意）
mkdir -p ~/.claude/commands
cp ~/repos/youtube-to-obsidian/SKILL.md ~/.claude/commands/youtube-to-obsidian.md
```

`youtube-to-obsidian` 内のパスを自分の環境に合わせて編集:

```bash
SCRIPT="$HOME/scripts/transcribe.py"                                          # transcribe.py のパス
OUTPUT_DIR="$HOME/Library/Mobile Documents/com~apple~CloudDocs/Obsidian/Vault/レシピ"  # Obsidian Vault のパス
```

`transcribe.py` 内の `OBSIDIAN_OUTPUT_DIR` も同様に変更。

## 使い方

```bash
# 再生リストをまとめて処理
~/scripts/youtube-to-obsidian https://www.youtube.com/playlist?list=XXXXX

# 単体の動画
~/scripts/youtube-to-obsidian https://www.youtube.com/watch?v=XXXXX

# プロンプトを指定（デフォルトは prompt.txt）
~/scripts/youtube-to-obsidian -p prompt-lecture.txt https://www.youtube.com/watch?v=XXXXX

# 文字起こしだけ（ノート変換なし）
~/scripts/.venv/bin/python3 ~/scripts/transcribe.py https://www.youtube.com/watch?v=XXXXX
```

## 出力形式

```markdown
---
created: 2026-06-16 19:00
updated: 2026-06-16 19:00
source: https://www.youtube.com/watch?v=XXXXX
---

# 料理名

* 材料1 分量
* 材料2 分量

1. 手順1
2. 手順2
```

## 運用の流れ

1. YouTubeの再生リストにノート化したい動画を追加していく
2. `~/scripts/youtube-to-obsidian` を実行
3. 完了後、最後に表示される処理結果を確認
4. 問題なければ再生リストから処理済みの動画を削除

### 失敗した動画のリトライ

失敗した文字起こしは `.transcripts/` に残るので、そのまま再実行すればノート変換だけリトライされる。

```bash
~/scripts/youtube-to-obsidian
```

文字起こし自体の品質が悪かった場合は、文字起こしファイルを削除してからやり直す。

```bash
# 特定の動画を文字起こしからやり直し
rm "<vault>/.transcripts/<video_id>.txt"
~/scripts/youtube-to-obsidian "https://www.youtube.com/watch?v=<video_id>"

# 失敗分をまとめてやり直し
rm <vault>/.transcripts/*.txt
~/scripts/youtube-to-obsidian
```

### ファイルの状態

| 場所 | 意味 |
|------|------|
| `.transcripts/*.txt` | 未処理 or ノート変換に失敗した文字起こし |
| `.transcripts/done/*.txt` | ノート変換済みの文字起こし（参照用に保持） |
| `<vault>/*.md` | 完成したノート |

## Claude Code スキル

`SKILL.md` を `~/.claude/commands/youtube-to-obsidian.md` に配置すると、Claude Code のどのセッションからでも `/youtube-to-obsidian` コマンドでノート変換を実行できる。`.transcripts/` 内の文字起こしファイルを読み取り、対話的にノート化する。

```bash
# インストール
cp ~/repos/youtube-to-obsidian/SKILL.md ~/.claude/commands/youtube-to-obsidian.md
```

## 応用例

このパイプラインの仕組み（YouTube → ローカル文字起こし → Claude で構造化 → Obsidian）は、`prompt.txt` と出力先を差し替えるだけで他の用途にも応用できる。

| 動画のジャンル | 変換先のノート形式 |
|---|---|
| 技術チュートリアル | 手順書・コマンドチートシート |
| 講義・セミナー | 要約ノート・キーポイント集 |
| インタビュー・ポッドキャスト | Q&A形式のメモ |
| DIY・修理動画 | 工程表・部品リスト |
| 筋トレ・ヨガ | メニュー表（種目・セット数・時間） |

文字起こし部分（`transcribe.py`）はジャンルに依存しないので、そのまま流用できる。

## 注意点

- mlx-whisper は Apple Silicon 専用。Intel Mac では動かない
- Whisper large-v3 モデル（約3GB）を使用。初回実行時にダウンロードされる
- 処理済みの動画はスキップされるので、中断しても再開可能
- Whisperのハルシネーション（同一フレーズの繰り返し）は自動検出し、YouTube字幕→説明欄の順でフォールバックする。すべて失敗した場合のみスキップ
- `MallocStackLogging` の警告が出ることがあるが無害
