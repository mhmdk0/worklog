#!/bin/sh
# Start WorkLog with the project's virtual environment (Linux and macOS).
cd "$(dirname "$0")" || exit 1
if [ ! -x .venv/bin/python ]; then
    echo "WorkLog isn't set up yet: run ./setup.sh first." >&2
    exit 1
fi
exec .venv/bin/python app.py "$@"
