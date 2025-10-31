#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
multi_stock_alert_v2.py
- GitHub Actions의 에페메럴 환경(스토리지 비영속)을 고려하여
  '디스크에 히스토리를 저장하지 않고'도 오탑을 줄이도록 개선.
- 핵심: fast_info(이상치) 대신 Yahoo quote(regularMarketPrice) 우선 사용 +
       분봉 history(메모리 내 1회 조회)로 교차검증(디스크 미사용).
- KRX(.KS/.KQ): 정수 호가 강제, 전일종가 대비 급격 이탈 필터(기본 20%).
- 해외: fast_info 허용하되, quote/history로 상호 검증.
"""

from __future__ import annotations
import os
import sys
import traceback
import datetime as dt
from typing import Optional

import pandas as pd
import yfinance as yf
import pytz

KST = pytz.timezone("Asia/Seoul")

# ===== 환경 변수 =====
DEFAULT_TICKER_CSV = os.environ.get("TICKER_CSV", "./tickers.csv")
# auto | quote | fast  (history는 디스크 비영속 고려해 명시 옵션에서 제외, 교차검증용 내부 사용만)
PRICE_SOURCE = os.environ.get("PRICE_SOURCE", "auto").lower().strip()
try:
    KRX_JUMP_THRESHOLD = float(os.environ.get("KRX_JUMP_THRESHOLD", "0.20"))  # 20%
except Exception:
    KRX_JUMP_THRESHOLD = 0.20

LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO").upper().strip()
_LOG_LEVELS = {"DEBUG": 10, "INFO": 20, "WARN": 30, "WARNING": 30, "ERROR": 40}
_LOG_MIN = _LOG_LEVELS.get(LOG_LEVEL, 20)


def log(level: str, msg: str):
    if _LOG_LEVELS.get(level.upper(), 20) >= _LOG_MIN:
        ts = dt.datetime.now(KST).strftime("%Y-%m-%d %H:%M:%S %Z")
        print(f"[{level.upper():5s}] {ts} | {msg}")


def is_krx_ticker(ticker: str) -> bool:
    t = (ticker or "").upper()
    return t.endswith(".KS") or t.endswith(".KQ")


# ===== Yahoo quote 계열(디스크 비의존) =====
def get_quote_info_price(t: yf.Ticker) -> Optional[float]:
    """yfinance get_info()의 regularMarketPrice를 우선 사용"""
    try:
        info = t.get_info()  # 네트워크 호출, 디스크 비저장
        for k in ("regularMarketPrice", "currentPrice", "postMarketPrice"):
            v = info.get(k)
            if v is not None:
                return float(v)
    except Exception as e:
        log("DEBUG", f"get_info() price error: {e}")
    return None


def get_quote_info_prev_close(t: yf.Ticker) -> Optional[float]:
    try:
        info = t.get_info()
        v = info.get("regularMarketPreviousClose")
        return float(v) if v is not None else None
    except Exception as e:
        log("DEBUG", f"get_info() prev_close error: {e}")
        return None


# ===== intraday history(메모리 내 1회 조회, 디스크 비사용) =====
def get_intraday_close(t: yf.Ticker, interval: str = "1m") -> Optional[float]:
    try:
        hist = t.history(period="1d", interval=interval)  # 메모리 상 조회
        if hist is not None and not hist.empty:
            return float(hist["Close"].iloc[-1])
    except Exception as e:
        log("DEBUG", f"history({interval}) error: {e}")
    return None


def get_daily_prev_close(t: yf.Ticker) -> Optional[float]:
    try:
        d = t.history(period="2d", interval="1d")
        if d is not None and not d.empty and len(d["Close"]) >= 2:
            return float(d["Close"].iloc[-2])
    except Exception as e:
        log("DEBUG", f"daily prev_close error: {e}")
    return None


def krx_sanity(price: Optional[float], prev_close: Optional[float]) -> Optional[float]:
    if price is None:
        return None
    # 전일 종가 대비 급격 이탈 필터
    if prev_close and prev_close > 0:
        jump = abs(price - prev_close) / prev_close
        if jump > KRX_JUMP_THRESHOLD:
            log("WARN", f"KRX sanity: prev_close 대비 {jump*100:.1f}% 이탈 → drop")
            return None
    # 정수 호가 강제
    try:
        price = round(float(price))
    except Exception:
        return None
    return price


def cross_validate(primary: Optional[float], secondary: Optional[float], tol: float = 0.03) -> Optional[float]:
    """
    두 소스의 가격을 교차 검증. 허용 오차(tol, 기본 3%)를 넘으면 secondary 신뢰.
    """
    if secondary is None:
        return primary
    if primary is None:
        return secondary
    try:
        if abs(primary - secondary) / max(1.0, secondary) > tol:
            return secondary
        return primary
    except Exception:
        return secondary


def fetch_price(ticker: str) -> Optional[float]:
    """
    디스크 영속성 없이 신뢰도 있는 현재가 가져오기.
    - 기본(auto): KRX -> quote 우선 + intraday로 교차검증
                  해외 -> fast_info/quote 교차검증 + intraday 보정
    - quote: quote만 사용(가능하면 교차검증)
    - fast : fast_info 우선(가능하면 교차검증)
    """
    t = yf.Ticker(ticker)
    krx = is_krx_ticker(ticker)

    price_quote = get_quote_info_price(t)
    prev_close_quote = get_quote_info_prev_close(t)
    price_intraday = get_intraday_close(t, "1m") or get_intraday_close(t, "5m")

    # fast_info는 해외/auto에서만 보조로
    price_fast = None
    if PRICE_SOURCE in ("auto", "fast") and not krx:
        try:
            price_fast = t.fast_info.last_price
        except Exception as e:
            log("DEBUG", f"fast_info error: {e}")
            price_fast = None

    # 소스 조합
    if PRICE_SOURCE == "quote":
        price = cross_validate(price_quote, price_intraday, tol=0.03)
    elif PRICE_SOURCE == "fast":
        # fast -> quote -> intraday 순으로 교차 보정
        p = cross_validate(price_fast, price_quote, tol=0.03)
        price = cross_validate(p, price_intraday, tol=0.02)
    else:  # auto
        if krx:
            # KRX: quote 우선, intraday로 교차 보정 (fast는 사용하지 않음)
            price = cross_validate(price_quote, price_intraday, tol=0.02)
        else:
            # 해외: fast/quote 교차 후 intraday로 보정
            p = cross_validate(price_fast, price_quote, tol=0.03)
            price = cross_validate(p, price_intraday, tol=0.02)

    # KRX sanity
    if krx:
        # prev_close는 quote 우선, 없으면 일봉에서 확보
        prev = prev_close_quote if prev_close_quote is not None else get_daily_prev_close(t)
        price = krx_sanity(price, prev)

    return price


def parse_threshold(val) -> Optional[float]:
    try:
        if val is None:
            return None
        s = str(val).strip()
        if s == "" or s.lower() == "none":
            return None
        f = float(s)
        return f if f > 0 else None
    except Exception:
        return None


def load_tickers(csv_path: str) -> pd.DataFrame:
    df = pd.read_csv(csv_path)
    expected = ["loc", "company_name", "ticker", "price_down", "price_up"]
    missing = [c for c in expected if c not in df.columns]
    if missing:
        raise ValueError(f"CSV 누락 컬럼: {missing}")
    return df


def format_price(p: Optional[float]) -> str:
    return "N/A" if p is None else f"{p:,.0f}"


def main(csv_path: str = DEFAULT_TICKER_CSV) -> int:
    now_kst = dt.datetime.now(KST).strftime("%Y-%m-%d %H:%M:%S %Z")
    print(f"\n시각: {now_kst}\n")

    try:
        df = load_tickers(csv_path)
    except Exception as e:
        log("ERROR", f"CSV 로드 실패: {e}")
        return 2

    alerts_up, alerts_down, errors = [], [], []

    for _, row in df.iterrows():
        name = str(row.get("company_name", "")).strip()
        ticker = str(row.get("ticker", "")).strip()
        lower = parse_threshold(row.get("price_down"))
        upper = parse_threshold(row.get("price_up"))

        if not ticker:
            continue

        price = fetch_price(ticker)
        log("INFO", f"{ticker} 현재가={price} (down={lower}, up={upper})")

        if price is None:
            errors.append((name, ticker))
            continue

        if upper is not None and price >= upper:
            alerts_up.append((name, ticker, price, upper))

        if lower is not None and price <= lower:
            alerts_down.append((name, ticker, price, lower))

    if alerts_up:
        print("[상한 돌파] (현재가 ≥ 상한)")
        for name, ticker, price, upper in alerts_up:
            print(f"- {name} ({ticker}): {format_price(price)} ≥ {format_price(upper)}")
        print()

    if alerts_down:
        print("[하한 돌파] (현재가 ≤ 하한)")
        for name, ticker, price, lower in alerts_down:
            print(f"- {name} ({ticker}): {format_price(price)} ≤ {format_price(lower)}")
        print()

    if errors:
        print("[가격 조회 오류/불명확]")
        for name, ticker in errors:
            print(f"- {name} ({ticker})")
        print()

    # 알림이 있든 없든 정상 종료
    return 0


if __name__ == "__main__":
    csv = sys.argv[1].strip() if len(sys.argv) > 1 and sys.argv[1].strip() else DEFAULT_TICKER_CSV
    try:
        sys.exit(main(csv))
    except KeyboardInterrupt:
        sys.exit(130)
    except Exception as e:
        log("ERROR", f"비정상 종료: {e}")
        log("DEBUG", traceback.format_exc())
        sys.exit(1)
