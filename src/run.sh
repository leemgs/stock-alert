#!/usr/bin/env bash
set -euo pipefail
/opt/stock_alert/venv/bin/python /opt/stock_alert/multi_stock_alert.py >> /opt/stock_alert/stock_alert.log 2>&1
