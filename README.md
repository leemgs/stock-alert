# stock-alert

Email + Slack alerts when stock prices cross configured thresholds (both **down** and **up**).
Supports:
- Multiple tickers via `stock.txt`
- Min/Max thresholds: `price_down` and `price_up`
- Daily de-duplication and **rate-limits**
- Slack split channels (#risk for down, #wins for up) via separate incoming webhooks
- Trading-hour window (active window filter)
- **Weekly Report** (email + Slack) aggregating the last 7 days
- Apache-2.0 licensed

## Project Layout
```
stock-alert/
  ├─ LICENSE
  ├─ README.md
  ├─ requirements.txt
  ├─ examples/
  │   ├─ config.txt
  │   └─ stock.txt
  └─ src/
      ├─ multi_stock_alert.py
      ├─ weekly_report.py
      └─ run.sh
```

## Quick Start (Ubuntu 24.04)

```bash
sudo apt update
sudo apt install -y python3-venv

# project path (adjust as you like)
sudo mkdir -p /opt/stock_alert
sudo chown $USER:$USER /opt/stock_alert
cd /opt/stock_alert

python3 -m venv venv
./venv/bin/pip install --upgrade pip
./venv/bin/pip install -r /path/to/requirements.txt
```

Copy files:

```bash
# assuming you cloned this repo to ~/stock-alert
cp -r ~/stock-alert/src/* /opt/stock_alert/
mkdir -p /opt/stock_alert/examples
cp ~/stock-alert/examples/* /opt/stock_alert/
```

Edit `config.txt` and `stock.txt` under `/opt/stock_alert/`.

Make scripts executable:

```bash
chmod +x /opt/stock_alert/run.sh
chmod +x /opt/stock_alert/multi_stock_alert.py
chmod +x /opt/stock_alert/weekly_report.py
```

### Cron

Run alerts every 2 hours:

```bash
crontab -e
# add:
0 */2 * * * /opt/stock_alert/run.sh
```

Weekly report every Sunday 18:00 (KST):

```bash
crontab -e
# add:
0 18 * * 0 /opt/stock_alert/venv/bin/python /opt/stock_alert/weekly_report.py >> /opt/stock_alert/stock_alert.log 2>&1
```

## Configuration

See `examples/config.txt`. Key highlights:

- **SMTP**: `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASS`, `EMAIL_FROM`, `EMAIL_TO`
- **Slack**: `SLACK_ENABLE=true`, `SLACK_WEBHOOK_URL`, or split: `SLACK_WEBHOOK_DOWN`, `SLACK_WEBHOOK_UP`, `SLACK_SPLIT_CHANNELS=true`
- **Active Window**: enable `ACTIVE_WINDOW_ENABLE=true`, `ACTIVE_START/END` and weekday filter
- **Rate Limits**:
  - `ALERT_RATE_LIMIT_PER_TICKER_PER_DAY` (e.g., 2)
  - `ALERT_MIN_INTERVAL_MINUTES` (e.g., 60)
  - `ALERT_GLOBAL_DAILY_CAP`

## Stock List Format (`stock.txt`)

CSV with 5 columns: `loc, company_name, ticker, price_down, price_up`
- leave `price_down` or `price_up` empty to ignore that side
- currency must match the ticker's exchange currency (KRW for KRX `.KS`/`.KQ`, USD for US)

Example provided in `examples/stock.txt`.

## Security

- Use **app passwords** for SMTP where possible.
- Restrict config file permissions: `chmod 600 config.txt`.
- Slack incoming webhooks grant post rights to the chosen channel; treat them as secrets.

## License

Apache License 2.0. See `LICENSE` for details.
