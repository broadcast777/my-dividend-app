import streamlit as st
import pandas as pd
import yfinance as yf
from concurrent.futures import ThreadPoolExecutor, as_completed
import time
import mojito 
import datetime 
import calendar 
from urllib.parse import quote
import re
import requests
from github import Github

# ==========================================
# [1] 시세 조회 및 유틸리티 (Global Scope - 최상단 배치)
# ==========================================

def _fetch_price_raw(broker, code, category):
    """실제 가격 정보를 1회 조회하는 하위 부품"""
    try:
        code_str = str(code).strip().zfill(6) if category == '국내' else str(code).strip()
        if category == '국내':
            try:
                resp = broker.fetch_price(code_str)
                if resp and isinstance(resp, dict) and 'output' in resp:
                    if resp['output'] and resp['output'].get('stck_prpr'):
                        return int(resp['output']['stck_prpr'])
            except: pass
        
        ticker_code = f"{code_str}.KS" if category == '국내' else code_str
        ticker = yf.Ticker(ticker_code)
        price = ticker.fast_info.get('last_price')
        if not price:
            hist = ticker.history(period="1d")
            if not hist.empty: price = hist['Close'].iloc[-1]
        return float(price) if price else None
    except: return None

def get_safe_price(broker, code, category):
    """[복구 완료] 시세를 2번 시도해서 안전하게 가져오는 함수"""
    for _ in range(2):
        price = _fetch_price_raw(broker, code, category)
        if price is not None: return price
        time.sleep(0.5)
    return None

def classify_asset(row):
    name, symbol = str(row.get('종목명', '')).upper(), str(row.get('종목코드', '')).upper()
    if any(k in name or k in symbol for k in ['커버드콜', 'COVERED', 'QYLD', 'JEPI', 'JEPQ', 'NVDY', 'TSLY', 'QQQI']): return '🛡️ 커버드콜'
    if '혼합' in name: return '⚖️ 혼합형'
    if any(k in name or k in symbol for k in ['채권', '국채', 'BOND', 'TLT', '하이일드','SPHY', 'BIL', 'SHV', 'T-Bill']): return '🏦 채권형'
    if '리츠' in name or 'REITS' in name: return '🏢 리츠형'
    return '📈 주식형'

def get_hedge_status(name, category):
    name_str = str(name).upper()
    if category == '해외': return "💲달러(직투)"
    if "환노출" in name_str or "UNHEDGED" in name_str: return "⚡환노출"
    if any(x in name_str for x in ["(H)", "헤지", "합성"]): return "🛡️환헤지(H)"
    return "⚡환노출" if any(x in name_str for x in ['미국', 'GLOBAL', 'S&P500', '나스닥']) else "-"

# ==========================================
# [2] 배당금액 기반 정밀 연산 엔진 (직접 계산 방식)
# ==========================================

def fetch_dividend_yield_hybrid(code, category):
    """
    [어제 성공 로직 + 모바일 API 우회]
    배당률(%)이 아닌 배당금(원/$)을 긁어와서 현재가로 직접 계산
    """
    code_str = str(code).strip().zfill(6)
    
    # 1. 시세 확보 (야후가 차단이 덜함)
    try:
        ticker_code = f"{code_str}.KS" if (category == '국내' and code_str.isdigit()) else code_str
        stock = yf.Ticker(ticker_code)
        curr_price = stock.fast_info.get('last_price') or 0
    except: curr_price = 0

    if category == '국내':
        try:
            # 네이버 모바일 API (차단 우회 신분증 장착)
            url = f"https://m.stock.naver.com/api/stock/{code_str}/integration"
            headers = {'User-Agent': 'Mozilla/5.0 (iPhone; CPU iPhone OS 15_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/15.0 Mobile/15E148 Safari/604.1'}
            res = requests.get(url, headers=headers, timeout=5)
            
            if res.status_code == 200:
                data = res.json()
                # 'dividend'는 원 단위의 금액입니다.
                div_amt = data.get('totalInfo', {}).get('dividend')
                
                if div_amt and curr_price > 0:
                    div_amt = float(str(div_amt).replace(',', ''))
                    # 직접 계산: (배당금 / 현재가) * 100
                    return round((div_amt / curr_price) * 100, 2), "네이버(M)"
                
                # 금액이 없으면 비율이라도 가져옴
                yld = data.get('totalInfo', {}).get('dividendYield')
                if yld: return float(yld), "네이버(M-비율)"
        except: pass
        return 0.0, "조회실패"

    else: # 해외 종목
        try:
            # 야후에서 dividendRate(금액) 확인
            info = stock.info
            div_rate = info.get('dividendRate')
            if div_rate and curr_price > 0:
                return round((div_rate / curr_price) * 100, 2), "야후(금액)"
            
            dy = info.get('dividendYield')
            if dy: return round(dy * 100, 2), "야후(비율)"
        except: pass
        return 0.0, "조회실패"

# ==========================================
# [3] 데이터 로드 및 캘린더 (Global Scope)
# ==========================================

@st.cache_data(ttl=600, show_spinner=False)
def load_and_process_data(df_raw, is_admin=False):
    if df_raw.empty: return pd.DataFrame()
    try:
        broker = mojito.KoreaInvestment(api_key=st.secrets["kis"]["app_key"], api_secret=st.secrets["kis"]["app_secret"], acc_no=st.secrets["kis"]["acc_no"], mock=True)
    except: return pd.DataFrame()

    results = [None] * len(df_raw)
    def process_row(idx, row):
        code, name, category = str(row.get('종목코드', '')).strip(), str(row.get('종목명', '')).strip(), str(row.get('분류', '국내')).strip()
        # [복구 확인] 이제 Global Scope에 있는 get_safe_price를 호출합니다.
        price = get_safe_price(broker, code, category)
        if not price: return idx, None
        
        try: months = int(row.get('신규상장개월수', 0))
        except: months = 0

        if 0 < months < 12:
            yield_val = ((float(row.get('연배당금', 0)) / months) * 12 / price) * 100
            display_name = f"{name} ⭐"
        elif '연배당률' in row and pd.notnull(row['연배당률']) and str(row['연배당률']).strip() != "":
            yield_val = float(row['연배당률'])
            display_name = name
        else:
            yield_val = (float(row.get('연배당금', 0)) / price) * 100
            display_name = name

        return idx, {
            '코드': code, '종목명': display_name, '현재가': f"{int(price):,}원" if category == '국내' else f"${price:.2f}",
            '연배당률': yield_val, '환구분': get_hedge_status(name, category), '배당락일': str(row.get('배당락일', '-')),
            '분류': category, '자산유형': classify_asset(row), 'pure_name': name,
            '캘린더링크': calculate_google_calendar_url(display_name, str(row.get('배당락일', '-')))
        }

    with ThreadPoolExecutor(max_workers=5) as executor:
        futures = {executor.submit(process_row, idx, row): idx for idx, row in df_raw.iterrows()}
        for f in as_completed(futures):
            idx, res = f.result()
            results[idx] = res

    final = [r for r in results if r is not None]
    return pd.DataFrame(final).sort_values('연배당률', ascending=False)

# ... (나머지 calculate_google_calendar_url, load_stock_data_from_csv, 
#      update_dividend_rolling, generate_portfolio_ics, save_to_github 등은 동일하게 유지)
