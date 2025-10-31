#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
multi_stock_alert.py
- KRX(.KS/.KQ) 종목의 yfinance fast_info 이상치 대응
- 분봉 history() 기반 보정, 전일 종가 대비 sanity-check, 정수 호가 강제
- 상/하한 임계치 비교 후 알림 메시지 출력
"""

from __future__ import annotations
import os
import sys
import traceback
import datetime as dt
import pandas as pd
import yfinance as yf
import pytz

KST = pytz.timezone("Asia/Seoul")

DEFAULT_TICKER_CSV = os.environ.get("TICKER_CSV", "./tickers.csv")
PRICE_SOURCE = os.environ.get("PRICE_SOURCE", "auto").lower().strip()
try:
    KRX_JUMP_THRESHOLD = float(os.environ.get("KRX_JUMP_THRESHOLD", "0.20"))
except Exception:
    KRX_JUMP_THRESHOLD = 0.20

def log(level, msg):
    ts = dt.datetime.now(KST).strftime("%Y-%m-%d %H:%M:%S %Z")
    print(f"[{level}] {ts} | {msg}")

def is_krx_ticker(ticker: str) -> bool:
    return ticker.upper().endswith(".KS") or ticker.upper().endswith(".KQ")

def get_prev_close(t: yf.Ticker):
    try:
        d = t.history(period="2d", interval="1d")
        if len(d) >= 2:
            return float(d["Close"].iloc[-2])
    except Exception:
        return None

def get_last_close_intraday(t: yf.Ticker, interval="1m"):
    try:
        hist = t.history(period="1d", interval=interval)
        if not hist.empty:
            return float(hist["Close"].iloc[-1])
    except Exception:
        return None

def fetch_price(ticker: str):
    t = yf.Ticker(ticker)
    krx = is_krx_ticker(ticker)
    price = None
    try:
        if not krx and PRICE_SOURCE != "history":
            price = t.fast_info.last_price
        hist_price = get_last_close_intraday(t, "1m") or get_last_close_intraday(t, "5m")
        if price is None or (hist_price and abs(price - hist_price) / hist_price > 0.02):
            price = hist_price
        if krx and price:
            prev = get_prev_close(t)
            if prev and abs(price - prev) / prev > KRX_JUMP_THRESHOLD:
                return None
            price = round(price)
    except Exception:
        return None
    return price

def parse_threshold(val):
    try:
        if val is None or str(val).strip() == "" or str(val).lower() == "none":
            return None
        f = float(val)
        return f if f > 0 else None
    except Exception:
        return None

def format_price(p):
    return "N/A" if p is None else f"{p:,.0f}"

def main(csv_path=DEFAULT_TICKER_CSV):
    now_kst = dt.datetime.now(KST).strftime("%Y-%m-%d %H:%M:%S %Z")
    print(f"\n시각: {now_kst}\n")
    df = pd.read_csv(csv_path)
    alerts_up, alerts_down, errors = [], [], []

    for _, row in df.iterrows():
        name, ticker = str(row['company_name']), str(row['ticker'])
        lower, upper = parse_threshold(row['price_down']), parse_threshold(row['price_up'])
        price = fetch_price(ticker)
        if price is None:
            errors.append((name, ticker))
            continue
        if upper and price >= upper:
            alerts_up.append((name, ticker, price, upper))
        if lower and price <= lower:
            alerts_down.append((name, ticker, price, lower))

    if alerts_up:
        print("[상한 돌파] (현재가 ≥ 상한)")
        for n, t, p, u in alerts_up:
            print(f"- {n} ({t}): {format_price(p)} ≥ {format_price(u)}")
        print()
    if alerts_down:
        print("[하한 돌파] (현재가 ≤ 하한)")
        for n, t, p, l in alerts_down:
            print(f"- {n} ({t}): {format_price(p)} ≤ {format_price(l)}")
        print()
    if errors:
        print("[가격 조회 오류]")
        for n, t in errors:
            print(f"- {n} ({t})")
        print()

if __name__ == "__main__":
    csv = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_TICKER_CSV
    try:
        sys.exit(main(csv))
    except Exception as e:
        log("ERROR", str(e))
        log("DEBUG", traceback.format_exc())
        sys.exit(1)
