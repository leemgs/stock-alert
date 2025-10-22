
---

# 📈 Stock Alert – Multi-Market Price Monitor

**자동 주식 임계가(상한/하한) 감시 및 이메일·Slack 알림 시스템**

본 프로젝트는

* 국내(KOSPI/KOSDAQ) 및 해외(NASDAQ/NYSE/HK/VN 등) 주요 종목의 실시간 가격을 감시하고,
* 지정된 임계값(`price_down`, `price_up`)을 넘거나 내려갈 때
  **자동으로 이메일과 Slack 채널로 알림**을 전송합니다.
* 또한 **주간 리포트** 및 **GitHub Actions 기반 서버리스 실행**을 지원합니다.

---

## 🚀 주요 기능

| 기능                     | 설명                                                   |
| ---------------------- | ---------------------------------------------------- |
| **가격 모니터링**            | Yahoo Finance API(`yfinance`)를 통해 종목별 실시간 시세 수집      |
| **임계가 알림**             | 하한(`price_down`) 이하 또는 상한(`price_up`) 이상일 때 메일/슬랙 발송 |
| **Rate-Limit 제어**      | 하루 종목당 최대 알림 횟수, 최소 알림 간격, 글로벌 알림 캡 제한               |
| **Slack 분기 채널 지원**     | 상승 시 `#wins`, 하락 시 `#risk` 등 별도 채널로 전송 가능            |
| **주간 리포트**             | 주 1회 Slack 리포트 자동 발송 (지난 7일 상/하한 기록 요약)              |
| **장중 실행 제한**           | 장중(예: 09:00~15:30) 시간대만 알림 수행                        |
| **GitHub Actions 자동화** | 별도 서버 없이 1시간마다/주 1회 GitHub Actions로 자동 실행 가능         |

---

## 📦 프로젝트 구조

```
stock-alert/
├── LICENSE
├── README.md
├── requirements.txt
├── examples/
│   ├── config.txt
│   └── stock.txt
├── src/
│   ├── multi_stock_alert.py
│   ├── weekly_report.py
│   └── run.sh
└── .github/
    └── workflows/
        ├── alerts.yml     # 2시간마다 자동 알림
        └── weekly.yml     # 주간 리포트
```

---

## ⚙️ 설치 및 실행 (로컬 / 서버 환경)

```bash
# 1. 의존성 설치
pip install -r requirements.txt

# 2. 설정 파일 작성
vi /opt/stock_alert/config.txt
vi /opt/stock_alert/stock.txt

# 3. 테스트 실행
python src/multi_stock_alert.py

# 4. 크론 등록 (1시간마다)
0 */1 * * * /opt/stock_alert/run.sh
```

---

## 📄 예시 설정

### `stock.txt`

```csv
loc, company_name, ticker, price_down, price_up
국내, Samsung Electronics, 005930.KS, 60000, 90000
국내, SK hynix, 000660.KS, 140000, 220000
미국, Nvidia, NVDA, 400, 1200
미국, Tesla, TSLA, 150, 350
```

### `config.txt`

```ini
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USER=your_email@gmail.com
SMTP_PASS=your_app_password
EMAIL_FROM=Stock Alert <your_email@gmail.com>
EMAIL_TO=your_email@gmail.com

SLACK_ENABLE=true
SLACK_SPLIT_CHANNELS=true
SLACK_WEBHOOK_DOWN=https://hooks.slack.com/services/XXXX/XXXX/risk
SLACK_WEBHOOK_UP=https://hooks.slack.com/services/XXXX/XXXX/wins
SLACK_WEBHOOK_REPORT=https://hooks.slack.com/services/XXXX/XXXX/report

ALERT_RATE_LIMIT_PER_TICKER_PER_DAY=2
ALERT_MIN_INTERVAL_MINUTES=60
ALERT_GLOBAL_DAILY_CAP=100

ACTIVE_WINDOW_ENABLE=true
ACTIVE_BUSINESS_DAYS_ONLY=true
ACTIVE_START=09:00
ACTIVE_END=15:30
```

---

## ☁️ GitHub Actions 서버리스 자동화

이 프로젝트는 별도 서버 없이 GitHub Actions로 자동 실행할 수 있습니다.
레포에 포함된 워크플로 파일:

* `.github/workflows/alerts.yml` → **1시간마다 자동 알림**
* `.github/workflows/weekly.yml` → **매주 일요일 18:00 KST 주간 리포트**

### 1️⃣ Secrets 등록 (Settings → Secrets → Actions)

| Key                                                             | 설명                   |
| --------------------------------------------------------------- | -------------------- |
| SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASS                      | 이메일 발송용 SMTP 설정      |
| EMAIL_FROM, EMAIL_TO                                            | 발신자/수신자 이메일          |
| SLACK_ENABLE, SLACK_WEBHOOK_URL                                 | Slack 사용 여부 및 웹훅 URL |
| SLACK_SPLIT_CHANNELS, SLACK_WEBHOOK_DOWN, SLACK_WEBHOOK_UP      | 상승/하락 채널 분리 설정       |
| SLACK_WEBHOOK_REPORT                                            | 주간 리포트 전송용           |
| ALERT_RATE_LIMIT_PER_TICKER_PER_DAY, ALERT_MIN_INTERVAL_MINUTES | 알림 rate-limit 제어     |
| TZ, ACTIVE_WINDOW_ENABLE, ACTIVE_START, ACTIVE_END              | 시간대 및 장중 필터          |

### 2️⃣ 워크플로 실행 확인

```bash
# 수동 트리거
gh workflow run "Stock Alerts (1-hour)"
gh workflow run "Weekly Stock Report"
```

### 3️⃣ 실행 주기 (UTC 기준)

* 알림: `0 */1 * * *` → 1시간마다
* 리포트: `0 9 * * 0` → 일요일 18:00 (KST)

---

## 📊 알림 예시

### 이메일

```
Subject: [Stock Alert] 임계 도달 종목 (상/하한)
시각: 2025-10-21 18:00:00 KST

[하한 돌파]
- Samsung Electronics (005930.KS): 59,500 ≤ 60,000

[상한 돌파]
- SK hynix (000660.KS): 220,500 ≥ 220,000
```

### Slack (#wins)

> :small_red_triangle: **상한 돌파**
>
> * *Nvidia* `NVDA`: `1250 ≥ 1200`

### Slack (#risk)

> :small_red_triangle_down: **하한 돌파**
>
> * *KakaoBank* `323410.KS`: `23,800 ≤ 25,000`

---

## 📆 주간 리포트 예시

```
[Weekly Summary]
기간: 2025-10-13 ~ 2025-10-20

상한 돌파 7건 / 하한 돌파 5건

Top 3 상승:
1. Nvidia +8.2%
2. Samsung Electronics +5.1%
3. SK hynix +4.3%

Top 3 하락:
1. KakaoBank -6.0%
2. Jeju Air -5.7%
3. Tesla -5.3%
```

---

## 🧩 GitHub Actions YAML

| 파일명                            | 설명                                          |
| ------------------------------ | ------------------------------------------- |
| `.github/workflows/alerts.yml` | 1시간마다 주식 가격 알림 실행                           |
| `.github/workflows/weekly.yml` | 매주 일요일 18시(KST) 주간 리포트 생성                   |
| **GitHub Secrets**             | 민감정보(SMTP, Slack Webhook 등)는 Secrets를 통해 주입 |

> Actions 러너는 매 실행마다 초기화되므로,
> `history.json` 보존에는 `actions/cache` 또는 외부 스토리지(S3, Redis 등) 연동을 권장합니다.

---

## ⚖️ License

This project is licensed under the **Apache License 2.0**.
See the [LICENSE](./LICENSE) file for details.

---

## 🤝 Contributing

PR 환영합니다.

* 코드 포맷: **PEP8**
* 커밋 컨벤션: `feat:`, `fix:`, `ci:`, `docs:`, `chore:` 등
* 테스트 커맨드: `pytest -v`

---

## 🧠 Credits

* Developed by [Geunsik Lim](https://github.com/leemgs)
* Powered by **Python 3.11 + GitHub Actions + Yahoo Finance API**

---
