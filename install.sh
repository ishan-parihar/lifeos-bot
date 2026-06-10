#!/usr/bin/env bash
set -euo pipefail

# ──────────────────────────────────────────────────────────────────────────────
# LifeOS Bot — Installer
# Sets up venv, dependencies, systemd service, log directory, and management CLI
# ──────────────────────────────────────────────────────────────────────────────

BOT_NAME="lifeos-bot"
BOT_DIR="$(cd "$(dirname "$0")" && pwd)"
VENV_DIR="$BOT_DIR/.venv"
SERVICE_FILE="/etc/systemd/system/${BOT_NAME}.service"
LOG_DIR="/var/log/${BOT_NAME}"
CACHE_DIR="$HOME/.cache/lifeos_bot"
PYTHON="python3"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

info()  { echo -e "${GREEN}[INFO]${NC}  $*"; }
warn()  { echo -e "${YELLOW}[WARN]${NC}  $*"; }
error() { echo -e "${RED}[ERROR]${NC} $*"; exit 1; }

# ── Pre-flight checks ────────────────────────────────────────────────────────

command -v $PYTHON >/dev/null 2>&1 || error "Python3 not found. Install python3 first."

if [ ! -f "$BOT_DIR/.env" ]; then
    error ".env file not found at $BOT_DIR/.env"
fi

# ── Virtual environment ──────────────────────────────────────────────────────

if [ ! -d "$VENV_DIR" ]; then
    info "Creating virtual environment..."
    $PYTHON -m venv "$VENV_DIR"
fi

info "Installing dependencies..."
"$VENV_DIR/bin/pip" install --upgrade pip -q
"$VENV_DIR/bin/pip" install -r "$BOT_DIR/requirements.txt" -q
info "Dependencies installed."

# ── Log directory ────────────────────────────────────────────────────────────

if [ ! -d "$LOG_DIR" ]; then
    info "Creating log directory at $LOG_DIR (requires sudo)..."
    sudo mkdir -p "$LOG_DIR"
    sudo chown "$USER:$USER" "$LOG_DIR"
fi

# ── Cache directory ──────────────────────────────────────────────────────────

mkdir -p "$CACHE_DIR"

# ── Validate configuration ───────────────────────────────────────────────────

info "Validating configuration..."
"$VENV_DIR/bin/python" -c "
import sys; sys.path.insert(0, '$BOT_DIR')
from config import settings
issues = []
if not settings.TELEGRAM_BOT_TOKEN:
    issues.append('TELEGRAM_BOT_TOKEN is empty')
if not settings.NOTION_API_KEY:
    issues.append('NOTION_API_KEY is empty')
if issues:
    for i in issues: print(f'  FAIL: {i}')
    sys.exit(1)
print('  TELEGRAM_BOT_TOKEN: OK')
print('  NOTION_API_KEY: OK')
print('  Configuration valid.')
"

# ── Systemd service ──────────────────────────────────────────────────────────

info "Installing systemd service..."

sudo tee "$SERVICE_FILE" > /dev/null << EOF
[Unit]
Description=LifeOS Telegram Bot
After=network-online.target
Wants=network-online.target
StartLimitIntervalSec=300
StartLimitBurst=5

[Service]
Type=simple
User=$USER
Group=$USER
WorkingDirectory=$BOT_DIR
ExecStart=$VENV_DIR/bin/python $BOT_DIR/run.py
Restart=on-failure
RestartSec=10

# Logging
StandardOutput=append:$LOG_DIR/bot.log
StandardError=append:$LOG_DIR/bot.log

# Environment
EnvironmentFile=$BOT_DIR/.env

# Hardening (light — ProtectSystem=strict causes path issues)
NoNewPrivileges=true

# Resource limits
MemoryMax=512M

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable "$SERVICE_FILE" 2>/dev/null || true
info "Systemd service installed and enabled: $SERVICE_FILE"

# ── Management script ────────────────────────────────────────────────────────

info "Creating management script..."
cat > "$BOT_DIR/lifeos" << 'MANEOF'
#!/usr/bin/env bash
set -euo pipefail

BOT_NAME="lifeos-bot"
SERVICE="$BOT_NAME.service"

case "${1:-help}" in
    start)
        echo "Starting $BOT_NAME..."
        sudo systemctl start "$SERVICE"
        sleep 2
        sudo systemctl status "$SERVICE" --no-pager -l
        ;;
    stop)
        echo "Stopping $BOT_NAME..."
        sudo systemctl stop "$SERVICE"
        echo "Stopped."
        ;;
    restart)
        echo "Restarting $BOT_NAME..."
        sudo systemctl restart "$SERVICE"
        sleep 2
        sudo systemctl status "$SERVICE" --no-pager -l
        ;;
    status)
        sudo systemctl status "$SERVICE" --no-pager -l
        ;;
    logs)
        shift
        if [ "${1:-}" = "-f" ]; then
            tail -f /var/log/$BOT_NAME/bot.log
        else
            tail -n "${1:-50}" /var/log/$BOT_NAME/bot.log
        fi
        ;;
    errors)
        grep -i "error\|exception\|traceback" /var/log/$BOT_NAME/bot.log | tail -n "${1:-20}"
        ;;
    enable)
        sudo systemctl enable "$SERVICE"
        echo "Enabled on boot."
        ;;
    disable)
        sudo systemctl disable "$SERVICE"
        echo "Disabled on boot."
        ;;
    debug)
        echo "Running in foreground (Ctrl+C to stop)..."
        cd "$(dirname "$0")"
        .venv/bin/python run.py
        ;;
    health)
        echo "=== Service Status ==="
        sudo systemctl is-active "$SERVICE" && echo "ACTIVE" || echo "INACTIVE"
        echo ""
        echo "=== Last 5 Log Lines ==="
        tail -5 /var/log/$BOT_NAME/bot.log 2>/dev/null || echo "No logs yet"
        echo ""
        echo "=== Disk Usage ==="
        du -sh /var/log/$BOT_NAME/ 2>/dev/null || echo "No log dir"
        du -sh ~/.cache/lifeos_bot/ 2>/dev/null || echo "No cache dir"
        echo ""
        echo "=== Process ==="
        pgrep -af "run.py" || echo "No process running"
        ;;
    help|*)
        cat << EOF
LifeOS Bot Management

Usage: ./lifeos <command>

Commands:
    start       Start the bot service
    stop        Stop the bot service
    restart     Restart the bot service
    status      Show service status
    logs [N]    Show last N log lines (default 50)
    logs -f     Follow logs in real-time
    errors [N]  Show last N error lines
    enable      Enable on boot
    disable     Disable on boot
    debug       Run in foreground (for debugging)
    health      Quick health check
    help        Show this help
EOF
        ;;
esac
MANEOF

chmod +x "$BOT_DIR/lifeos"

# ── Log rotation ─────────────────────────────────────────────────────────────

info "Setting up log rotation..."
sudo tee /etc/logrotate.d/$BOT_NAME > /dev/null << EOF
/var/log/$BOT_NAME/*.log {
    daily
    rotate 14
    compress
    delaycompress
    missingok
    notifempty
    create 0644 $USER $USER
    copytruncate
    maxsize 50M
}
EOF

# ── Done ─────────────────────────────────────────────────────────────────────

echo ""
info "Installation complete!"
echo ""
echo "  Management:  ./lifeos <command>"
echo ""
echo "  Quick start:"
echo "    ./lifeos start      # Start as systemd service"
echo "    ./lifeos logs -f    # Follow live logs"
echo "    ./lifeos health     # Quick health check"
echo "    ./lifeos debug      # Run in foreground"
echo ""
echo "  The bot auto-discovers Notion database IDs on first start."
echo "  Logs: /var/log/$BOT_NAME/bot.log"
echo ""
