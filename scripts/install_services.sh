#!/bin/zsh
# Installs the background services as launchd user agents:
#   com.ninad.tradebot            → `tradebot daemon`     (workers + scheduler)
#   com.ninad.tradebot.dashboard  → `tradebot dashboard`  (web page on localhost:8090)
# Both start at login (RunAtLoad), restart if they exit (KeepAlive) and log to logs/<name>.{out,err}.
# PostgreSQL is managed separately by `brew services` (also starts at login).
set -euo pipefail
ROOT="${0:A:h:h}"
mkdir -p "$ROOT/logs" "$HOME/Library/LaunchAgents"

install_agent() {
  local LABEL="$1" CMD="$2" LOG="$3"
  local PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
  cat > "$PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>$LABEL</string>
  <key>ProgramArguments</key>
  <array><string>$ROOT/.venv/bin/tradebot</string><string>$CMD</string></array>
  <key>WorkingDirectory</key><string>$ROOT</string>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>ThrottleInterval</key><integer>30</integer>
  <key>ProcessType</key><string>Background</string>
  <key>EnvironmentVariables</key>
  <dict><key>PATH</key><string>/opt/homebrew/opt/postgresql@17/bin:/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin</string></dict>
  <key>StandardOutPath</key><string>$ROOT/logs/$LOG.out</string>
  <key>StandardErrorPath</key><string>$ROOT/logs/$LOG.err</string>
</dict>
</plist>
EOF
  launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
  launchctl bootstrap "gui/$(id -u)" "$PLIST"
  echo "installed $LABEL → $PLIST"
}

if [[ "${1:-all}" == "all" || "${1:-}" == "daemon" ]]; then
  install_agent com.ninad.tradebot daemon daemon
fi
if [[ "${1:-all}" == "all" || "${1:-}" == "dashboard" ]]; then
  install_agent com.ninad.tradebot.dashboard dashboard dashboard
fi
