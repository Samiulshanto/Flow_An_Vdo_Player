#!/bin/bash

APP_DIR="$(cd "$(dirname "${BASH_SOURCE}")" && pwd)"
APP_SCRIPT="app.py"

cd "$APP_DIR" || exit 1

if [ -f "$APP_DIR/.venv/bin/python" ]; then
    "$APP_DIR/.venv/bin/python" "$APP_DIR/$APP_SCRIPT" "$@"
else
    echo "Error: Virtual environment (.venv) not found in $APP_DIR"
    exit 1
fi
