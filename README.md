# youtube-recipe-pipeline

YouTube料理動画の音声を文字起こしし、Obsidianのレシピノートに自動変換するツール。

## インストール

```bash
curl -fsSL https://raw.githubusercontent.com/nobu666/youtube-recipe-pipeline-pipeline/main/install.sh | bash
```

brew、venv、シンボリックリンク、Claude Code スキルまで一括セットアップ。既存環境では更新のみ行う。

## 仕組み

1. **transcribe.py** — yt-dlp で音声抽出 → mlx-whisper でローカル文字起こし → `_transcripts/` に保存
2. **recipe** — transcribe.py を実行後、Claude CLI (`claude -p`) で文字起こしをレシピ形式に変換

## 必要なもの

- macOS（Apple Silicon）
- Python 3.10+
- [Claude Code](https://docs.claude.com/en/docs/claude-code) (`claude` コマンド)
- Obsidian Vault（レシピの保存先）

## セットアップ

```bash
# ツールのインストール
brew install yt-dlp ffmpeg python@3.12

# リポジトリのクローン
git clone https://github.com/nobu666/youtube-recipe-pipeline-pipeline.git ~/repos/youtube-recipe-pipeline-pipeline

# venv 作成と mlx-whisper インストール
python3.12 -m venv ~/scripts/.venv
~/scripts/.venv/bin/pip install mlx-whisper

# シンボリックリンクを作成
mkdir -p ~/scripts
ln -s ~/repos/youtube-recipe-pipeline-pipeline/recipe ~/scripts/recipe
ln -s ~/repos/youtube-recipe-pipeline-pipeline/transcribe.py ~/scripts/transcribe.py

# Claude Code のスキルをインストール（任意）
mkdir -p ~/.claude/commands
cp ~/repos/youtube-recipe-pipeline-pipeline/SKILL.md ~/.claude/commands/youtube-recipe-pipeline.md
```

`recipe` 内のパスを自分の環境に合わせて編集:

```bash
SCRIPT="$HOME/scripts/transcribe.py"                                          # transcribe.py のパス
RECIPE_DIR="$HOME/Library/Mobile Documents/com~apple~CloudDocs/Obsidian/Vault/レシピ"  # Obsidian Vault のパス
```

`transcribe.py` 内の `OBSIDIAN_RECIPE_DIR` も同様に変更。

## 使い方

```bash
# 再生リストをまとめて処理
~/scripts/recipe https://www.youtube.com/playlist?list=XXXXX

# 単体の動画
~/scripts/recipe https://www.youtube.com/watch?v=XXXXX

# 文字起こしだけ（レシピ変換なし）
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

1. YouTubeの再生リストにレシピ動画を追加していく
2. `~/scripts/recipe` を実行
3. 完了後、最後に表示される処理結果を確認
4. 問題なければ再生リストから処理済みの動画を削除

### 失敗した動画のリトライ

失敗した文字起こしは `_transcripts/` に残るので、そのまま再実行すればレシピ変換だけリトライされる。

```bash
~/scripts/recipe
```

文字起こし自体の品質が悪かった場合は、文字起こしファイルを削除してからやり直す。

```bash
# 特定の動画を文字起こしからやり直し
rm "<vault>/_transcripts/<video_id>.txt"
~/scripts/recipe "https://www.youtube.com/watch?v=<video_id>"

# 失敗分をまとめてやり直し
rm <vault>/_transcripts/*.txt
~/scripts/recipe
```

### ファイルの状態

| 場所 | 意味 |
|------|------|
| `_transcripts/*.txt` | 未処理 or レシピ変換に失敗した文字起こし |
| `_transcripts/done/*.txt` | レシピ変換済みの文字起こし（参照用に保持） |
| `<vault>/*.md` | 完成したレシピノート |

## Claude Code スキル

`SKILL.md` を `~/.claude/commands/youtube-recipe-pipeline.md` に配置すると、Claude Code のどのセッションからでも `/youtube-recipe-pipeline` コマンドでレシピ変換を実行できる。`_transcripts/` 内の文字起こしファイルを読み取り、対話的にレシピ化する。

```bash
# インストール
cp ~/repos/youtube-recipe-pipeline-pipeline/SKILL.md ~/.claude/commands/youtube-recipe-pipeline.md
```

## 注意点

- mlx-whisper は Apple Silicon 専用。Intel Mac では動かない
- Whisper large-v3 モデル（約3GB）を使用。初回実行時にダウンロードされる
- 処理済みの動画はスキップされるので、中断しても再開可能
- Whisperのハルシネーション（同一フレーズの繰り返し）は自動検出してスキップする
- `MallocStackLogging` の警告が出ることがあるが無害
