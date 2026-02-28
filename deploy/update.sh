#!/usr/bin/env bash
# SnapClaw — update script (run on your EC2 instance to pull latest code)
# Usage: sudo /opt/snapclaw/deploy/update.sh

set -euo pipefail
INSTALL_DIR="/opt/snapclaw"
APP_USER="snapclaw"

echo "Pulling latest code..."
git -C "$INSTALL_DIR" pull origin main

echo "Updating dependencies..."
sudo -u "$APP_USER" "$INSTALL_DIR/venv/bin/pip" install --quiet -r "$INSTALL_DIR/backend/requirements.txt"

echo "Restarting service..."
systemctl restart snapclaw
sleep 2
systemctl is-active snapclaw && echo "✅ SnapClaw updated and running" || echo "❌ Service failed — check: journalctl -u snapclaw"
