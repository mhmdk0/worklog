#!/bin/sh
# Create .venv and install WorkLog's dependencies (Linux and macOS).
# Uses python3 from PATH; pick another one with:  PYTHON=/path/to/python3 ./setup.sh
set -e
cd "$(dirname "$0")"
PY=${PYTHON:-python3}

if ! "$PY" - <<'PYCHECK'
import sys
if sys.version_info < (3, 9):
    sys.exit(f"WorkLog needs Python 3.9 or newer; {sys.executable} is {sys.version.split()[0]}.")
try:
    import tkinter
except ImportError:
    sys.exit("This Python has no tkinter (Tk). On Ubuntu/Debian: sudo apt install python3-tk. "
             "With Homebrew on macOS: brew install python-tk.")
tk = tkinter.Tcl().eval("info patchlevel")
if tuple(int(p) for p in tk.split(".")[:2]) < (8, 6):
    sys.exit(f"This Python uses Tk {tk}, which is too old (8.6+ needed). On macOS, install Python from "
             "https://www.python.org/downloads/ (or Homebrew's python + python-tk), then run "
             "PYTHON=/usr/local/bin/python3 ./setup.sh")
print(f"Using Python {sys.version.split()[0]} with Tk {tk}: {sys.executable}")
if sys.platform.startswith("linux"):
    try:
        root = tkinter.Tk()
        root.withdraw()
        try:
            fonts = root.tk.eval("::tk::pkgconfig get fontsystem")
        except tkinter.TclError:
            fonts = ""
        root.destroy()
        if fonts != "xft":
            print("Warning: this Tk can't draw smooth fonts (no Xft), so the app will look pixelated. "
                  "Anaconda's Python does this; use the system one: PYTHON=/usr/bin/python3 ./setup.sh")
    except tkinter.TclError:
        pass  # no display to check with
PYCHECK
then
    exit 1
fi

if ! "$PY" -m venv .venv; then
    echo "Couldn't create the virtual environment. On Ubuntu/Debian: sudo apt install python3-venv" >&2
    exit 1
fi
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -r requirements.txt
echo
echo "Done. Start WorkLog with ./run.sh, or run ./install-launcher.sh to add it to your apps."
