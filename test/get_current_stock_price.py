#!/usr/bin/env python3
# yfinance를 사용하여 삼성바이오로직스(207940.KS)의 
# 현재 시세(regularMarketPrice)를 조회해 출력하는 코드

import yfinance as yf

# 삼성바이오로직스 티커
ticker = "207940.KS"

# 티커 객체 생성
stock = yf.Ticker(ticker)

# 현재 시세 가져오기
info = stock.info
current_price = info.get("regularMarketPrice")

print(f"삼성바이오로직스 현재가: {current_price:,.2f} KRW")
