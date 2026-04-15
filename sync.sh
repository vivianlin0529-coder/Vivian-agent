#!/bin/bash

# Vivian-Agent 同步腳本
# 用途：同步本地變更到 GitHub，並拉取最新版本
# 使用方式：./sync.sh 或由 cron 自動執行

REPO_DIR="$(cd "$(dirname "$0")" && pwd)"
LOG_FILE="$REPO_DIR/.sync.log"
TIMESTAMP=$(date '+%Y-%m-%d %H:%M:%S')

cd "$REPO_DIR" || exit 1

echo "[$TIMESTAMP] 開始同步..." >> "$LOG_FILE"

# 1. 拉取遠端最新版本（優先處理衝突）
git fetch origin >> "$LOG_FILE" 2>&1

# 2. 如果有本地變更，先 commit
if ! git diff --quiet || ! git diff --cached --quiet; then
    git add .
    git commit -m "auto-sync: $TIMESTAMP" >> "$LOG_FILE" 2>&1
    echo "[$TIMESTAMP] 已 commit 本地變更" >> "$LOG_FILE"
fi

# 3. 合併遠端變更（rebase 策略，保持 commit 整潔）
git pull --rebase origin main >> "$LOG_FILE" 2>&1

# 4. 推送到 GitHub
git push origin main >> "$LOG_FILE" 2>&1

echo "[$TIMESTAMP] 同步完成" >> "$LOG_FILE"
echo "---" >> "$LOG_FILE"
