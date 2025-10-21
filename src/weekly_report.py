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

def send_email(cfg, subj, body):
    msg=MIMEText(body,_charset="utf-8")
    msg["Subject"]=subj; msg["From"]=cfg["EMAIL_FROM"]; msg["To"]=cfg["EMAIL_TO"]
    ctx=ssl.create_default_context()
    with smtplib.SMTP(cfg["SMTP_HOST"], int(cfg["SMTP_PORT"]), timeout=20) as s:
        s.ehlo(); s.starttls(context=ctx); s.login(cfg["SMTP_USER"], cfg["SMTP_PASS"])
        s.sendmail(cfg["EMAIL_FROM"], [cfg["EMAIL_TO"]], msg.as_string())

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

    # 이메일
    try:
        send_email(cfg, "[Stock Alert] 주간 리포트", body)
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
