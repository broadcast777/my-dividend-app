"""
프로젝트: 배당 팽이 (Dividend Top) v3.1
파일명: logic.py
설명: 금융 API 연동, TTM 직접 계산 로직 추가 (액티브 ETF 완벽 대응)
업데이트: 2026.01.23
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
import base64
import json
from github import Github
import sqlite3
from playwright.sync_api import sync_playwright
import os
import subprocess
import logging
from bs4 import BeautifulSoup

# -----------------------------------------------------------
# 로거 설정
# -----------------------------------------------------------
if not logging.getLogger().handlers:
    logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# -----------------------------------------------------------
# [SECTION 0] TTM 데이터 확보 (API 계산기 + Playwright)
# -----------------------------------------------------------

def _ensure_browser_installed():
    """브라우저가 없으면 자동으로 설치 명령어를 실행합니다."""
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            try:
                p.chromium.launch(headless=True)
            except Exception:
                # logger.info("⚠️ 브라우저가 없어서 자동 설치를 시작합니다...")
                subprocess.run(["playwright", "install", "chromium"], check=True)
    except Exception:
        pass

def get_ttm_or_calculate(code):
    """
    [최종 솔루션]
    1. 네이버 배당 내역 API를 호출하여 최근 1년치 배당금을 '직접 합산'합니다. (가장 정확)
    2. 실패 시, 화면 크롤링(Playwright)을 시도합니다.
    """
    code = str(code).strip()
    
    # -----------------------------------------------------------
    # [1단계] 네이버 배당 내역 API로 TTM 직접 계산 (필살기)
    # -----------------------------------------------------------
    try:
        # 1. 현재가 조회 (계산용)
        price_url = f"https://api.stock.naver.com/etf/{code}/basic"
        price_res = requests.get(price_url, timeout=3, headers={"User-Agent": "Mozilla/5.0"})
        current_price = 0
        if price_res.status_code == 200:
            p_data = price_res.json()
            if 'result' in p_data and 'closePrice' in p_data['result']:
                current_price = float(p_data['result']['closePrice'])

        # 2. 배당 내역 조회
        hist_url = f"https://m.stock.naver.com/api/etf/{code}/dividend/history?pageSize=20"
        res = requests.get(hist_url, timeout=5, headers={"User-Agent": "Mozilla/5.0"})
        
        if res.status_code == 200 and current_price > 0:
            data = res.json()
            items = []
            
            # JSON 구조 파싱 (네이버 API 구조 대응)
            if isinstance(data, list): items = data
            elif isinstance(data, dict):
                items = data.get('result', []) or data.get('items', [])
            
            if items:
                ttm_sum = 0
                # 오늘 기준 1년 전 날짜
                cutoff_date = (datetime.date.today() - datetime.timedelta(days=365)).strftime("%Y%m%d")
                
                for item in items:
                    # 날짜 확인 (paymentDate or dividendDate)
                    d_date = item.get('paymentDate') or item.get('dividendDate') or ""
                    d_date = str(d_date).replace(".", "")
                    
                    # 금액 확인
                    amt = item.get('dividendAmount') or item.get('amount') or 0
                    
                    if d_date >= cutoff_date:
                        ttm_sum += float(amt)
                
                if ttm_sum > 0:
                    # 수익률 계산: (1년 합계 / 현재가) * 100
                    final_yield = round((ttm_sum / current_price) * 100, 2)
                    return final_yield, f"✅ API계산({ttm_sum}원/{final_yield}%)"

    except Exception:
        pass # 계산 실패 시 크롤링으로 넘어감

    # -----------------------------------------------------------
    # [2단계] Playwright (브라우저 크롤링 - 최후의 수단)
    # -----------------------------------------------------------
    yield_val = 0.0
    try:
        yield_val, msg = _run_crawling(code)
        if yield_val > 0: return yield_val, msg
    except Exception as e:
        if "Executable" in str(e) or "browser" in str(e):
            _ensure_browser_installed()
            try:
                return _run_crawling(code)
            except:
                pass
        pass
        
    return 0.0, ""

def _run_crawling(code):
    """실제 크롤링 로직 (내부용)"""
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--no-sandbox"])
        context = browser.new_context(user_agent="Mozilla/5.0 (iPhone; CPU iPhone OS 15_0 like Mac OS X)")
        page = context.new_page()
        
        url = f"https://m.stock.naver.com/item/main.nhn#/stocks/{code}"
        page.goto(url, timeout=30000)
        page.wait_for_timeout(3000)
        
        page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        page.wait_for_timeout(1000)
        
        body_text = page.inner_text("body")
        
        pattern = re.compile(r'(?:배당수익률|분배금수익률).*?([\d\.]+)\s*%', re.DOTALL)
        match = pattern.search(body_text)
        
        browser.close()
        
        if match:
            val = float(match.group(1))
            return val, f"✅ 웹크롤링({val}%)"
            
    return 0.0, ""


# -----------------------------------------------------------
# [SECTION 1] 날짜 및 스케줄링 헬퍼
# -----------------------------------------------------------

def standardize_date_format(date_str):
    s = str(date_str).strip()
    if re.match(r'^\d{4}-\d{2}-\d{2}$', s): return s
    s = s.replace('.', '-').replace('/', '-')
    match = re.match(r'^(\d{4})-(\d{1,2})-(\d{1,2})$', s)
    if match:
        y, m, d = match.groups()
        return f"{y}-{m.zfill(2)}-{d.zfill(2)}"
    return s

def parse_dividend_date(date_str):
    s = standardize_date_format(str(date_str))
    today = datetime.date.today()
    try: return datetime.datetime.strptime(s, "%Y-%m-%d").date()
    except ValueError: pass
    
    is_end_of_month = any(k in s for k in ['말일', '월말', '마지막', '하순', 'END'])
    is_start_of_month = any(k in s for k in ['매월 초', '월초', '1~3일', 'BEGIN'])
    day_match = re.search(r'(\d+)', s)
    
    if is_end_of_month or is_start_of_month or (day_match and ('매월' in s or '일' in s)):
        try:
            if is_end_of_month: day = calendar.monthrange(today.year, today.month)[1]
            elif is_start_of_month: day = 1 
            else: day = int(day_match.group(1))
            
            try:
                last_day_actual = calendar.monthrange(today.year, today.month)[1]
                safe_day = min(day, last_day_actual)
                target_date = datetime.date(today.year, today.month, safe_day)
            except ValueError: target_date = today
            
            if target_date < today:
                next_month = today.month + 1 if today.month < 12 else 1
                year = today.year if today.month < 12 else today.year + 1
                last_day_next = calendar.monthrange(year, next_month)[1]
                if is_end_of_month: real_day = last_day_next
                elif is_start_of_month: real_day = 1
                else: real_day = min(day, last_day_next)
                return datetime.date(year, next_month, real_day)
            return target_date
        except Exception: pass
    return None 

def generate_portfolio_ics(portfolio_data):
    ics_content = [
        "BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//DividendPange//Portfolio//KO",
        "CALSCALE:GREGORIAN", "METHOD:PUBLISH"
    ]
    today = datetime.date.today()
    current_year = today.year
    
    for item in portfolio_data:
        name = item.get('종목', '배당주')
        date_info = str(item.get('배당락일', '-')).strip()
        if date_info in ['-', 'nan', 'None', '']: continue

        is_end_of_month = any(k in date_info for k in ['말일', '월말', '마지막', '30일', '31일', '하순'])
        is_start_of_month = any(k in date_info for k in ['매월 초', '월초', '1~3일'])
        day_match = re.search(r'(\d+)', date_info)
        
        target_day = None
        if is_end_of_month: target_day = 'END'
        elif is_start_of_month: target_day = 1
        elif day_match: target_day = int(day_match.group(1))
        
        fixed_date_obj = None
        if '-' in date_info or '.' in date_info:
             parsed = parse_dividend_date(date_info)
             if parsed: fixed_date_obj = parsed

        if target_day is not None or fixed_date_obj:
            check_idx = 0
            while check_idx < 12:
                month_calc = today.month + check_idx
                year = current_year + (month_calc - 1) // 12
                month = (month_calc - 1) % 12 + 1
                check_idx += 1 
                if year > current_year: break
                
                try:
                    last_day_of_month = calendar.monthrange(year, month)[1]
                    if target_day == 'END': safe_day = last_day_of_month
                    elif isinstance(target_day, int): safe_day = min(target_day, last_day_of_month)
                    else: continue
                    
                    event_date = datetime.date(year, month, safe_day)
                    buy_date = event_date - datetime.timedelta(days=4)
                    while buy_date.weekday() >= 5: buy_date -= datetime.timedelta(days=1)
                    if buy_date < today: continue
                        
                    dt_start = buy_date.strftime("%Y%m%d")
                    dt_end = (buy_date + datetime.timedelta(days=1)).strftime("%Y%m%d")
                    description = (f"예상 배당락일: {event_date}\\n\\n💰 [{name}] 배당 수령 확인 요망.")
                    
                    ics_content.extend([
                        "BEGIN:VEVENT", f"DTSTART;VALUE=DATE:{dt_start}", f"DTEND;VALUE=DATE:{dt_end}",
                        f"SUMMARY:🔔 [{name}] 배당락 D-4", f"DESCRIPTION:{description}", "END:VEVENT"
                    ])
                except ValueError: continue

    ics_content.append("END:VCALENDAR")
    return "\n".join(ics_content)

def get_google_cal_url(stock_name, date_str):
    try:
        target_date = parse_dividend_date(date_str)
        if not target_date or not isinstance(target_date, datetime.date): return None
        safe_buy_date = target_date - datetime.timedelta(days=4) 
        while safe_buy_date.weekday() >= 5: safe_buy_date -= datetime.timedelta(days=1)
        start_str = safe_buy_date.strftime("%Y%m%d")
        end_str = (safe_buy_date + datetime.timedelta(days=1)).strftime("%Y%m%d")
        base_url = "https://www.google.com/calendar/render?action=TEMPLATE"
        title = quote(f"🔔 [{stock_name}] 배당락 D-4")
        details = quote(f"예상 배당락일: {date_str}\n\n💰 배당 수령 준비.")
        return f"{base_url}&text={title}&dates={start_str}/{end_str}&details={details}"
    except: return None


# -----------------------------------------------------------
# [SECTION 2] 시세 조회 및 유틸리티 함수
# -----------------------------------------------------------

def _fetch_naver_price(code):
    try:
        headers = {"User-Agent": "Mozilla/5.0", "Referer": "https://m.stock.naver.com/"}
        url = f"https://api.stock.naver.com/etf/{code}/basic"
        res = requests.get(url, headers=headers, timeout=2)
        if res.status_code == 200:
            data = res.json()
            if 'result' in data and 'closePrice' in data['result']:
                return int(data['result']['closePrice'])
    except: pass
    return 0
    
def _fetch_price_raw(broker, code, category):
    try:
        code_str = str(code).strip()
        if category == '국내':
            try:
                resp = broker.fetch_price(code_str)
                if resp and isinstance(resp, dict) and 'output' in resp:
                    return int(resp['output'].get('stck_prpr', 0))
            except: pass
        
        ticker_code = f"{code_str}.KS" if category == '국내' else code_str
        for attempt in range(3):
            try:
                ticker = yf.Ticker(ticker_code)
                price = ticker.fast_info.get('last_price')
                if not price:
                    hist = ticker.history(period="1d")
                    if not hist.empty: price = hist['Close'].iloc[-1]
                if price: return float(price)
            except sqlite3.OperationalError: 
                time.sleep(0.5)
            except: break 
        return None
    except: return None

def get_safe_price(broker, code, category):
    for _ in range(2):
        price = _fetch_price_raw(broker, code, category)
        if price is not None: return price
        time.sleep(0.3)
    return None

def classify_asset(row):
    name, symbol = str(row.get('종목명', '')).upper(), str(row.get('종목코드', '')).upper()
    if any(k in name or k in symbol for k in ['커버드콜', 'COVERED', 'QYLD', 'JEPI', 'JEPQ']): return '🛡️ 커버드콜'
    if any(k in name or k in symbol for k in ['채권', '국채', 'BOND', 'TLT']): return '🏦 채권형'
    if '리츠' in name or 'REITS' in name or 'INFRA' in name: return '🏢 리츠형'
    if '혼합' in name: return '⚖️ 혼합형'
    return '📈 주식형'

def get_hedge_status(name, category):
    name_str = str(name).upper()
    if category == '해외': return "💲달러(직투)"
    if "환노출" in name_str or "UNHEDGED" in name_str: return "⚡환노출"
    if any(x in name_str for x in ["(H)", "헤지"]): return "🛡️환헤지(H)"
    return "⚡환노출"


# -----------------------------------------------------------
# [SECTION 3] 데이터 로드 및 처리
# -----------------------------------------------------------

@st.cache_data(ttl=1800, show_spinner=False)
def load_and_process_data(df_raw, is_admin=False):
    if df_raw.empty: return pd.DataFrame()
    try:
        num_cols = ['연배당금', '연배당률', '현재가', '신규상장개월수', '연배당금_크롤링', '연배당금_크롤링_auto', 'TTM_연배당률(크롤링)']
        for col in num_cols:
            if col in df_raw.columns: df_raw[col] = pd.to_numeric(df_raw[col], errors='coerce').fillna(0)
        
        if '종목코드' in df_raw.columns:
            df_raw['종목코드'] = df_raw['종목코드'].apply(lambda x: str(x).split('.')[0].strip().zfill(6) if str(x).isdigit() else str(x).upper())
        if '배당락일' in df_raw.columns:
            df_raw['배당락일'] = df_raw['배당락일'].astype(str).replace(['nan', 'None', 'nan '], '-')
        if '자산유형' in df_raw.columns:
            df_raw['자산유형'] = df_raw['자산유형'].fillna('기타')
    except: pass

    try:
        broker = mojito.KoreaInvestment(
            api_key=st.secrets["kis"]["app_key"], api_secret=st.secrets["kis"]["app_secret"],
            acc_no=st.secrets["kis"]["acc_no"], mock=True 
        )
    except: broker = None

    results = [None] * len(df_raw)
    
    def process_row(idx, row):
        try:
            code = str(row.get('종목코드', '')).strip()
            name = str(row.get('종목명', '')).strip()
            category = str(row.get('분류', '국내')).strip()
            price = get_safe_price(broker, code, category) or 0
            
            auto_div = float(row.get('연배당금_크롤링_auto', 0))
            manual_div = float(row.get('연배당금', 0))
            old_div = float(row.get('연배당금_크롤링', 0))
            saved_ttm_yield = float(row.get('TTM_연배당률(크롤링)', 0))

            final_div = 0
            calc_yield = 0
            status_msg = ""
            
            if auto_div > 0:
                final_div = auto_div
                calc_yield = (final_div / price * 100) if price > 0 else 0
                status_msg = "⚡ Auto"
            elif saved_ttm_yield > 0:
                calc_yield = saved_ttm_yield
                final_div = int(price * (saved_ttm_yield / 100)) if price > 0 else 0
                status_msg = f"✅ API계산({saved_ttm_yield}%)"
            elif manual_div > 0:
                final_div = manual_div
                calc_yield = (final_div / price * 100) if price > 0 else 0
                status_msg = "🔧 수동"
            elif old_div > 0:
                final_div = old_div
                calc_yield = (final_div / price * 100) if price > 0 else 0
                status_msg = "⚠️ Old"
            else: status_msg = "❌ 갱신필요"

            months = int(row.get('신규상장개월수', 0))
            if 0 < months < 12 and "수동" in status_msg:
                final_div = (manual_div / months * 12)
                calc_yield = (final_div / price * 100) if price > 0 else 0
                display_name = f"{name} ⭐"
            else: display_name = name
            
            price_fmt = f"{int(price):,}원" if category == '국내' else f"${price:.2f}"
            return idx, {
                '코드': code, '종목명': display_name, '블로그링크': str(row.get('블로그링크', '#')),
                '금융링크': f"https://finance.naver.com/item/main.naver?code={code}" if category == '국내' else f"https://finance.yahoo.com/quote/{code}",
                '현재가': price_fmt, '연배당률': round(calc_yield, 2), '환구분': get_hedge_status(name, category),
                '배당락일': str(row.get('배당락일', '-')), '분류': category, '유형': str(row.get('유형', '-')),
                '자산유형': classify_asset(row), '캘린더링크': None, 'pure_name': name,
                '신규상장개월수': months, '배당기록': str(row.get('배당기록', '')),
                '검색라벨': str(row.get('검색라벨', f"[{code}] {display_name}")), '비고': status_msg,
                '연배당금_크롤링_auto': auto_div, '연배당금': manual_div, '연배당금_크롤링': old_div,
                'TTM_연배당률(크롤링)': saved_ttm_yield 
            }
        except: return idx, None

    with ThreadPoolExecutor(max_workers=10) as executor:
        futures = {executor.submit(process_row, idx, row): idx for idx, row in df_raw.iterrows()}
        for future in as_completed(futures):
            idx, result = future.result()
            results[idx] = result
    
    final_data = [r for r in results if r is not None]
    if final_data:
        result_df = pd.DataFrame(final_data)
        if '연배당률' in result_df.columns: return result_df.sort_values('연배당률', ascending=False)
        return result_df
    return pd.DataFrame()


# -----------------------------------------------------------
# [SECTION 4] 데이터 파일 관리
# -----------------------------------------------------------

@st.cache_data(ttl=1800)
def load_stock_data_from_csv():
    file_path = "stocks.csv"
    for _ in range(3):
        try:
            if not os.path.exists(file_path): return pd.DataFrame()
            df = pd.read_csv(file_path, dtype=str, encoding='utf-8-sig')
            df.columns = [c.replace('\ufeff', '').strip() for c in df.columns]
            
            for c in ['연배당금_크롤링', '연배당금_크롤링_auto', '연배당률_크롤링', 'TTM_연배당률(크롤링)']:
                if c not in df.columns: df[c] = 0.0
            if '배당기록' not in df.columns: df['배당기록'] = ""
            if '종목코드' not in df.columns: df['종목코드'] = df.index.astype(str)
            df['종목코드'] = df['종목코드'].apply(lambda x: str(x).split('.')[0].strip().zfill(6) if str(x).isdigit() else str(x).upper())
            return df
        except: time.sleep(0.5)
    return pd.DataFrame()

def save_to_github(df):
    try:
        g = Github(st.secrets["github"]["token"])
        repo = g.get_repo(st.secrets["github"]["repo_name"])
        contents = repo.get_contents(st.secrets["github"]["file_path"])
        repo.update_file(contents.path, "🤖 데이터 자동 갱신", df.to_csv(index=False).encode("utf-8"), contents.sha)
        return True, "✅ 깃허브 저장 성공!"
    except Exception as e: return False, f"❌ 저장 실패: {str(e)}"

def reset_auto_data(code):
    try:
        df = load_stock_data_from_csv()
        idx = df[df['종목코드'] == code].index
        if not idx.empty:
            df.at[idx[0], '연배당금_크롤링_auto'] = 0.0
            df.to_csv("stocks.csv", index=False, encoding='utf-8-sig')
            return True, "초기화 완료!"
        return False, "종목 없음"
    except Exception as e: return False, f"에러: {e}"

# -----------------------------------------------------------
# [SECTION 6] 갱신 로직 (API 계산기 탑재)
# -----------------------------------------------------------

def fetch_dividend_yield_hybrid(code, category):
    code = str(code).strip()
    if category == '국내':
        # API 계산 로직과 중복되지만, 여기서는 '연배당금_크롤링_auto' 갱신용으로 사용
        # 계산은 smart_update_and_save에서 get_ttm_or_calculate로 대체
        return 0.0, "" 
    else:
        # 해외 종목 로직 유지
        try:
            ticker = yf.Ticker(code)
            divs = ticker.dividends
            if not divs.empty:
                cutoff = pd.Timestamp.now(tz=divs.index.tz) - pd.Timedelta(days=365)
                usd_sum = float(divs[divs.index >= cutoff].sum())
                price = ticker.fast_info.get('last_price')
                if not price:
                    hist = ticker.history(period="1d")
                    if not hist.empty: price = hist['Close'].iloc[-1]
                if price and price > 0:
                    yield_pct = (usd_sum / price) * 100
                    return round(yield_pct, 2), f"✅ 야후({usd_sum:.2f})"
        except: pass
        return 0.0, "⚠️ 데이터 없음"

def smart_update_and_save():
    try:
        df = load_stock_data_from_csv()
        if df.empty: return False, "CSV 없음"
        
        updated_count = 0
        skipped_count = 0
        progress_bar = st.progress(0)
        status_text = st.empty()
        total = len(df)
        
        try: _ensure_browser_installed()
        except: pass

        for idx, row in df.iterrows():
            code = str(row['종목코드']).strip()
            name = str(row['종목명']).strip()
            category = str(row.get('분류', '국내')).strip()
            progress_bar.progress((idx + 1) / total)
            status_text.text(f"검사 중: {name} ({idx+1}/{total})")
            
            try: months = int(row.get('신규상장개월수', 0))
            except: months = 0
            if 0 < months < 12:
                skipped_count += 1
                continue

            def to_float(val):
                try: return float(val)
                except: return 0.0

            current_auto = to_float(row.get('연배당금_크롤링_auto', 0))
            current_manual = to_float(row.get('연배당금', 0))
            is_locked = (current_manual > 0) and (current_auto == 0)
            
            if category == '국내':
                # 1. 일반 크롤링 (Auto) - 국내는 TTM 계산기로 통합 추천하지만 기존 로직 유지
                pass 

                # 2. TTM 갱신 (Auto가 0일 때 무조건 시도)
                # API로 직접 계산하여 TTM 컬럼 채우기
                check_auto = to_float(df.at[idx, '연배당금_크롤링_auto'])
                if check_auto == 0:
                    try:
                        # [핵심] API 계산기 호출
                        ttm_yield, _ = get_ttm_or_calculate(code)
                        if ttm_yield > 0:
                            df.at[idx, 'TTM_연배당률(크롤링)'] = float(ttm_yield)
                            if is_locked: updated_count += 1
                    except: pass

            elif category == '해외':
                if not is_locked:
                    try:
                        y_val, msg = fetch_dividend_yield_hybrid(code, category)
                        if y_val > 0:
                            df.at[idx, '연배당률_크롤링'] = y_val
                            # 금액 추출
                            m = re.search(r'\(([\d\.]+)', msg)
                            if m: df.at[idx, '연배당금_크롤링_auto'] = float(m.group(1))
                            updated_count += 1
                    except: pass

        df.to_csv("stocks.csv", index=False, encoding='utf-8-sig')
        if "github" in st.secrets: save_to_github(df)
            
        status_text.empty()
        progress_bar.empty()
        return True, f"✅ 스마트 갱신 완료! ({updated_count}개 업데이트)"
        
    except Exception as e: return False, f"오류: {e}"

def update_dividend_rolling(current_history_str, new_dividend_amount):
    try: history = [int(float(x)) for x in str(current_history_str).split('|') if x.strip()]
    except: history = []
    if len(history) >= 12: history.pop(0)
    history.append(int(new_dividend_amount))
    return sum(history), "|".join(map(str, history))
