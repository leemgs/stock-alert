#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
python3 src/multi_stock_alert.py >> data/stock_alert.log 2>&1
