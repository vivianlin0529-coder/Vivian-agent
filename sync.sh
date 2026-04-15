#!/bin/bash

# Vivian-Agent 同步腳本
# 用途：備份 Claude 設定 + 同步到 GitHub + 拉取最新版本
# 使用方式：./sync.sh 或由 cron 自動執行

REPO_DIR="$(cd "$(dirname "$0")" && pwd)"
LOG_FILE="$REPO_DIR/.sync.log"
TIMESTAMP=$(date '+%Y-%m-%d %H:%M:%S')
CLAUDE_DIR="$HOME/.claude"
CONFIG_DIR="$REPO_DIR/claude-config"

cd "$REPO_DIR" || exit 1

echo "[$TIMESTAMP] 開始同步..." >> "$LOG_FILE"

# 1. 備份 Claude 設定到 repo
echo "[$TIMESTAMP] 備份 Claude 設定..." >> "$LOG_FILE"
cp "$CLAUDE_DIR/settings.json" "$CONFIG_DIR/settings.json" 2>> "$LOG_FILE"
cp "$CLAUDE_DIR/statusline-command.sh" "$CONFIG_DIR/statusline-command.sh" 2>> "$LOG_FILE"
rsync -a --delete "$CLAUDE_DIR/commands/" "$CONFIG_DIR/commands/" 2>> "$LOG_FILE"
rsync -a --delete "$CLAUDE_DIR/skills/" "$CONFIG_DIR/skills/" 2>> "$LOG_FILE"

# 2. 拉取遠端最新版本
git fetch origin >> "$LOG_FILE" 2>&1

# 3. 如果有本地變更，先 commit
if ! git diff --quiet || ! git diff --cached --quiet; then
    git add .
    git commit -m "auto-sync: $TIMESTAMP" >> "$LOG_FILE" 2>&1
    echo "[$TIMESTAMP] 已 commit 本地變更" >> "$LOG_FILE"
fi

# 4. 合併遠端變更（rebase 策略，保持 commit 整潔）
git pull --rebase origin main >> "$LOG_FILE" 2>&1

# 5. 推送到 GitHub
git push origin main >> "$LOG_FILE" 2>&1

echo "[$TIMESTAMP] 同步完成" >> "$LOG_FILE"
echo "---" >> "$LOG_FILE"
