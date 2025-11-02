#!/usr/bin/env python3
# yfinance를 사용하여 삼성바이오로직스(207940.KS)의 현재 시세를 조회해 출력하는 코드
# fast_info / info 방식 중 선택하여 조회 가능

import yfinance as yf

# 삼성바이오로직스 티커
ticker = "207940.KS"

# 조회 방식 선택: "fast_info" 또는 "info"
info_type = "info"   # ← "fast_info" 또는 "info" 로 변경 가능

# 티커 객체 생성
stock = yf.Ticker(ticker)

# fast_info vs. info 
# fast_info → 가볍고 빠른 핵심 데이터 전용
# info → 기업/재무/시장 등 방대한 전체 정보, 속도 느리고 종종 깨짐

# info를 미리 가져오기 (if문 내부에는 current_price 설정만)
fast_price = stock.fast_info.last_price
info_data = stock.info
info_price = info_data.get("regularMarketPrice")

if info_type == "fast_info":
    current_price = fast_price
elif info_type == "info":
    current_price = info_price
else:
    raise ValueError("info_type must be either 'fast_info' or 'info'")

print(f"[{info_type}] 삼성바이오로직스 현재가: {current_price:,.2f} KRW")
