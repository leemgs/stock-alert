#!/usr/bin/env python3
import json, datetime, pytz, sys, ssl, smtplib, requests
from pathlib import Path
from email.mime.text import MIMEText

BASE = Path("/opt/stock_alert")
CONFIG_PATH = BASE / "config.txt"
HISTORY_PATH= BASE / "history.json"

def load_kv(path:Path):
    kv={}
    for raw in path.read_text(encoding="utf-8").splitlines():
        s=raw.strip()
        if not s or s.startswith("#") or "=" not in s: continue
        k,v=s.split("=",1); kv[k.strip()]=v.strip()
    return kv

def send_email(cfg, subj, body, subtype="plain"):
    msg=MIMEText(body, subtype, _charset="utf-8")
    msg["Subject"]=subj; msg["From"]=cfg["EMAIL_FROM"]; msg["To"]=cfg["EMAIL_TO"]
    ctx=ssl.create_default_context()
    with smtplib.SMTP(cfg["SMTP_HOST"], int(cfg["SMTP_PORT"]), timeout=20) as s:
        s.ehlo(); s.starttls(context=ctx); s.login(cfg["SMTP_USER"], cfg["SMTP_PASS"])
        s.sendmail(cfg["EMAIL_FROM"], [cfg["EMAIL_TO"]], msg.as_string())

def generate_weekly_html(since_str, now_str, total, downs, ups, by_ticker):
    """
    Generates a premium HTML body for the weekly report email.
    """
    styles = """
    <style>
        body { font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; line-height: 1.6; color: #333; background-color: #f4f7f9; margin: 0; padding: 0; }
        .container { max-width: 600px; margin: 20px auto; background: #ffffff; border-radius: 8px; overflow: hidden; box-shadow: 0 4px 10px rgba(0,0,0,0.05); }
        .header { background: #34495e; color: #ffffff; padding: 25px; text-align: center; }
        .header h1 { margin: 0; font-size: 22px; font-weight: 600; }
        .header p { margin: 5px 0 0; opacity: 0.8; font-size: 14px; }
        .content { padding: 30px; }
        .summary-grid { display: flex; justify-content: space-between; margin-bottom: 25px; background: #f8f9fa; border-radius: 6px; padding: 15px; }
        .summary-item { text-align: center; flex: 1; }
        .summary-label { font-size: 12px; color: #7f8c8d; text-transform: uppercase; margin-bottom: 5px; }
        .summary-value { font-size: 20px; font-weight: bold; color: #2c3e50; }
        .table-container { margin-top: 20px; border: 1px solid #eee; border-radius: 6px; overflow: hidden; }
        table { width: 100%; border-collapse: collapse; }
        th { background: #f8f9fa; text-align: left; padding: 12px 15px; font-size: 13px; color: #7f8c8d; border-bottom: 1px solid #eee; }
        td { padding: 12px 15px; font-size: 14px; border-bottom: 1px solid #eee; }
        .ticker-name { font-weight: 600; color: #2c3e50; }
        .count-down { color: #3498db; font-weight: bold; }
        .count-up { color: #e74c3c; font-weight: bold; }
        .footer { background: #f9f9f9; padding: 20px; text-align: center; font-size: 12px; color: #777; border-top: 1px solid #eee; }
        .empty-msg { text-align: center; color: #95a5a6; font-style: italic; padding: 20px; }
    </style>
    """

    ticker_rows = ""
    if by_ticker:
        for k, v in sorted(by_ticker.items(), key=lambda x: (x[1]['down'] + x[1]['up']), reverse=True):
            ticker_rows += f"""
            <tr>
                <td class="ticker-name">{k}</td>
                <td class="count-down">{v['down']}</td>
                <td class="count-up">{v['up']}</td>
                <td style="text-align:right; font-weight:bold;">{v['down'] + v['up']}</td>
            </tr>
            """
    else:
        ticker_rows = '<tr><td colspan="4" class="empty-msg">지난 7일간 알림 내역이 없습니다.</td></tr>'

    html = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        {styles}
    </head>
    <body>
        <div class="container">
            <div class="header">
                <h1>주간 스톡 리포트</h1>
                <p>{since_str} ~ {now_str}</p>
            </div>
            <div class="content">
                <div class="summary-grid">
                    <div class="summary-item">
                        <div class="summary-label">총 알림</div>
                        <div class="summary-value">{total}</div>
                    </div>
                    <div class="summary-item">
                        <div class="summary-label">하한 돌파</div>
                        <div class="summary-value" style="color:#3498db;">{downs}</div>
                    </div>
                    <div class="summary-item">
                        <div class="summary-label">상한 돌파</div>
                        <div class="summary-value" style="color:#e74c3c;">{ups}</div>
                    </div>
                </div>

                <div class="table-container">
                    <table>
                        <thead>
                            <tr>
                                <th>종목 (티커)</th>
                                <th>하향</th>
                                <th>상향</th>
                                <th style="text-align:right;">합계</th>
                            </tr>
                        </thead>
                        <tbody>
                            {ticker_rows}
                        </tbody>
                    </table>
                </div>
            </div>
            <div class="footer">
                Stock Alert Bot - Weekly Summary Report<br>
                본 리포트는 최근 7일간의 알림 기록을 바탕으로 자동 생성되었습니다.
            </div>
        </div>
    </body>
    </html>
    """
    return html

def post_slack(url, username, icon, blocks):
    payload={"username":username,"icon_emoji":icon,"blocks":blocks}
    r=requests.post(url, json=payload, timeout=10)
    if r.status_code!=200:
        print(f"[WEEKLY] Slack 전송 실패: {r.status_code} {r.text}", file=sys.stderr)

def parse_ts(ts_str, tz):
    return tz.localize(datetime.datetime.strptime(" ".join(ts_str.split(" ")[:2]), "%Y-%m-%d %H:%M:%S"))

def main():
    cfg=load_kv(CONFIG_PATH)
    tz=pytz.timezone(cfg.get("WEEKLY_REPORT_TZ", cfg.get("TZ","Asia/Seoul")))
    now=datetime.datetime.now(tz); since=now-datetime.timedelta(days=7)
    try: hist=json.loads(HISTORY_PATH.read_text(encoding="utf-8"))
    except: hist=[]

    total=0; downs=0; ups=0; by_ticker={}
    for ev in hist:
        try: ts=parse_ts(ev["ts"], tz)
        except: continue
        if ts<since: continue
        total+=1
        key=f"{ev.get('name',ev['ticker'])} ({ev['ticker']})"
        by_ticker.setdefault(key,{"down":0,"up":0})
        if ev.get("dir")=="down": by_ticker[key]["down"]+=1; downs+=1
        elif ev.get("dir")=="up": by_ticker[key]["up"]+=1; ups+=1

    lines=[]
    lines.append(f"*기간:* {since.strftime('%Y-%m-%d')} ~ {now.strftime('%Y-%m-%d')}")
    lines.append(f"*총 알림:* {total}건 (하 {downs} / 상 {ups})\n")
    if by_ticker:
        lines.append("*티커별 건수:*")
        for k,v in sorted(by_ticker.items(), key=lambda x:(x[1]['down']+x[1]['up']), reverse=True):
            lines.append(f"- {k}: 하 {v['down']} / 상 {v['up']}")
    else:
        lines.append("_지난 7일간 알림 없음_")
    body="\n".join(lines)

    # 이메일 발송
    try:
        since_str = since.strftime('%Y-%m-%d')
        now_str = now.strftime('%Y-%m-%d')
        html_report = generate_weekly_html(since_str, now_str, total, downs, ups, by_ticker)
        
        send_email(cfg, "[Stock Alert] 주간 리포트", html_report, subtype="html")
        print("[WEEKLY] 이메일 발송 완료")
    except Exception as e:
        print(f"[WEEKLY] 이메일 발송 실패: {e}", file=sys.stderr)

    # Slack
    if cfg.get("SLACK_ENABLE","false").lower()=="true":
        username=cfg.get("SLACK_USERNAME","Stock-Alert-Bot")
        icon=cfg.get("SLACK_ICON_EMOJI",":bar_chart:")
        split = cfg.get("WEEKLY_REPORT_SPLIT","false").lower()=="true"

        blocks_all=[
            {"type":"header","text":{"type":"plain_text","text":"🗓️ Weekly Stock Alert Report","emoji":True}},
            {"type":"section","text":{"type":"mrkdwn","text":body}}
        ]

        if split:
            down_lines=[l for l in lines if "하 " in l and "/ 상 " not in l]
            up_lines  =[l for l in lines if " 상 " in l]
            if cfg.get("SLACK_WEBHOOK_DOWN"):
                blocks_down=[
                    {"type":"header","text":{"type":"plain_text","text":"🗓️ Weekly DOWN Summary","emoji":True}},
                    {"type":"section","text":{"type":"mrkdwn","text":"\n".join(down_lines) if down_lines else "_지난주 하향 알림 없음_"}}
                ]
                post_slack(cfg["SLACK_WEBHOOK_DOWN"], username, icon, blocks_down)
            if cfg.get("SLACK_WEBHOOK_UP"):
                blocks_up=[
                    {"type":"header","text":{"type":"plain_text","text":"🗓️ Weekly UP Summary","emoji":True}},
                    {"type":"section","text":{"type":"mrkdwn","text":"\n".join(up_lines) if up_lines else "_지난주 상향 알림 없음_"}}
                ]
                post_slack(cfg["SLACK_WEBHOOK_UP"], username, icon, blocks_up)

        url_report = cfg.get("SLACK_WEBHOOK_REPORT") or cfg.get("SLACK_WEBHOOK_URL")
        if url_report:
            post_slack(url_report, username, icon, blocks_all)

if __name__=="__main__":
    main()
