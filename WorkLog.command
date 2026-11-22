#!/bin/sh
# macOS: double-click in Finder to start WorkLog (opens a Terminal window alongside).
# For a Dock icon without the Terminal window, run ./install-launcher.sh once instead.
exec "$(dirname "$0")/run.sh"
