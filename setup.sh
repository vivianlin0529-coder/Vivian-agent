#!/bin/bash

# Vivian-Agent 一鍵安裝腳本
# 在新電腦執行這個腳本，自動完成所有設定
# 使用方式：bash setup.sh

set -e

REPO_URL="https://github.com/vivianlin0529-coder/Vivian-agent.git"
INSTALL_DIR="$HOME/Downloads/Vivian-agent"
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

echo ""
echo "=============================="
echo " Vivian-Agent 安裝程式"
echo "=============================="
echo ""

# 1. 確認 gh CLI 已登入
echo "▶ 確認 GitHub 登入狀態..."
if ! gh auth status &>/dev/null; then
    echo -e "${YELLOW}⚠ 尚未登入 GitHub，請先執行：${NC}"
    echo "   gh auth login"
    echo ""
    echo "登入後再重新執行此腳本。"
    exit 1
fi
echo -e "${GREEN}✓ GitHub 已登入${NC}"

# 2. 設定 gh 為 git 認證來源
gh auth setup-git

# 3. Clone 或更新 repo
if [ -d "$INSTALL_DIR/.git" ]; then
    echo "▶ 已存在，更新 repo..."
    cd "$INSTALL_DIR"
    git pull origin main
else
    echo "▶ Clone repo 到 $INSTALL_DIR..."
    git clone "$REPO_URL" "$INSTALL_DIR"
    cd "$INSTALL_DIR"
fi
echo -e "${GREEN}✓ Repo 就緒${NC}"

# 4. 設定 sync.sh 執行權限
chmod +x sync.sh
echo -e "${GREEN}✓ sync.sh 已設定執行權限${NC}"

# 5. 設定 cron job（避免重複新增）
echo "▶ 設定自動同步排程..."
CRON_JOB_1="0 9 * * * $INSTALL_DIR/sync.sh"
CRON_JOB_2="0 18 * * * $INSTALL_DIR/sync.sh"
CURRENT_CRON=$(crontab -l 2>/dev/null || true)

if echo "$CURRENT_CRON" | grep -qF "$INSTALL_DIR/sync.sh"; then
    echo -e "${GREEN}✓ 排程已存在，略過${NC}"
else
    (echo "$CURRENT_CRON"; echo ""; echo "# Vivian-Agent 自動同步"; echo "$CRON_JOB_1"; echo "$CRON_JOB_2") | crontab -
    echo -e "${GREEN}✓ 已設定每日 09:00 & 18:00 自動同步${NC}"
fi

# 6. 提醒補上 .env
echo ""
echo "=============================="
echo -e "${YELLOW}⚠ 最後一步（手動）${NC}"
echo "=============================="
echo ""
echo "請在以下位置建立 .env 檔案（含你的 API Key）："
echo "  $INSTALL_DIR/.env"
echo ""
echo "範例格式："
echo "  PEXELS_API_KEY=你的金鑰"
echo ""
echo -e "${GREEN}✅ 安裝完成！${NC}"
echo ""
