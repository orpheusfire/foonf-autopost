#!/bin/sh
# Install a LaunchAgent that publishes the next approved queue.json entry (post.py --next --live)
# every Tuesday and Friday at 10:00. Each run posts at most one poster and marks it "posted".
# If the Mac is asleep at 10:00, launchd runs the job when it wakes.
# Pause/uninstall: launchctl bootout gui/$(id -u)/com.foonf.ig-post && rm ~/Library/LaunchAgents/com.foonf.ig-post.plist
# Change the schedule: edit the StartCalendarInterval entries below (Weekday 0=Sun ... 6=Sat), then re-run this script.
set -e
LABEL=com.foonf.ig-post
DIR="$(cd "$(dirname "$0")" && pwd)"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
LOGDIR="$HOME/Library/Logs/foonf-autopost"
mkdir -p "$LOGDIR" "$HOME/Library/LaunchAgents"

cat > "$PLIST" <<PLISTEOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>$LABEL</string>
  <key>ProgramArguments</key>
  <array>
    <string>/usr/bin/python3</string>
    <string>$DIR/post.py</string>
    <string>--next</string>
    <string>--live</string>
  </array>
  <key>WorkingDirectory</key><string>$DIR</string>
  <key>EnvironmentVariables</key>
  <dict><key>PATH</key><string>$HOME/.local/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin</string></dict>
  <key>StartCalendarInterval</key>
  <array>
    <dict><key>Weekday</key><integer>2</integer><key>Hour</key><integer>10</integer><key>Minute</key><integer>0</integer></dict>
    <dict><key>Weekday</key><integer>5</integer><key>Hour</key><integer>10</integer><key>Minute</key><integer>0</integer></dict>
  </array>
  <key>StandardOutPath</key><string>$LOGDIR/post.log</string>
  <key>StandardErrorPath</key><string>$LOGDIR/post.log</string>
</dict>
</plist>
PLISTEOF

plutil -lint "$PLIST"
launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" "$PLIST"
echo "Installed $PLIST (Tue + Fri 10:00; logs: $LOGDIR/post.log)"
