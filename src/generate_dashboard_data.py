#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Dashboard Data Generator
========================
`data/stock.txt` 에 정의된 종목들의 과거 주가 이력(주봉, 최대 5년)과
현재 시세/기업 정보를 수집하여 정적 대시보드(`docs/`)가 읽을 수 있는
`docs/data/history.json` 파일을 생성합니다.

- 브라우저(정적 GitHub Pages)에서는 CORS 제한으로 Yahoo Finance API를
  직접 호출할 수 없기 때문에, GitHub Actions(Python + yfinance)에서
  본 스크립트를 주기적으로 실행하여 JSON 데이터를 미리 생성/커밋합니다.

출력 스키마 (docs/data/history.json):
{
  "generated_at": "2026-07-18T09:00:00+09:00",
  "period": "5y", "interval": "1wk",
  "domains": ["AI", "SW", ...],
  "tickers": {
    "<ticker>": {
      "name", "domain", "ticker", "currency", "desc",
      "down", "up",
      "current", "prev_close", "change_pct",
      "week52_high", "week52_low", "sector", "industry",
      "market_cap", "website",
      "series": [["2021-07-05", 123.45], ...]   # [날짜, 종가(주봉)]
    }, ...
  },
  "errors": ["<ticker>: <reason>", ...]
}
"""
import os
import sys
import json
import math
import datetime
from pathlib import Path

import yfinance as yf
import pytz

BASE_DIR = Path(__file__).resolve().parent.parent
STOCKS_PATH = BASE_DIR / "data" / "stock.txt"
OUT_DIR = BASE_DIR / "docs" / "data"
OUT_PATH = OUT_DIR / "history.json"

PERIOD = os.getenv("DASHBOARD_PERIOD", "5y")
INTERVAL = os.getenv("DASHBOARD_INTERVAL", "1wk")
TZ = os.getenv("TZ", "Asia/Seoul")


def parse_float_or_none(s):
    s = (s or "").strip()
    if not s:
        return None
    try:
        return float(s)
    except Exception:
        return None


def load_stocks(path: Path):
    """multi_stock_alert.py 와 동일한 파싱 규칙."""
    items = []
    with path.open(encoding="utf-8") as f:
        for raw in f:
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            parts = [p.strip() for p in line.split(",")]
            while len(parts) < 6:
                parts.append("")
            loc, name, ticker, down_str, up_str, desc = parts[:6]
            down = parse_float_or_none(down_str)
            up = parse_float_or_none(up_str)
            if down is None and up is None:
                continue
            items.append({
                "loc": loc, "name": name, "ticker": ticker,
                "down": down, "up": up, "desc": desc,
            })
    return items


def _clean(v):
    """NaN/inf 를 None 으로 정리."""
    if v is None:
        return None
    try:
        f = float(v)
        if math.isnan(f) or math.isinf(f):
            return None
        return f
    except Exception:
        return None


def fetch_ticker(stock):
    tkr = stock["ticker"]
    t = yf.Ticker(tkr)

    # --- 과거 주가 이력 (주봉) ---
    hist = t.history(period=PERIOD, interval=INTERVAL)
    series = []
    if hist is not None and not hist.empty and "Close" in hist:
        for idx, close in hist["Close"].items():
            c = _clean(close)
            if c is None:
                continue
            try:
                date_str = idx.strftime("%Y-%m-%d")
            except Exception:
                date_str = str(idx)[:10]
            series.append([date_str, round(c, 4)])

    if not series:
        raise RuntimeError("가격 이력 없음")

    current = series[-1][1]
    prev_close = series[-2][1] if len(series) >= 2 else None
    change_pct = None
    if prev_close:
        change_pct = round((current - prev_close) / prev_close * 100.0, 2)

    # --- 기업/시세 메타데이터 (실패해도 무시) ---
    currency = None
    sector = industry = website = None
    market_cap = week52_high = week52_low = None
    try:
        fi = t.fast_info
        currency = getattr(fi, "currency", None)
        week52_high = _clean(getattr(fi, "year_high", None))
        week52_low = _clean(getattr(fi, "year_low", None))
        market_cap = _clean(getattr(fi, "market_cap", None))
        lp = _clean(getattr(fi, "last_price", None))
        if lp is not None:
            current = round(lp, 4)
    except Exception:
        pass

    try:
        info = t.info or {}
        currency = info.get("currency") or currency
        sector = info.get("sector") or sector
        industry = info.get("industry") or industry
        website = info.get("website") or website
        market_cap = _clean(info.get("marketCap")) or market_cap
        week52_high = _clean(info.get("fiftyTwoWeekHigh")) or week52_high
        week52_low = _clean(info.get("fiftyTwoWeekLow")) or week52_low
        cp = _clean(info.get("regularMarketPrice"))
        if cp is not None:
            current = round(cp, 4)
        pc = _clean(info.get("regularMarketPreviousClose"))
        if pc is not None:
            prev_close = round(pc, 4)
            if prev_close:
                change_pct = round((current - prev_close) / prev_close * 100.0, 2)
    except Exception:
        pass

    return {
        "name": stock["name"],
        "domain": stock["loc"],
        "ticker": tkr,
        "desc": stock["desc"],
        "down": stock["down"],
        "up": stock["up"],
        "currency": currency,
        "current": current,
        "prev_close": prev_close,
        "change_pct": change_pct,
        "week52_high": week52_high,
        "week52_low": week52_low,
        "sector": sector,
        "industry": industry,
        "market_cap": market_cap,
        "website": website,
        "series": series,
    }


def main():
    stocks = load_stocks(STOCKS_PATH)
    print(f"[dashboard] {len(stocks)}개 종목 데이터 수집 시작 "
          f"(period={PERIOD}, interval={INTERVAL})")

    tickers = {}
    errors = []
    domains = []
    for s in stocks:
        if s["loc"] and s["loc"] not in domains:
            domains.append(s["loc"])
        try:
            data = fetch_ticker(s)
            tickers[s["ticker"]] = data
            print(f"  ✓ {s['ticker']:<14} {s['name']} "
                  f"({len(data['series'])} pts)")
        except Exception as e:
            msg = f"{s['ticker']}: {e}"
            errors.append(msg)
            print(f"  ✗ {msg}", file=sys.stderr)

    now = datetime.datetime.now(pytz.timezone(TZ))
    out = {
        "generated_at": now.isoformat(),
        "period": PERIOD,
        "interval": INTERVAL,
        "domains": domains,
        "count": len(tickers),
        "tickers": tickers,
        "errors": errors,
    }

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(
        json.dumps(out, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )
    print(f"[dashboard] 저장 완료: {OUT_PATH} "
          f"(성공 {len(tickers)} / 실패 {len(errors)})")


if __name__ == "__main__":
    main()
