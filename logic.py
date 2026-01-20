"""
프로젝트: 배당 팽이 (Dividend Top) v3.1
파일명: logic.py
설명: 데이터 크롤링 엔진 (해외 배당률 단위 보정 + 국내 현재가 조회 네이버 백업 추가)
"""

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
import json
from github import Github
from logger import logger
import sqlite3

# -----------------------------------------------------------
# [SECTION 1] 날짜 및 스케줄링 헬퍼
# -----------------------------------------------------------

def parse_dividend_date(date_str):
    s = str(date_str).strip()
    today = datetime.date.today()
    try:
        return datetime.datetime.strptime(s, "%Y-%m-%d").date()
    except ValueError:
        pass
    
    day_match = re.search(r'(\d+)', s)
    if day_match and ('매월' in s or '일' in s):
        try:
            day = int(day_match.group(1))
            target_date = datetime.date(today.year, today.month, day)
            if target_date < today:
                next_month = today.month + 1 if today.month < 12 else 1
                year = today.year if today.month < 12 else today.year + 1
                try:
                    return datetime.date(year, next_month, day)
                except ValueError:
                    last_day = calendar.monthrange(year, next_month)[1]
                    return datetime.date(year, next_month, last_day)
            return target_date
        except ValueError:
            pass
    return None 

def generate_portfolio_ics(portfolio_data):
    ics_content = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//DividendPange//Portfolio//KO",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH"
    ]
    today = datetime.date.today()
    current_year = today.year
    
    for item in portfolio_data:
        name = item.get('종목', '배당주')
        date_info = str(item.get('배당락일', '-'))
        day_match = re.search(r'(\d+)', date_info)
        
        if day_match and ('매월' in date_info or '일' in date_info):
            day = int(day_match.group(1))
            for i in range(12):
                month = today.month + i
                year = current_year + (month - 1) // 12
                month = (month - 1) % 12 + 1
                try:
                    last_day = calendar.monthrange(year, month)[1]
                    safe_day = min(day, last_day)
                    event_date = datetime.date(year, month, safe_day)
                    buy_date = event_date - datetime.timedelta(days=4)
                    while buy_date.weekday() >= 5: buy_date -= datetime.timedelta(days=1)
                    
                    dt_start = buy_date.strftime("%Y%m%d")
                    dt_end = (buy_date + datetime.timedelta(days=1)).strftime("%Y%m%d")
                    ics_content.extend([
                        "BEGIN:VEVENT",
                        f"DTSTART;VALUE=DATE:{dt_start}",
                        f"DTEND;VALUE=DATE:{dt_end}",
                        f"SUMMARY:🔔 [{name}] 배당락 D-4 (매수 권장)",
                        f"DESCRIPTION:예상 배당락일: {event_date}\\n안전하게 오늘 매수하세요!",
                        "END:VEVENT"
                    ])
                except ValueError: continue
    ics_content.append("END:VCALENDAR")
    return "\n".join(ics_content)

def get_google_cal_url(stock_name, date_str):
    try:
        target_date = parse_dividend_date(date_str)
        if not target_date: return None
        if isinstance(target_date, datetime.date):
            safe_buy_date = target_date - datetime.timedelta(days=4) 
        else: return None
        while safe_buy_date.weekday() >= 5: safe_buy_date -= datetime.timedelta(days=1)
        start_str = safe_buy_date.strftime("%Y%m%d")
        end_str = (safe_buy_date + datetime.timedelta(days=1)).strftime("%Y%m%d")
        base_url = "https://www.google.com/calendar/render?action=TEMPLATE"
        title = quote(f"🔔 [{stock_name}] 배당락 D-4")
        details = quote(f"예상 배당락일: {date_str}\n안전하게 오늘 매수하세요!")
        return f"{base_url}&text={title}&dates={start_str}/{end_str}&details={details}"
    except: return None


# -----------------------------------------------------------
# [SECTION 2] 시세 조회 및 유틸리티
# -----------------------------------------------------------

def _fetch_naver_price(code):
    """[NEW] 네이버 모바일 API로 현재가 조회 (한투 실패 시 백업용)"""
    try:
        headers = {
            "User-Agent": "Mozilla/5.0",
            "Referer": "https://m.stock.naver.com/"
        }
        # ETF 시도
        url = f"https://api.stock.naver.com/etf/{code}/basic"
        res = requests.get(url, headers=headers, timeout=2)
        if res.status_code == 200:
            data = res.json()
            if 'closePrice' in data: return int(data['closePrice'])
            
        # 주식 시도
        url = f"https://api.stock.naver.com/stock/{code}/basic"
        res = requests.get(url, headers=headers, timeout=2)
        if res.status_code == 200:
            data = res.json()
            if 'closePrice' in data: return int(data['closePrice'])
    except:
        pass
    return 0

def _fetch_price_raw(broker, code, category):
    try:
        code_str = str(code).strip()
        
        # 1. 국내: 한투 API -> 실패 시 네이버 API
        if category == '국내':
            try:
                resp = broker.fetch_price(code_str)
                if resp and isinstance(resp, dict) and 'output' in resp:
                    if resp['output'].get('stck_prpr'): return int(resp['output']['stck_prpr'])
            except: pass
            
            # [백업] 네이버에서 가격 가져오기
            return _fetch_naver_price(code_str)
        
        # 2. 해외: Yfinance
        ticker_code = f"{code_str}.KS" if category == '국내' else code_str
        max_retries = 3
        for attempt in range(max_retries):
            try:
                ticker = yf.Ticker(ticker_code)
                price = ticker.fast_info.get('last_price')
                if not price:
                    hist = ticker.history(period="1d")
                    if not hist.empty: price = hist['Close'].iloc[-1]
                if price: return float(price)
            except sqlite3.OperationalError: 
                if attempt < max_retries - 1: time.sleep(0.5); continue
            except: break
        return None
    except: return None

def get_safe_price(broker, code, category):
    for _ in range(2):
        price = _fetch_price_raw(broker, code, category)
        if price and price > 0: return price
        time.sleep(0.3)
    return None

def classify_asset(row):
    name, symbol = str(row.get('종목명', '')).upper(), str(row.get('종목코드', '')).upper()
    if any(k in name or k in symbol for k in ['커버드콜', 'COVERED', 'QYLD', 'JEPI', 'JEPQ', 'NVDY', 'TSLY', 'QQQI']): return '🛡️ 커버드콜'
    if any(k in name or k in symbol for k in ['채권', '국채', 'BOND', 'TLT', '하이일드']): return '🏦 채권형'
    if '리츠' in name or 'REITS' in name or 'INFRA' in name: return '🏢 리츠형'
    return '📈 주식형'

def get_hedge_status(name, category):
    name_str = str(name).upper()
    if category == '해외': return "💲달러(직투)"
    if "환노출" in name_str or "UNHEDGED" in name_str: return "⚡환노출"
    if any(x in name_str for x in ["(H)", "헤지"]): return "🛡️환헤지(H)"
    return "⚡환노출" if any(x in name_str for x in ['미국', 'GLOBAL']) else "-"


# -----------------------------------------------------------
# [SECTION 3] 메인 데이터 로드 및 병렬 처리
# -----------------------------------------------------------

@st.cache_data(ttl=1800, show_spinner=False)
def load_and_process_data(df_raw, is_admin=False):
    if df_raw.empty: return pd.DataFrame()
    try:
        num_cols = ['연배당금', '연배당률', '현재가', '신규상장개월수', '연배당금_크롤링']
        for col in num_cols:
            if col in df_raw.columns: df_raw[col] = pd.to_numeric(df_raw[col], errors='coerce').fillna(0)
        if '종목코드' in df_raw.columns:
            df_raw['종목코드'] = df_raw['종목코드'].apply(lambda x: str(x).split('.')[0].strip().zfill(6) if str(x).split('.')[0].strip().isdigit() else str(x).upper())
        if '배당락일' in df_raw.columns: df_raw['배당락일'] = df_raw['배당락일'].astype(str).replace(['nan', 'None'], '-')
        if '자산유형' in df_raw.columns: df_raw['자산유형'] = df_raw['자산유형'].fillna('기타')
    except: pass

    try:
        broker = mojito.KoreaInvestment(
            api_key=st.secrets["kis"]["app_key"],
            api_secret=st.secrets["kis"]["app_secret"],
            acc_no=st.secrets["kis"]["acc_no"],
            mock=True 
        )
    except: broker = None

    results = [None] * len(df_raw)
    
    def process_row(idx, row):
        try:
            code = str(row.get('종목코드', '')).strip()
            name = str(row.get('종목명', '')).strip()
            category = str(row.get('분류', '국내')).strip()
            
            price = get_safe_price(broker, code, category)
            if not price: price = 0 

            crawled_div = float(row.get('연배당금_크롤링', 0))
            manual_div = float(row.get('연배당금', 0))        
            months = int(row.get('신규상장개월수', 0))

            if 0 < months < 12:
                target_div = (manual_div / months * 12) if manual_div > 0 else crawled_div
                display_name = f"{name} ⭐"
            else:
                target_div = crawled_div if crawled_div > 0 else manual_div
                display_name = name

            yield_val = (target_div / price * 100) if price > 0 else 0
            if is_admin and (yield_val < 2.0 or yield_val > 25.0): display_name = f"🚫 {display_name}"
            price_fmt = f"{int(price):,}원" if category == '국내' else f"${price:.2f}"
            
            auto_asset_type = classify_asset(row) 
            final_type = str(row.get('유형', '-'))
            if '채권' in auto_asset_type: final_type = '채권'
            elif '커버드콜' in auto_asset_type: final_type = '커버드콜'
            elif '리츠' in auto_asset_type: final_type = '리츠'

            return idx, {
                '코드': code, 
                '종목명': display_name,
                '블로그링크': str(row.get('블로그링크', '#')),
                '금융링크': f"https://finance.naver.com/item/main.naver?code={code}" if category == '국내' else f"https://finance.yahoo.com/quote/{code}",
                '현재가': price_fmt, 
                '연배당률': yield_val,
                '환구분': get_hedge_status(name, category),
                '배당락일': str(row.get('배당락일', '-')), 
                '분류': category,
                '유형': final_type, 
                '자산유형': auto_asset_type,
                '캘린더링크': None, 
                'pure_name': name.replace("🚫 ", "").replace(" (필터대상)", ""), 
                '신규상장개월수': months,
                '배당기록': str(row.get('배당기록', '')),
                '검색라벨': str(row.get('검색라벨', f"[{code}] {display_name}"))
            }
        except: return idx, None

    with ThreadPoolExecutor(max_workers=10) as executor:
        futures = {executor.submit(process_row, idx, row): idx for idx, row in df_raw.iterrows()}
        for future in as_completed(futures):
            idx, result = future.result()
            results[idx] = result

    final_data = [r for r in results if r is not None]
    return pd.DataFrame(final_data).sort_values('연배당률', ascending=False) if final_data else pd.DataFrame()


# -----------------------------------------------------------
# [SECTION 4] 데이터 파일 관리
# -----------------------------------------------------------

@st.cache_data(ttl=1800)
def load_stock_data_from_csv():
    import os
    file_path = "stocks.csv"
    for _ in range(3):
        try:
            if not os.path.exists(file_path): return pd.DataFrame()
            df = pd.read_csv(file_path, dtype={'종목코드': str})
            df.columns = df.columns.str.strip()
            if '연배당금_크롤링' not in df.columns: df['연배당금_크롤링'] = 0.0
            return df
        except: time.sleep(0.5)
    return pd.DataFrame()

def save_to_github(df):
    try:
        token = st.secrets["github"]["token"]
        repo_name = st.secrets["github"]["repo_name"]
        file_path = st.secrets["github"]["file_path"]
        g = Github(token)
        repo = g.get_repo(repo_name)
        contents = repo.get_contents(file_path)
        csv_data = df.to_csv(index=False).encode("utf-8")
        repo.update_file(path=contents.path, message="🤖 데이터 자동 갱신", content=csv_data, sha=contents.sha)
        return True, "✅ 깃허브 저장 성공!"
    except Exception as e: return False, f"❌ 저장 실패: {str(e)}"


# -----------------------------------------------------------
# [SECTION 6] 실시간 배당 정보 크롤링 (Hybrid)
# -----------------------------------------------------------

def fetch_dividend_yield_hybrid(code, category):
    """
    네이버 모바일 '배당 내역(History)' API 직접 집계 + 야후 보정 적용
    """
    code = str(code).strip()
    
    # 1. [국내 주식] 네이버 모바일 API
    if category == '국내':
        HEADERS_MOBILE = {
            "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 15_0 like Mac OS X)",
            "Accept": "application/json, text/plain, */*",
            "Referer": "https://m.stock.naver.com/"
        }
        
        # 1-1. 현재가 확보 (한투 -> 네이버 백업)
        current_price = 0
        try:
            broker = mojito.KoreaInvestment(
                api_key=st.secrets["kis"]["app_key"],
                api_secret=st.secrets["kis"]["app_secret"],
                acc_no=st.secrets["kis"]["acc_no"],
                mock=True 
            )
            resp = broker.fetch_price(code)
            if resp and 'output' in resp:
                current_price = int(resp['output'].get('stck_prpr', 0))
        except: pass
        
        if current_price == 0:
            current_price = _fetch_naver_price(code)
        
        if current_price == 0: return 0.0, "⚠️ 현재가 조회 실패"

        # 1-2. 배당 내역 집계
        urls = [f"https://m.stock.naver.com/api/etf/{code}/dividend/history", f"https://m.stock.naver.com/api/stock/{code}/dividend/history"]
        total_dividend = 0
        found_source = ""
        
        for url in urls:
            try:
                res = requests.get(url, params={"page": 1, "pageSize": 50}, headers=HEADERS_MOBILE, timeout=5)
                if res.status_code == 200:
                    data = res.json()
                    items = []
                    if 'result' in data and 'items' in data['result']: items = data['result']['items']
                    elif 'items' in data: items = data['items']
                        
                    if items:
                        real_total = 0; limit = 12; collected = 0
                        for it in items:
                            val = None
                            for k in ['dividend', 'dividendAmount', 'amount']:
                                if k in it and it[k]: val = it[k]; break
                            if val:
                                try:
                                    real_total += int(float(str(val).replace(',', '')))
                                    collected += 1
                                except: pass
                            if collected >= limit: break
                        if real_total > 0:
                            total_dividend = real_total; found_source = "✅ 네이버(History)"; break
            except: pass
        
        if total_dividend > 0:
            yield_val = (total_dividend / current_price) * 100
            return round(yield_val, 2), found_source
            
        return 0.0, "⚠️ 데이터 없음 (국내)"

    # 2. [해외 주식] 야후 파이낸스 (보정 로직 추가)
    else:
        try:
            stock = yf.Ticker(code)
            dy = stock.info.get('dividendYield')
            if dy and dy > 0: 
                # 🚨 [보정] 50% 이상이면 100으로 나눔 (738% -> 7.38%)
                calc_val = dy * 100
                if calc_val > 50: calc_val = dy
                return round(calc_val, 2), "✅ 야후(Info)"
            return 0.0, "⚠️ 데이터 없음"
        except:
            return 0.0, "❌ 해외 에러"

def update_dividend_rolling(current_history_str, new_dividend_amount):
    if pd.isna(current_history_str) or str(current_history_str).strip() == "": history = []
    else:
        try: history = [int(float(x)) for x in str(current_history_str).split('|') if x.strip()]
        except: history = []
    if len(history) >= 12: history.pop(0)
    history.append(int(new_dividend_amount))
    return sum(history), "|".join(map(str, history))
