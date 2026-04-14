#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

# Create venv if missing
if [ ! -d .venv ]; then
  python3 -m venv .venv
fi

# Activate
# shellcheck disable=SC1091
. .venv/bin/activate

pip install --upgrade pip
pip install -r requirements.txt
python -m playwright install chromium

# Run script with any user args forwarded
python double_ip.py "$@"
