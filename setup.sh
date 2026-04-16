#!/bin/bash
set -e
echo "=== Happy Vision Setup ==="
python3 --version || { echo "Python 3.10+ required"; exit 1; }
if ! command -v exiftool &> /dev/null; then
    echo "Installing exiftool..."
    brew install exiftool
fi
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
echo "=== Setup complete ==="
echo "Activate venv: source .venv/bin/activate"
