#!/bin/bash
set -e

REPO_DIR="${INSTALL_DIR:-$HOME/repos}/obsidian-import"
SCRIPTS_DIR="$HOME/scripts"
VENV_DIR="$SCRIPTS_DIR/.venv"

echo "=== obsidian-import インストール ==="

# 依存ツール
echo ""
echo "--- brew パッケージ ---"
brew install yt-dlp ffmpeg python@3.12 2>/dev/null || brew upgrade yt-dlp ffmpeg python@3.12 2>/dev/null || true

# リポジトリ
echo ""
echo "--- リポジトリ ---"
if [ -d "$REPO_DIR/.git" ]; then
  echo "既存のリポジトリを更新..."
  git -C "$REPO_DIR" pull
else
  echo "クローン中..."
  mkdir -p "$(dirname "$REPO_DIR")"
  git clone https://github.com/nobu666/obsidian-import.git "$REPO_DIR"
fi

# venv
echo ""
echo "--- Python venv ---"
if [ ! -d "$VENV_DIR" ]; then
  python3.12 -m venv "$VENV_DIR"
fi
"$VENV_DIR/bin/pip" install -q mlx-whisper "markitdown[all]"

# シンボリックリンク
echo ""
echo "--- シンボリックリンク ---"
mkdir -p "$SCRIPTS_DIR"
ln -sf "$REPO_DIR/obsidian-import" "$SCRIPTS_DIR/obsidian-import"
ln -sf "$REPO_DIR/transcribe.py" "$SCRIPTS_DIR/transcribe.py"
ln -sf "$REPO_DIR/convert.py" "$SCRIPTS_DIR/convert.py"

# Claude Code スキル
echo ""
echo "--- Claude Code スキル ---"
mkdir -p "$HOME/.claude/commands"
cp "$REPO_DIR/SKILL.md" "$HOME/.claude/commands/obsidian-import.md"

echo ""
echo "=== 完了 ==="
echo "使い方: ~/scripts/obsidian-import <URL or file>"
echo "スキル: Claude Code で /obsidian-import"
