#!/bin/sh
# Add WorkLog to your apps.
#   Linux: an app-grid / menu entry you can pin to the dock.
#   macOS: ~/Applications/WorkLog.app, which shows up in Launchpad and can be kept in the Dock.
# Run it again if you move this folder.
set -e
DIR=$(cd "$(dirname "$0")" && pwd)
if [ ! -x "$DIR/.venv/bin/python" ]; then
    echo "Run ./setup.sh first." >&2
    exit 1
fi

case "$(uname -s)" in
Darwin)
    APP="$HOME/Applications/WorkLog.app"
    rm -rf "$APP"
    mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"
    cat > "$APP/Contents/MacOS/WorkLog" <<EOF
#!/bin/sh
exec "$DIR/.venv/bin/python" "$DIR/app.py"
EOF
    chmod +x "$APP/Contents/MacOS/WorkLog"
    cat > "$APP/Contents/Info.plist" <<'EOF'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>CFBundleName</key><string>WorkLog</string>
    <key>CFBundleDisplayName</key><string>WorkLog</string>
    <key>CFBundleIdentifier</key><string>local.worklog</string>
    <key>CFBundleExecutable</key><string>WorkLog</string>
    <key>CFBundleIconFile</key><string>WorkLog</string>
    <key>CFBundlePackageType</key><string>APPL</string>
    <key>CFBundleShortVersionString</key><string>1.0</string>
    <key>NSHighResolutionCapable</key><true/>
</dict>
</plist>
EOF
    ICONSET="$(mktemp -d)/WorkLog.iconset"
    mkdir -p "$ICONSET"
    for s in 16 32 128 256; do
        sips -z $s $s "$DIR/assets/worklog.png" --out "$ICONSET/icon_${s}x${s}.png" >/dev/null
        sips -z $((s * 2)) $((s * 2)) "$DIR/assets/worklog.png" --out "$ICONSET/icon_${s}x${s}@2x.png" >/dev/null
    done
    iconutil -c icns "$ICONSET" -o "$APP/Contents/Resources/WorkLog.icns"
    rm -rf "$(dirname "$ICONSET")"
    touch "$APP"
    echo "Installed $APP"
    echo "Open it from Launchpad or Finder. To pin it: right-click its Dock icon > Options > Keep in Dock."
    ;;
*)
    APPS="${XDG_DATA_HOME:-$HOME/.local/share}/applications"
    mkdir -p "$APPS"
    cat > "$APPS/worklog.desktop" <<EOF
[Desktop Entry]
Type=Application
Version=1.0
Name=WorkLog
GenericName=Time Tracker
Comment=Track working hours and generate monthly reports and invoices
Exec="$DIR/run.sh"
Icon=$DIR/assets/worklog.png
Terminal=false
Categories=Office;
Keywords=hours;time;invoice;report;timesheet;
StartupWMClass=Worklog
StartupNotify=true
EOF
    command -v update-desktop-database >/dev/null && update-desktop-database "$APPS" 2>/dev/null || true
    echo "Installed $APPS/worklog.desktop"
    echo "Find WorkLog in your app grid; right-click it while running to pin it to the dock."
    ;;
esac
