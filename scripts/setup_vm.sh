#!/usr/bin/env bash
set -euo pipefail

# Usage: sudo ./scripts/setup_vm.sh <username>
# Installs system deps, creates venv in user's repo dir, installs python deps and Playwright browsers.

USER_NAME="${1:-serveradmin}"
REPO_DIR="/home/${USER_NAME}/Tradingview-Pine-Script-Downloader"

if [ "$EUID" -ne 0 ]; then
  echo "This script must be run as root (it will install system packages and run user steps)."
  echo "Usage: sudo $0 <username>"
  exit 1
fi

echo "Installing system packages needed for Playwright..."
apt update
apt install -y python3-venv python3-dev build-essential curl gnupg ca-certificates \
  libnss3 libatk-bridge2.0-0 libx11-xcb1 libxcomposite1 libasound2 libxrandr2 libgtk-3-0 libgbm1 libxss1 libxshmfence1 fonts-liberation libpangocairo-1.0-0 libcups2 libdrm2

if [ ! -d "$REPO_DIR" ]; then
  echo "Repository directory $REPO_DIR not found. Make sure you cloned the repo into the user's home dir."
  exit 1
fi

# Create virtualenv and install python deps as the target user
echo "Creating virtualenv and installing python deps as $USER_NAME..."
su - "$USER_NAME" -c "bash -lc 'cd \"$REPO_DIR\" && python3 -m venv .venv && . .venv/bin/activate && python -m pip install --upgrade pip setuptools wheel && pip install -r requirements.txt'"

# Install Playwright browsers (as the target user)
echo "Installing Playwright browsers (this can take a while)..."
su - "$USER_NAME" -c "bash -lc 'cd \"$REPO_DIR\" && . .venv/bin/activate && python -m playwright install --with-deps --force'"

echo "Setup complete. You can now run:"
echo "  sudo -u $USER_NAME -i bash -lc 'cd $REPO_DIR && ./scripts/run_download.sh --url <URL> --max-pages 5'"

exit 0
