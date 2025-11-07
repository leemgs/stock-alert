#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Stock Alert Bot
- BASE: /opt/stock_alert
- INFO_TYPE: "info" (default) or "fast_info"
- History mode (K3): auto — disabled on CI/GitHub Actions, enabled otherwise.

Files under /opt/stock_alert:
  - multi_stock_alert.py  (this script)
  - config.txt            (key=value)
  - stock.txt             (CSV-like lines: loc, name, ticker, price_down, price_up)
  - state.json            (runtime state)
  - history.json          (recent alerts log; auto-disabled on CI)
"""
import os, sys, csv, json, smtplib, ssl, datetime, traceback
from pathlib import Path
from email.mime.text import MIMEText

import yfinance as yf

# --- GitHub reference footer (added)
import os
REF_GITHUB_URL = os.getenv("REF_GITHUB_URL", "https://github.com/leemgs/stock-alert")
# --- end
import pytz
import requests

# ---------- Paths / Constants ----------
BASE = Path("/opt/stock_alert")
CONFIG_PATH = BASE / "config.txt"
STOCKS_PATH = BASE / "stock.txt"
STATE_PATH  = BASE / "state.json"
HISTORY_PATH= BASE / "history.json"
LOG_PREFIX  = "[STOCK-ALERT] "

# ---------- Helpers: env / CI detection ----------
def _is_ci_like_env() -> bool:
    # GitHub Actions exposes GITHUB_ACTIONS=true and CI=true
    ga = os.getenv("GITHUB_ACTIONS", "").lower() == "true"
    ci = os.getenv("CI", "").lower() == "true"
    return ga or ci

# ---------- Config ----------
def load_kv(path: Path) -> dict:
    kv={}
    for raw in path.read_text(encoding="utf-8").splitlines():
        s=raw.strip()
        if not s or s.startswith("#") or "=" not in s: continue
        k,v=s.split("=",1); kv[k.strip()]=v.strip()
    return kv

def load_config(path: Path)->dict:
    c = load_kv(path)
    # defaults
    c.setdefault("SMTP_PORT","587")
    c.setdefault("EMAIL_FROM", c.get("SMTP_USER","stock-alert@example.com"))
    c.setdefault("EMAIL_TO", c.get("SMTP_USER","root@localhost"))
    c.setdefault("TZ","Asia/Seoul")
    c.setdefault("DAILY_DEDUP","true")
    c.setdefault("ALERT_ON_CROSSDOWN_ONLY","false")
    c.setdefault("ALERT_ON_CROSSUP_ONLY","false")

    # Slack
    c.setdefault("SLACK_ENABLE","false")
    c.setdefault("SLACK_USERNAME","Stock-Alert-Bot")
    c.setdefault("SLACK_ICON_EMOJI",":bar_chart:")
    c.setdefault("SLACK_SPLIT_CHANNELS","false")   # A: default single channel

    # Active window
    c.setdefault("ACTIVE_WINDOW_ENABLE","false")
    c.setdefault("ACTIVE_TZ", c.get("TZ","Asia/Seoul"))
    c.setdefault("ACTIVE_BUSINESS_DAYS_ONLY","true")
    c.setdefault("ACTIVE_START","00:00")
    c.setdefault("ACTIVE_END","23:59")

    # Rate-limit
    c.setdefault("ALERT_RATE_LIMIT_PER_TICKER_PER_DAY","2")
    c.setdefault("ALERT_MIN_INTERVAL_MINUTES","60")
    c.setdefault("ALERT_GLOBAL_DAILY_CAP","100")

    # Price source
    c.setdefault("INFO_TYPE", "info")

    # History mode (K3: auto)
    # HISTORY_MODE in {"auto","on","off"}
    c.setdefault("HISTORY_MODE", "auto")

    # types
    c["SMTP_PORT"]=int(c["SMTP_PORT"])
    c["DAILY_DEDUP"]=c["DAILY_DEDUP"].lower()=="true"
    c["ALERT_ON_CROSSDOWN_ONLY"]=c["ALERT_ON_CROSSDOWN_ONLY"].lower()=="true"
    c["ALERT_ON_CROSSUP_ONLY"]=c["ALERT_ON_CROSSUP_ONLY"].lower()=="true"
    c["SLACK_ENABLE"]=c["SLACK_ENABLE"].lower()=="true"
    c["SLACK_SPLIT_CHANNELS"]=c["SLACK_SPLIT_CHANNELS"].lower()=="true"
    c["ACTIVE_WINDOW_ENABLE"]=c["ACTIVE_WINDOW_ENABLE"].lower()=="true"
    c["ACTIVE_BUSINESS_DAYS_ONLY"]=c["ACTIVE_BUSINESS_DAYS_ONLY"].lower()=="true"
    c["ALERT_RATE_LIMIT_PER_TICKER_PER_DAY"]=int(c["ALERT_RATE_LIMIT_PER_TICKER_PER_DAY"])
    c["ALERT_MIN_INTERVAL_MINUTES"]=int(c["ALERT_MIN_INTERVAL_MINUTES"])
    c["ALERT_GLOBAL_DAILY_CAP"]=int(c["ALERT_GLOBAL_DAILY_CAP"])
    c["INFO_TYPE"]=c["INFO_TYPE"].lower().strip()
    if c["INFO_TYPE"] not in {"fast_info","info"}:
        c["INFO_TYPE"] = "info"

    hm = c["HISTORY_MODE"].lower().strip()
    if hm not in {"auto","on","off"}:
        hm = "auto"
    # Resolve auto -> disabled on CI, enabled otherwise
    if hm == "auto":
        c["HISTORY_ENABLE"] = (not _is_ci_like_env())
    elif hm == "on":
        c["HISTORY_ENABLE"] = True
    else:
        c["HISTORY_ENABLE"] = False

    return c

# ---------- Stocks / State / History ----------
def parse_float_or_none(s:str):
    s=s.strip()
    if not s: return None
    try: return float(s)
    except: return None

def load_stocks(path:Path):
    items=[]
    with path.open(encoding="utf-8") as f:
        for raw in f:
            line=raw.strip()
            if not line or line.startswith("#"): continue
            parts=[p.strip() for p in line.split(",") ]
            while len(parts)<5: parts.append("")
            loc,name,ticker,down_str,up_str = parts[:5]
            down=parse_float_or_none(down_str); up=parse_float_or_none(up_str)
            if down is None and up is None: continue
            items.append({"loc":loc,"name":name,"ticker":ticker,"down":down,"up":up})
    return items

def load_state():
    if STATE_PATH.exists():
        try: return json.loads(STATE_PATH.read_text(encoding="utf-8"))
        except: pass
    return {
        "last_alert_date":{}, "last_price":{},
        "alert_counters":{"date":None,"per":{}},
        "last_alert_ts":{},
        "global_counter":{"date":None,"count":0}
    }

def save_state(st): STATE_PATH.write_text(json.dumps(st,ensure_ascii=False),encoding="utf-8")

def load_history(cfg):
    if not cfg.get("HISTORY_ENABLE", True):
        return []
    if HISTORY_PATH.exists():
        try: return json.loads(HISTORY_PATH.read_text(encoding="utf-8"))
        except: pass
    return []

def append_history(cfg, events):
    if not cfg.get("HISTORY_ENABLE", True):
        return
    hist = load_history(cfg)
    hist.extend(events)
    if len(hist)>5000: hist=hist[-5000:]
    HISTORY_PATH.write_text(json.dumps(hist,ensure_ascii=False),encoding="utf-8")

# ---------- Time / Window ----------
def now_tz(tzname:str):
    return datetime.datetime.now(pytz.timezone(tzname))

def within_active_window(cfg:dict)->bool:
    if not cfg["ACTIVE_WINDOW_ENABLE"]: return True
    tz=pytz.timezone(cfg["ACTIVE_TZ"]); now=datetime.datetime.now(tz)
    if cfg["ACTIVE_BUSINESS_DAYS_ONLY"] and now.weekday()>=5: return False
    def HM(s): h,m=s.split(":"); return int(h),int(m)
    sh,sm=HM(cfg["ACTIVE_START"]); eh,em=HM(cfg["ACTIVE_END"])
    start=now.replace(hour=sh,minute=sm,second=0,microsecond=0)
    end=now.replace(hour=eh,minute=em,second=0,microsecond=0)
    return start<=now<=end

# ---------- Price fetch (requested logic) ----------
def fetch_price(ticker: str, info_type: str = "info"):
    t = yf.Ticker(ticker)

    fast_price = None
    info_price = None

    # fast_info
    try:
        fast_price = t.fast_info.last_price
    except Exception:
        fast_price = None

    # info
    try:
        info_data = t.info
        info_price = info_data.get("regularMarketPrice")
    except Exception:
        info_price = None

    # 선택 우선순위
    if info_type == "fast_info":
        primary, secondary = fast_price, info_price
    else:  # default "info"
        primary, secondary = info_price, fast_price

    price = primary if primary is not None else secondary

    # 최종 폴백: 1분봉 Close
    if price is None:
        try:
            hist = t.history(period="1d", interval="1m")
            if not hist.empty:
                price = float(hist["Close"].iloc[-1])
        except Exception:
            price = None

    return price

# ---------- Email / Slack ----------
def send_email(cfg, subj, _append_github_footer(body)):
    msg=MIMEText(body,_charset="utf-8")
    msg["Subject"]=subj; msg["From"]=cfg["EMAIL_FROM"]; msg["To"]=cfg["EMAIL_TO"]
    ctx=ssl.create_default_context()
    with smtplib.SMTP(cfg["SMTP_HOST"], cfg["SMTP_PORT"], timeout=20) as s:
        s.ehlo(); s.starttls(context=ctx); s.login(cfg["SMTP_USER"], cfg["SMTP_PASS"])
        s.sendmail(cfg["EMAIL_FROM"], [cfg["EMAIL_TO"]], msg.as_string())

def slack_blocks_header(ts_str): 
    return [
        {"type":"header","text":{"type":"plain_text","text":"📈 Stock Alert","emoji":True}},
        {"type":"context","elements":[{"type":"mrkdwn","text":f"*시각:* {ts_str}"}]}
    ]

def slack_blocks_section(title, rows):
    blocks=[]
    if rows:
        blocks.append({"type":"section","text":{"type":"mrkdwn","text":f"*{title}*"}})
        desc = "\n".join(rows)
        blocks.append({"type":"section","text":{"type":"mrkdwn","text":desc}})
    return blocks

def post_slack(url, username, icon_emoji, slack_append_footer(blocks )):
    payload={"username":username, "icon_emoji":icon_emoji, "blocks":blocks}
    r=requests.post(url, json=payload, timeout=10)
    if r.status_code!=200:
        print(LOG_PREFIX+f"Slack 전송 실패: {r.status_code} {r.text}", file=sys.stderr)

def send_slack_split(cfg, ts_str, down_breaches, up_breaches, errors):
    if not cfg["SLACK_ENABLE"]: return
    username=cfg.get("SLACK_USERNAME","Stock-Alert-Bot")
    icon=cfg.get("SLACK_ICON_EMOJI",":bar_chart:")

    if down_breaches:
        url = cfg.get("SLACK_WEBHOOK_DOWN") or cfg.get("SLACK_WEBHOOK_URL")
        if url:
            rows=[f"- *{n}* `{t}`: `{p:.2f}` ≤ `{th:.2f}`" for n,t,p,th in down_breaches]
            blocks = slack_blocks_header(ts_str) +                      slack_blocks_section(":small_red_triangle_down: 하한 돌파 (현재가 ≤ 하한)", rows)
            if errors:
                blocks.append({"type":"divider"})
                blocks += slack_blocks_section("_(참고) 조회 오류_", [f"- {e}" for e in errors])
            post_slack(url, username, icon, slack_append_footer(blocks ))

    if up_breaches:
        url = cfg.get("SLACK_WEBHOOK_UP") or cfg.get("SLACK_WEBHOOK_URL")
        if url:
            rows=[f"- *{n}* `{t}`: `{p:.2f}` ≥ `{th:.2f}`" for n,t,p,th in up_breaches]
            blocks = slack_blocks_header(ts_str) +                      slack_blocks_section(":small_red_triangle: 상한 돌파 (현재가 ≥ 상한)", rows)
            if errors and not down_breaches:
                blocks.append({"type":"divider"})
                blocks += slack_blocks_section("_(참고) 조회 오류_", [f"- {e}" for e in errors])
            post_slack(url, username, icon, slack_append_footer(blocks ))

# ---------- Rate-limit ----------
def rl_reset_if_new_day(state, today):
    if state["alert_counters"].get("date") != today:
        state["alert_counters"] = {"date": today, "per": {}}
    if state["global_counter"].get("date") != today:
        state["global_counter"] = {"date": today, "count": 0}

def rl_key(ticker, kind):  # kind in {"down","up"}
    return f"{ticker}|{kind}"

def rl_can_send(cfg, state, tz, ticker, kind, now_dt):
    k = rl_key(ticker, kind)
    if state["global_counter"]["count"] >= cfg["ALERT_GLOBAL_DAILY_CAP"]:
        return (False, "global_cap_reached")
    per = state["alert_counters"]["per"].get(k, 0)
    if per >= cfg["ALERT_RATE_LIMIT_PER_TICKER_PER_DAY"]:
        return (False, "per_ticker_daily_cap")
    last_ts_str = state["last_alert_ts"].get(k)
    if last_ts_str:
        try:
            last_dt = datetime.datetime.fromisoformat(last_ts_str)
        except Exception:
            last_dt = None
        if last_dt is not None:
            delta = now_dt - last_dt
            mins = delta.total_seconds()/60.0
            if mins < cfg["ALERT_MIN_INTERVAL_MINUTES"]:
                return (False, "min_interval_violation")
    return (True, "")

def rl_commit(state, ticker, kind, now_dt):
    k = rl_key(ticker, kind)
    cur = state["alert_counters"]["per"].get(k, 0)
    state["alert_counters"]["per"][k] = cur + 1
    state["global_counter"]["count"] = state["global_counter"].get("count", 0) + 1
    state["last_alert_ts"][k] = now_dt.isoformat()

# ---------- Main ----------
def main():
    cfg = load_config(CONFIG_PATH)
    info_type = cfg.get("INFO_TYPE", "info").lower()

    if not within_active_window(cfg):
        print(LOG_PREFIX+"비활성 시간대 — 알림/슬랙 생략"); return

    stocks=load_stocks(STOCKS_PATH)
    state =load_state()
    ts = now_tz(cfg["TZ"]); today=ts.strftime("%Y-%m-%d"); ts_str=ts.strftime("%Y-%m-%d %H:%M:%S %Z")

    rl_reset_if_new_day(state, today)

    down_breaches=[]; up_breaches=[]; errors=[]; new_events=[]
    rate_limited_notes=[]

    for s in stocks:
        tkr=s["ticker"]; dth=s["down"]; uth=s["up"]
        try:
            price=fetch_price(tkr, info_type)
            if price is None:
                errors.append(f"{tkr}: 가격 조회 실패"); continue
            last=state["last_price"].get(tkr)

            if dth is not None:
                crossed=(last is not None and last>dth and price<=dth)
                alert=False
                if price<=dth:
                    if cfg["ALERT_ON_CROSSDOWN_ONLY"]: alert=crossed
                    else:
                        if cfg["DAILY_DEDUP"]:
                            last_day=state["last_alert_date"].get(f"{tkr}|down")
                            alert=(last_day!=today) or crossed
                        else: alert=True
                if alert:
                    can, why = rl_can_send(cfg, state, cfg["TZ"], tkr, "down", ts)
                    if can:
                        down_breaches.append((s["name"], tkr, price, dth))
                        state["last_alert_date"][f"{tkr}|down"]=today
                        rl_commit(state, tkr, "down", ts)
                        new_events.append({"ts":ts_str,"dir":"down","name":s["name"],"ticker":tkr,"price":price,"threshold":dth})
                    else:
                        rate_limited_notes.append(f"{tkr}|down 제한({why})")

            if uth is not None:
                crossed=(last is not None and last<uth and price>=uth)
                alert=False
                if price>=uth:
                    if cfg["ALERT_ON_CROSSUP_ONLY"]: alert=crossed
                    else:
                        if cfg["DAILY_DEDUP"]:
                            last_day=state["last_alert_date"].get(f"{tkr}|up")
                            alert=(last_day!=today) or crossed
                        else: alert=True
                if alert:
                    can, why = rl_can_send(cfg, state, cfg["TZ"], tkr, "up", ts)
                    if can:
                        up_breaches.append((s["name"], tkr, price, uth))
                        state["last_alert_date"][f"{tkr}|up"]=today
                        rl_commit(state, tkr, "up", ts)
                        new_events.append({"ts":ts_str,"dir":"up","name":s["name"],"ticker":tkr,"price":price,"threshold":uth})
                    else:
                        rate_limited_notes.append(f"{tkr}|up 제한({why})")

            state["last_price"][tkr]=price

        except Exception as e:
            errors.append(f"{tkr}: {e}")

    if down_breaches or up_breaches:
        lines=[f"시각: {ts_str}"]
        if down_breaches:
            lines.append("\n[하한 돌파] (현재가 ≤ 하한)")
            for n,t,p,th in down_breaches: lines.append(f"- {n} ({t}): {p:.2f} ≤ {th:.2f}")
        if up_breaches:
            lines.append("\n[상한 돌파] (현재가 ≥ 상한)")
            for n,t,p,th in up_breaches: lines.append(f"- {n} ({t}): {p:.2f} ≥ {th:.2f}")
        if rate_limited_notes:
            lines.append("\n(참고) rate-limit으로 생략된 알림:")
            lines += [f"- {x}" for x in rate_limited_notes]
        if errors:
            lines.append("\n(참고) 조회 오류:"); lines += [f"- {e}" for e in errors]
        body="\n".join(lines)
        try:
            send_email(cfg, "[Stock Alert] 임계 도달 종목 (상/하한)", _append_github_footer(body))
            print(LOG_PREFIX+"메일 발송 완료")
        except Exception as e:
            print(LOG_PREFIX+f"메일 발송 실패: {e}", file=sys.stderr)

        if cfg["SLACK_ENABLE"]:
            if cfg["SLACK_SPLIT_CHANNELS"]:
                send_slack_split(cfg, ts_str, down_breaches, up_breaches, errors)
            else:
                url = cfg.get("SLACK_WEBHOOK_URL")
                if url:
                    rows=[]
                    if down_breaches:
                        rows += [f"- *{n}* `{t}`: `{p:.2f}` ≤ `{th:.2f}`" for n,t,p,th in down_breaches]
                    if up_breaches:
                        rows += [f"- *{n}* `{t}`: `{p:.2f}` ≥ `{th:.2f}`" for n,t,p,th in up_breaches]
                    blocks = slack_blocks_header(ts_str) +                              slack_blocks_section("임계 도달 종목 (상/하한)", rows)
                    if errors or rate_limited_notes:
                        blocks.append({"type":"divider"})
                        if errors:
                            blocks += slack_blocks_section("_(참고) 조회 오류_", [f"- {e}" for e in errors])
                        if rate_limited_notes:
                            blocks += slack_blocks_section("_(참고) rate-limit 생략_", [f"- {x}" for x in rate_limited_notes])
                    post_slack(url, cfg.get("SLACK_USERNAME","Stock-Alert-Bot"), cfg.get("SLACK_ICON_EMOJI",":bar_chart:"), blocks)
    else:
        note = []
        if rate_limited_notes: note.append("rate-limit 생략: "+", ".join(rate_limited_notes))
        if errors: note.append("오류: "+" | ".join(errors))
        if note: print(LOG_PREFIX+"; "+"; ".join(note), file=sys.stderr)

    if new_events: append_history(cfg, new_events)
    save_state(state)

if __name__=="__main__":
    try: main()
    except Exception:
        print(LOG_PREFIX+"오류 발생:\n"+traceback.format_exc(), file=sys.stderr)
        sys.exit(1)


def _append_github_footer(text: str) -> str:
    sep = "\n\n---\n"
    return (text or "") + f"{sep}{REF_GITHUB_URL}"

def slack_append_footer(blocks, url=REF_GITHUB_URL):
    try:
        blocks.append({"type": "divider"})
        blocks.append({"type": "context", "elements": [{"type": "mrkdwn", "text": f"<{url}|GitHub: leemgs/stock-alert>"}]})
    except Exception:
        pass
    return blocks
