#!/bin/sh
# Install a LaunchAgent that runs refresh_token.py --if-due daily at 10:00.
# The script itself only refreshes once 45 days have passed since the last refresh.
# Uninstall: launchctl bootout gui/$(id -u)/com.foonf.ig-token-refresh && rm ~/Library/LaunchAgents/com.foonf.ig-token-refresh.plist
set -e
LABEL=com.foonf.ig-token-refresh
DIR="$(cd "$(dirname "$0")" && pwd)"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
LOGDIR="$HOME/Library/Logs/foonf-autopost"
mkdir -p "$LOGDIR" "$HOME/Library/LaunchAgents"

cat > "$PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>$LABEL</string>
  <key>ProgramArguments</key>
  <array>
    <string>/usr/bin/python3</string>
    <string>$DIR/refresh_token.py</string>
    <string>--if-due</string>
  </array>
  <key>WorkingDirectory</key><string>$DIR</string>
  <key>StartCalendarInterval</key>
  <dict><key>Hour</key><integer>10</integer><key>Minute</key><integer>0</integer></dict>
  <key>StandardOutPath</key><string>$LOGDIR/refresh.log</string>
  <key>StandardErrorPath</key><string>$LOGDIR/refresh.log</string>
</dict>
</plist>
EOF

launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" "$PLIST"
echo "Installed $PLIST (logs: $LOGDIR/refresh.log)"
