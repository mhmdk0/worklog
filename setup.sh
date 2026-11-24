#!/bin/sh
# Create .venv and install WorkLog's dependencies (Linux and macOS).
# Picks a Python 3.9+ with Tk 8.6 and, on Linux, smooth (Xft) fonts. Force a specific one with:
#   PYTHON=/path/to/python3 ./setup.sh
set -e
cd "$(dirname "$0")"

# Prints "Python <version> with Tk <version>" and exits 0 if this Python is usable,
# 2 if it works but draws pixelated text (Tk without Xft, e.g. Anaconda's), 1 otherwise.
check() {
    "$1" - <<'PYCHECK' 2>/dev/null
import sys
if sys.version_info < (3, 9):
    sys.exit(1)
try:
    import tkinter
except ImportError:
    sys.exit(1)
tk = tkinter.Tcl().eval("info patchlevel")
if tuple(int(p) for p in tk.split(".")[:2]) < (8, 6):
    sys.exit(1)
print(f"Python {sys.version.split()[0]} with Tk {tk}")
if sys.platform.startswith("linux"):
    # A Tk built with Xft (smooth fonts) loads libXft along with libtk.
    with open("/proc/self/maps") as maps:
        if "libXft" not in maps.read():
            sys.exit(2)
PYCHECK
}

if [ "$(uname -s)" = Darwin ]; then
    CANDIDATES="/Library/Frameworks/Python.framework/Versions/Current/bin/python3 /opt/homebrew/bin/python3
                /usr/local/bin/python3 python3"
else
    CANDIDATES="/usr/bin/python3 /usr/local/bin/python3 python3"
fi
[ -n "$PYTHON" ] && CANDIDATES=$PYTHON

PY=
for c in $CANDIDATES; do
    command -v "$c" >/dev/null 2>&1 || continue
    if out=$(check "$c"); then
        PY=$c info=$out
        break
    elif [ $? -eq 2 ] && [ -z "$PIXELATED" ]; then
        PIXELATED=$c pixelated_info=$out
    fi
done

if [ -z "$PY" ] && [ -n "$PIXELATED" ]; then
    PY=$PIXELATED info=$pixelated_info
    echo "Warning: $PY can't draw smooth fonts (its Tk has no Xft; Anaconda's Python is like this)," >&2
    echo "so the app's text will look pixelated. For smooth text, install the system Python's Tk and" >&2
    echo "run ./setup.sh again:  sudo apt install python3-tk python3-venv   (Fedora: python3-tkinter)" >&2
    echo >&2
fi
if [ -z "$PY" ]; then
    echo "No usable Python found: WorkLog needs Python 3.9+ with Tk 8.6." >&2
    if [ "$(uname -s)" = Darwin ]; then
        echo "Install Python from https://www.python.org/downloads/macos/ (or: brew install python python-tk)." >&2
    else
        echo "On Ubuntu/Debian: sudo apt install python3-tk python3-venv   (Fedora: python3-tkinter)" >&2
    fi
    exit 1
fi
echo "Using $info: $(command -v "$PY")"

if ! "$PY" -m venv --clear .venv >/dev/null 2>&1; then
    # Ubuntu/Debian leave pip out of venvs unless python3-venv is installed: borrow pip from
    # another Python (e.g. Anaconda's) to install it.
    "$PY" -m venv --clear --without-pip .venv
    for c in python3 python /usr/local/bin/python3; do
        command -v "$c" >/dev/null 2>&1 || continue
        if "$c" -m pip --python .venv/bin/python install --quiet pip >/dev/null 2>&1; then
            break
        fi
    done
    if ! .venv/bin/python -m pip --version >/dev/null 2>&1; then
        echo "Couldn't create the virtual environment. On Ubuntu/Debian: sudo apt install python3-venv" >&2
        exit 1
    fi
fi
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -r requirements.txt
echo
echo "Done. Start WorkLog with ./run.sh, or run ./install-launcher.sh to add it to your apps."
