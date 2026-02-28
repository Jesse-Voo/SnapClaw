#!/usr/bin/env bash
# SnapClaw — AWS EC2 / Ubuntu 22.04 / 24.04 bootstrap script
# Tested on: t2.micro, t3.micro (AWS Free Tier)
#
# Usage (as root or with sudo):
#   curl -fsSL https://raw.githubusercontent.com/Jesse-Voo/SnapClaw/main/deploy/aws-ec2-setup.sh | sudo bash
#
# What this script does:
#   1. Installs system packages + Python 3.12 + nginx + certbot
#   2. Clones the SnapClaw repo
#   3. Installs Python dependencies in a virtual environment
#   4. Creates a systemd service (snapclaw.service)
#   5. Configures nginx as a reverse proxy
#   6. Opens firewall ports 80 and 443
#
# After running, edit /opt/snapclaw/backend/.env with your Supabase credentials
# then: sudo systemctl restart snapclaw

set -euo pipefail

# ── Config (edit before running if needed) ────────────────────────────────
REPO_URL="${REPO_URL:-https://github.com/Jesse-Voo/SnapClaw.git}"
BRANCH="${BRANCH:-main}"
INSTALL_DIR="/opt/snapclaw"
APP_USER="snapclaw"
APP_PORT="${APP_PORT:-8000}"
DOMAIN="${DOMAIN:-}"   # Set to your domain for SSL, e.g. api.snapbase-78mp9.ondigitalocean.app
# ──────────────────────────────────────────────────────────────────────────

log()  { echo -e "\033[1;32m[SnapClaw]\033[0m $*"; }
warn() { echo -e "\033[1;33m[WARN]\033[0m $*"; }
die()  { echo -e "\033[1;31m[ERROR]\033[0m $*" >&2; exit 1; }

[[ "$EUID" -eq 0 ]] || die "Run as root: sudo bash $0"

log "Updating system packages..."
apt-get update -q
apt-get upgrade -y -q

log "Installing dependencies..."
apt-get install -y -q \
    git curl wget unzip build-essential \
    python3.12 python3.12-venv python3.12-dev \
    libpq-dev libssl-dev libffi-dev \
    libjpeg-dev libpng-dev libwebp-dev \
    nginx certbot python3-certbot-nginx \
    ufw

log "Creating system user: $APP_USER"
id "$APP_USER" &>/dev/null || useradd --system --shell /bin/bash --home "$INSTALL_DIR" "$APP_USER"

log "Cloning repo to $INSTALL_DIR..."
if [[ -d "$INSTALL_DIR/.git" ]]; then
    git -C "$INSTALL_DIR" pull origin "$BRANCH"
else
    git clone --depth=1 --branch "$BRANCH" "$REPO_URL" "$INSTALL_DIR"
fi
chown -R "$APP_USER":"$APP_USER" "$INSTALL_DIR"

log "Setting up Python virtual environment..."
sudo -u "$APP_USER" python3.12 -m venv "$INSTALL_DIR/venv"
sudo -u "$APP_USER" "$INSTALL_DIR/venv/bin/pip" install --quiet --upgrade pip
sudo -u "$APP_USER" "$INSTALL_DIR/venv/bin/pip" install --quiet -r "$INSTALL_DIR/backend/requirements.txt"

log "Installing .env template..."
if [[ ! -f "$INSTALL_DIR/backend/.env" ]]; then
    cp "$INSTALL_DIR/backend/.env.example" "$INSTALL_DIR/backend/.env"
    chown "$APP_USER":"$APP_USER" "$INSTALL_DIR/backend/.env"
    chmod 600 "$INSTALL_DIR/backend/.env"
    warn "⚠️  Edit $INSTALL_DIR/backend/.env with your Supabase credentials!"
fi

log "Installing systemd service..."
cat > /etc/systemd/system/snapclaw.service <<SERVICE
[Unit]
Description=SnapClaw API
After=network.target

[Service]
Type=exec
User=${APP_USER}
Group=${APP_USER}
WorkingDirectory=${INSTALL_DIR}/backend
EnvironmentFile=${INSTALL_DIR}/backend/.env
ExecStart=${INSTALL_DIR}/venv/bin/uvicorn main:app --host 127.0.0.1 --port ${APP_PORT} --workers 2
Restart=on-failure
RestartSec=5
StandardOutput=journal
StandardError=journal
SyslogIdentifier=snapclaw

# Hardening
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ReadWritePaths=${INSTALL_DIR}

[Install]
WantedBy=multi-user.target
SERVICE

systemctl daemon-reload
systemctl enable snapclaw
systemctl restart snapclaw
sleep 2
systemctl is-active snapclaw && log "SnapClaw service running ✅" || warn "Service may have failed — check: journalctl -u snapclaw"

log "Configuring nginx..."
NGINX_CONF="/etc/nginx/sites-available/snapclaw"

if [[ -n "$DOMAIN" ]]; then
    SERVER_NAME="$DOMAIN"
else
    SERVER_NAME="_"
    warn "No DOMAIN set. Using catch-all nginx config. Set DOMAIN=yourdomain.com for SSL."
fi

cat > "$NGINX_CONF" <<NGINX
upstream snapclaw_api {
    server 127.0.0.1:${APP_PORT};
    keepalive 32;
}

server {
    listen 80;
    server_name ${SERVER_NAME};

    client_max_body_size 50M;

    # Security headers
    add_header X-Frame-Options DENY;
    add_header X-Content-Type-Options nosniff;
    add_header X-XSS-Protection "1; mode=block";
    add_header Referrer-Policy strict-origin-when-cross-origin;

    location / {
        proxy_pass         http://snapclaw_api;
        proxy_http_version 1.1;
        proxy_set_header   Host              \$host;
        proxy_set_header   X-Real-IP         \$remote_addr;
        proxy_set_header   X-Forwarded-For   \$proxy_add_x_forwarded_for;
        proxy_set_header   X-Forwarded-Proto \$scheme;
        proxy_set_header   Connection        "";
        proxy_read_timeout 60s;
        proxy_connect_timeout 10s;
    }

    location /health {
        proxy_pass http://snapclaw_api/health;
        access_log off;
    }
}
NGINX

ln -sf "$NGINX_CONF" /etc/nginx/sites-enabled/snapclaw
rm -f /etc/nginx/sites-enabled/default
nginx -t && systemctl reload nginx && log "nginx configured ✅"

if [[ -n "$DOMAIN" ]]; then
    log "Obtaining SSL certificate for $DOMAIN via Let's Encrypt..."
    certbot --nginx -d "$DOMAIN" --non-interactive --agree-tos -m "admin@${DOMAIN}" --redirect || \
        warn "certbot failed — run manually: sudo certbot --nginx -d $DOMAIN"
fi

log "Configuring UFW firewall..."
ufw allow OpenSSH
ufw allow "Nginx Full"
ufw --force enable
log "UFW enabled ✅"

IP=$(curl -s ifconfig.me 2>/dev/null || echo "unknown")

echo ""
echo "══════════════════════════════════════════════"
echo " SnapClaw installed successfully! 🎉"
echo "══════════════════════════════════════════════"
echo " Server  : http://${IP}"
if [[ -n "$DOMAIN" ]]; then
echo " Domain  : https://${DOMAIN}"
fi
echo " API docs: http://${IP}/docs"
echo ""
echo " Next steps:"
echo "   1. Edit /opt/snapclaw/backend/.env with your Supabase credentials"
echo "   2. sudo systemctl restart snapclaw"
echo "   3. Test: curl http://${IP}/health"
echo "══════════════════════════════════════════════"
