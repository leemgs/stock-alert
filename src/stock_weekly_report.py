import os
import sys
import smtplib
import ssl
from pathlib import Path
from email.message import EmailMessage
import yfinance as yf
from datetime import datetime
import pytz
import requests

BASE_DIR = Path(__file__).resolve().parent.parent
STOCK_TXT_PATH = BASE_DIR / "data" / "stock.txt"

def load_kv() -> dict:
    kv = {}
    for k, v in os.environ.items():
        if k not in kv and v.strip() != "":
            kv[k] = v.strip()
    return kv

def load_config() -> dict:
    c = load_kv()
    
    # email.json 로드하여 병합 (존재하는 경우)
    email_json_path = BASE_DIR / "data" / "email.json"
    if email_json_path.exists():
        try:
            import json
            with open(email_json_path, "r", encoding="utf-8") as f:
                email_cfg = json.load(f)
                if "smtp_host" in email_cfg: c["SMTP_HOST"] = email_cfg["smtp_host"]
                if "smtp_port" in email_cfg: c["SMTP_PORT"] = str(email_cfg["smtp_port"])
                if "smtp_user" in email_cfg: c["SMTP_USER"] = email_cfg["smtp_user"]
                
                # sender -> EMAIL_FROM
                if "sender" in email_cfg: 
                    c["EMAIL_FROM"] = email_cfg["sender"]
                elif "smtp_user" in email_cfg:
                    c["EMAIL_FROM"] = email_cfg["smtp_user"]
                
                # receivers -> EMAIL_TO
                if "receivers" in email_cfg:
                    receivers = email_cfg["receivers"]
                    if isinstance(receivers, list):
                        c["EMAIL_TO"] = ",".join(receivers)
                    else:
                        c["EMAIL_TO"] = str(receivers)
        except Exception as e:
            print(f"[ERROR] 이메일 설정 파일(email.json) 파싱 실패: {e}", file=sys.stderr)

    # 환경변수가 명시적으로 지정된 경우 최우선 적용 (기존 환경변수 동작 보장)
    for env_k, env_v in os.environ.items():
        if env_v.strip() != "":
            if env_k in {"SMTP_HOST", "SMTP_PORT", "SMTP_USER", "EMAIL_FROM", "EMAIL_TO", "SMTP_PASS"}:
                c[env_k] = env_v.strip()

    c.setdefault("SMTP_PORT", "587")
    c["SMTP_PORT"] = int(c["SMTP_PORT"])
    return c

def send_email(cfg: dict, subject: str, html_body: str):
    host = cfg.get("SMTP_HOST")
    port = cfg.get("SMTP_PORT", 587)
    user = cfg.get("SMTP_USER")
    pw = cfg.get("SMTP_PASS")
    to_list = cfg.get("EMAIL_TO")
    
    if not host or not user or not pw or not to_list:
        print("[WEEKLY-REPORT] 메일 발송 설정(SMTP_HOST, SMTP_USER, SMTP_PASS, EMAIL_TO)이 누락되었습니다.")
        return

    to_addrs = [x.strip() for x in to_list.split(",") if x.strip()]

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = cfg.get("EMAIL_FROM", user)
    msg["To"] = ", ".join(to_addrs)
    msg.set_content("HTML을 지원하는 이메일 클라이언트가 필요합니다.")
    msg.add_alternative(html_body, subtype="html")

    ctx = ssl.create_default_context()
    try:
        if port == 465:
            with smtplib.SMTP_SSL(host, port, context=ctx) as s:
                s.login(user, pw)
                s.send_message(msg)
        else:
            with smtplib.SMTP(host, port) as s:
                s.starttls(context=ctx)
                s.login(user, pw)
                s.send_message(msg)
        print(f"[WEEKLY-REPORT] 이메일 발송 성공: {to_list}")
    except Exception as e:
        print(f"[WEEKLY-REPORT] 이메일 발송 실패: {e}")

def create_github_issue(cfg: dict, subject: str, body_markdown: str):
    token = os.environ.get("GITHUB_TOKEN") or cfg.get("GITHUB_TOKEN")
    if not token:
        print("[WEEKLY-REPORT] GITHUB_TOKEN이 설정되지 않아 깃허브 이슈를 생성하지 않습니다.")
        return

    repo = os.environ.get("GITHUB_REPOSITORY") or cfg.get("GITHUB_REPOSITORY") or "leemgs/stock-alert"
    url = f"https://api.github.com/repos/{repo}/issues"
    
    headers = {
        "Authorization": f"token {token}",
        "Accept": "application/vnd.github.v3+json"
    }
    
    payload = {
        "title": subject,
        "body": body_markdown
    }
    
    try:
        response = requests.post(url, json=payload, headers=headers, timeout=15)
        if response.status_code == 201:
            issue_url = response.json().get("html_url")
            print(f"[WEEKLY-REPORT] 깃허브 이슈 생성 성공: {issue_url}")
        else:
            print(f"[WEEKLY-REPORT] 깃허브 이슈 생성 실패: {response.status_code} - {response.text}")
    except Exception as e:
        print(f"[WEEKLY-REPORT] 깃허브 이슈 생성 중 에러 발생: {e}")

def get_weekly_data(tickers):
    results = []
    for t in tickers:
        try:
            df = yf.Ticker(t).history(period="5d")
            if df.empty:
                continue
            df = df.dropna(subset=['Close'])
            if len(df) >= 2:
                start_price = float(df['Close'].iloc[0])
                end_price = float(df['Close'].iloc[-1])
                change_pct = ((end_price - start_price) / start_price) * 100
                results.append({
                    "ticker": t,
                    "start": start_price,
                    "end": end_price,
                    "change": change_pct
                })
        except Exception as e:
            print(f"[WEEKLY-REPORT] {t} 조회 중 에러 발생: {e}")
    return results

def main():
    cfg = load_config()
    
    if not STOCK_TXT_PATH.exists():
        print(f"[WEEKLY-REPORT] {STOCK_TXT_PATH} 파일이 없습니다.")
        return
        
    stocks = []
    for line in STOCK_TXT_PATH.read_text(encoding="utf-8").splitlines():
        s = line.strip()
        if not s or s.startswith("#"): continue
        parts = [x.strip() for x in s.split(",")]
        if len(parts) >= 3:
            stocks.append({"loc": parts[0], "name": parts[1], "ticker": parts[2]})
            
    tickers = [s["ticker"] for s in stocks]
    if not tickers:
        print("[WEEKLY-REPORT] 분석할 주식 종목이 없습니다.")
        return
        
    print(f"[WEEKLY-REPORT] {len(tickers)}개 종목 데이터 조회 시작...")
    weekly_data = get_weekly_data(tickers)
    
    if not weekly_data:
        print("[WEEKLY-REPORT] 유효한 주식 데이터가 없어 리포트를 발송하지 않습니다.")
        return
        
    # 등락률 순(내림차순) 정렬
    weekly_data.sort(key=lambda x: x["change"], reverse=True)
    
    ticker_to_name = {s["ticker"]: s["name"] for s in stocks}
    ticker_to_domain = {s["ticker"]: s["loc"] for s in stocks}

    # Group weekly_data by domain
    data_by_domain = {}
    for item in weekly_data:
        t = item["ticker"]
        domain = ticker_to_domain.get(t, "기타")
        data_by_domain.setdefault(domain, []).append(item)

    # Preserve exact order of domains as they appear in stock.txt
    domains_ordered = []
    for s in stocks:
        if s["loc"] not in domains_ordered:
            domains_ordered.append(s["loc"])
    # Any other domains in data that were not in stocks (fallback)
    for domain in data_by_domain.keys():
        if domain not in domains_ordered:
            domains_ordered.append(domain)

    kst = datetime.now(pytz.timezone("Asia/Seoul"))
    date_str = kst.strftime("%Y-%m-%d %H:%M")
    
    md_body = f"## 📈 주간 주식 동향 요약\n"
    md_body += f"**기준일:** {date_str} (최근 5영업일 기준)\n\n"

    html_tables = ""

    for domain in domains_ordered:
        items = data_by_domain.get(domain, [])
        if not items:
            continue
            
        md_body += f"### 📂 {domain}\n\n"
        md_body += "| 종목명 (티커) | 시작가 | 현재가 (종가) | 주간 등락률 |\n"
        md_body += "| :--- | :--- | :--- | :--- |\n"

        html_tables += f"""
            <h3 style="color: #2c3e50; margin-top: 25px; margin-bottom: 10px; border-left: 4px solid #3498db; padding-left: 8px;">📂 {domain}</h3>
            <table>
                <thead>
                    <tr>
                        <th style="width: 40%;">종목명 (티커)</th>
                        <th style="width: 20%;">시작가</th>
                        <th style="width: 20%;">현재가 (종가)</th>
                        <th style="width: 20%;">주간 등락률</th>
                    </tr>
                </thead>
                <tbody>
        """
        
        # Sort items in this domain by change descending
        items.sort(key=lambda x: x["change"], reverse=True)
        
        for item in items:
            t = item["ticker"]
            name = ticker_to_name.get(t, t)
            chg = item["change"]
            start_p = item["start"]
            end_p = item["end"]
            
            if chg > 0:
                color_class = "positive"
                sign = "▲"
            elif chg < 0:
                color_class = "negative"
                sign = "▼"
            else:
                color_class = "neutral"
                sign = "-"
                
            start_str = f"{start_p:,.0f}" if start_p > 1000 else f"{start_p:,.2f}"
            end_str = f"{end_p:,.0f}" if end_p > 1000 else f"{end_p:,.2f}"
            
            html_tables += f"""
                        <tr>
                            <td><strong>{name}</strong> <span style="color:#7f8c8d; font-size:12px;">({t})</span></td>
                            <td>{start_str}</td>
                            <td>{end_str}</td>
                            <td class="{color_class}">{sign} {abs(chg):.2f}%</td>
                        </tr>
            """
            
            md_body += f"| **{name}** ({t}) | {start_str} | {end_str} | {sign} {abs(chg):.2f}% |\n"
            
        html_tables += """
                </tbody>
            </table>
        """
        md_body += "\n"

    html = f"""
    <html>
    <head>
        <meta charset="utf-8">
        <style>
            body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif; background-color: #f4f6f8; color: #333; margin: 0; padding: 20px; }}
            .container {{ max-width: 700px; margin: 0 auto; background: #ffffff; padding: 30px; border-radius: 10px; box-shadow: 0 4px 6px rgba(0,0,0,0.05); }}
            h2 {{ color: #2c3e50; font-size: 24px; margin-bottom: 5px; border-bottom: 2px solid #ecf0f1; padding-bottom: 10px; }}
            .meta {{ font-size: 14px; color: #7f8c8d; margin-bottom: 20px; }}
            table {{ width: 100%; border-collapse: collapse; margin-top: 10px; margin-bottom: 20px; font-size: 14px; }}
            th, td {{ padding: 12px 15px; text-align: left; border-bottom: 1px solid #ddd; }}
            th {{ background-color: #f8f9fa; color: #2c3e50; font-weight: bold; font-size: 13px; }}
            tr:hover {{ background-color: #f5f5f5; }}
            .positive {{ color: #e74c3c; font-weight: bold; }}
            .negative {{ color: #3498db; font-weight: bold; }}
            .neutral {{ color: #7f8c8d; font-weight: bold; }}
            .footer {{ margin-top: 30px; font-size: 12px; color: #bdc3c7; text-align: center; border-top: 1px solid #ecf0f1; padding-top: 10px; }}
        </style>
    </head>
    <body>
        <div class="container">
            <h2>📈 주간 주식 동향 요약</h2>
            <div class="meta">기준일: {date_str} (최근 5영업일 기준)</div>
            
            {html_tables}
            
            <div class="footer">
                Stock Alert &copy; Automated Weekly Report
            </div>
        </div>
    </body>
    </html>
    """
    
    subject = f"[Stock Alert] 주간 주식 증감 추이 요약 리포트 ({date_str})"
    send_email(cfg, subject, html)
    create_github_issue(cfg, subject, md_body)

if __name__ == "__main__":
    try: main()
    except Exception as e:
        import traceback
        traceback.print_exc()
        sys.exit(1)
