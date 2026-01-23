"""
프로젝트: 배당 팽이 (Dividend Top) v2.9
파일명: logic.py
설명: 금융 API 연동, 데이터 크롤링, 캘린더 파일 생성 (브라우저 자동 설치 및 해외 자동화 패치 적용)
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
# [SECTION 0] Playwright 브라우저 자동 설치 및 크롤링 헬퍼
# -----------------------------------------------------------

def _ensure_browser_installed():
    """브라우저가 없으면 자동으로 설치 명령어를 실행합니다."""
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            try:
                p.chromium.launch(headless=True)
            except Exception:
                logger.info("⚠️ 브라우저가 없어서 자동 설치를 시작합니다...")
                subprocess.run(["playwright", "install", "chromium"], check=True)
                logger.info("✅ 브라우저 설치 완료!")
    except Exception as e:
        logger.error(f"브라우저 설치 중 오류: {e}")

def get_ttm_playwright_sync(code):
    """
    [최종 방어] 화면 전체 텍스트 스캔 + 브라우저 자동 설치 기능 포함.
    """
    yield_val = 0.0
    
    # 1차 시도: 그냥 실행해본다.
    try:
        yield_val, msg = _run_crawling(code)
        if yield_val > 0: return yield_val, msg
    except Exception as e:
        # 에러가 'Executable doesn't exist'(브라우저 없음)이면 설치 후 재시도
        if "Executable" in str(e) or "browser" in str(e):
            _ensure_browser_installed()
            try:
                return _run_crawling(code)
            except:
                pass
        pass
        
    return 0.0, ""

def _run_crawling(code):
    """실제 크롤링 로직 (내부용) - 화면 전체 텍스트 스캔 방식"""
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--no-sandbox"])
        context = browser.new_context(user_agent="Mozilla/5.0 (iPhone; CPU iPhone OS 15_0 like Mac OS X)")
        page = context.new_page()
        
        url = f"https://m.stock.naver.com/item/main.nhn#/stocks/{code}"
        page.goto(url, timeout=30000)
        page.wait_for_timeout(3000)
        
        # 스크롤 내려서 데이터 로딩 유도
        page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        page.wait_for_timeout(1000)
        
        body_text = page.inner_text("body")
        
        # 정규식으로 '배당수익률' or '분배금수익률' 찾기
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
    """
    [NEW] 입력된 날짜 문자열을 'YYYY-MM-DD' 표준 포맷으로 1차 정규화합니다.
    """
    s = str(date_str).strip()
    if re.match(r'^\d{4}-\d{2}-\d{2}$', s):
        return s
    
    s = s.replace('.', '-').replace('/', '-')
    
    match = re.match(r'^(\d{4})-(\d{1,2})-(\d{1,2})$', s)
    if match:
        y, m, d = match.groups()
        return f"{y}-{m.zfill(2)}-{d.zfill(2)}"
    
    return s

def parse_dividend_date(date_str):
    """
    다양한 형태의 날짜 문자열(월초, 월말, 특정일)을 datetime.date 객체로 변환합니다.
    """
    s = standardize_date_format(str(date_str))
    today = datetime.date.today()
    
    try:
        return datetime.datetime.strptime(s, "%Y-%m-%d").date()
    except ValueError:
        pass
    
    is_end_of_month = any(k in s for k in ['말일', '월말', '마지막', '하순', 'END'])
    is_start_of_month = any(k in s for k in ['매월 초', '월초', '1~3일', 'BEGIN'])
    
    day_match = re.search(r'(\d+)', s)
    
    if is_end_of_month or is_start_of_month or (day_match and ('매월' in s or '일' in s)):
        try:
            if is_end_of_month:
                day = calendar.monthrange(today.year, today.month)[1]
            elif is_start_of_month:
                day = 1 
            else:
                day = int(day_match.group(1))
            
            try:
                last_day_actual = calendar.monthrange(today.year, today.month)[1]
                safe_day = min(day, last_day_actual)
                target_date = datetime.date(today.year, today.month, safe_day)
            except ValueError:
                target_date = today
            
            if target_date < today:
                next_month = today.month + 1 if today.month < 12 else 1
                year = today.year if today.month < 12 else today.year + 1
                
                last_day_next = calendar.monthrange(year, next_month)[1]
                
                if is_end_of_month:
                    real_day = last_day_next
                elif is_start_of_month:
                    real_day = 1
                else:
                    real_day = min(day, last_day_next)
                    
                return datetime.date(year, next_month, real_day)
            
            return target_date
        except Exception:
            pass
            
    return None 

def generate_portfolio_ics(portfolio_data):
    """
    [일괄 등록용] 포트폴리오 전체 일정을 .ics 파일 포맷으로 생성
    """
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
        date_info = str(item.get('배당락일', '-')).strip()
        if date_info in ['-', 'nan', 'None', '']: continue

        is_end_of_month = any(k in date_info for k in ['말일', '월말', '마지막', '30일', '31일', '하순'])
        is_start_of_month = any(k in date_info for k in ['매월 초', '월초', '1~3일'])
        day_match = re.search(r'(\d+)', date_info)
        
        target_day = None
        if is_end_of_month: target_day = 'END'
        elif is_start_of_month: target_day = 1
        elif day_match:
            target_day = int(day_match.group(1))
        
        fixed_date_obj = None
        if '-' in date_info or '.' in date_info:
             parsed = parse_dividend_date(date_info)
             if parsed: fixed_date_obj = parsed

        if target_day is not None or fixed_date_obj:
            check_idx = 0
            if fixed_date_obj: pass 

            while check_idx < 12:
                month_calc = today.month + check_idx
                year = current_year + (month_calc - 1) // 12
                month = (month_calc - 1) % 12 + 1
                
                check_idx += 1 
                
                if year > current_year:
                    break
                
                try:
                    last_day_of_month = calendar.monthrange(year, month)[1]
                    
                    if target_day == 'END':
                        safe_day = last_day_of_month
                    elif isinstance(target_day, int):
                        safe_day = min(target_day, last_day_of_month)
                    else:
                        continue
                    
                    event_date = datetime.date(year, month, safe_day)
                    
                    buy_date = event_date - datetime.timedelta(days=4)
                    
                    while buy_date.weekday() >= 5: 
                        buy_date -= datetime.timedelta(days=1)
                    
                    if buy_date < today:
                        continue
                        
                    dt_start = buy_date.strftime("%Y%m%d")
                    dt_end = (buy_date + datetime.timedelta(days=1)).strftime("%Y%m%d")
                    
                    description = (
                        f"예상 배당락일: {event_date}\\n\\n"
                        f"💰 [{name}] 배당 수령을 위해 계좌를 확인하세요.\\n\\n"
                        f"🛑 [필독] 투자 유의사항\\n"
                        f"이 알림은 과거 데이터를 기반으로 생성된 '예상 일정'입니다.\\n"
                        f"운용사 정책 변경으로 실제 배당일이 바뀔 수 있습니다.\\n"
                        f"안전한 투자를 위해, 매수 전 반드시 '운용사 공식 홈페이지' 공시를 확인해주세요."
                    )
                    
                    ics_content.extend([
                        "BEGIN:VEVENT",
                        f"DTSTART;VALUE=DATE:{dt_start}",
                        f"DTEND;VALUE=DATE:{dt_end}",
                        f"SUMMARY:🔔 [{name}] 배당락 D-4 (매수 권장)",
                        f"DESCRIPTION:{description}",
                        "END:VEVENT"
                    ])
                    
                except ValueError:
                    continue

    ics_content.append("END:VCALENDAR")
    return "\n".join(ics_content)

def get_google_cal_url(stock_name, date_str):
    """
    [단일 등록용] 구글 캘린더 일정 등록 URL 생성
    """
    try:
        target_date = parse_dividend_date(date_str)
        if not target_date: return None
        
        if isinstance(target_date, datetime.date):
            safe_buy_date = target_date - datetime.timedelta(days=4) 
        else:
            return None

        while safe_buy_date.weekday() >= 5:
            safe_buy_date -= datetime.timedelta(days=1)

        start_str = safe_buy_date.strftime("%Y%m%d")
        end_str = (safe_buy_date + datetime.timedelta(days=1)).strftime("%Y%m%d")
        
        base_url = "https://www.google.com/calendar/render?action=TEMPLATE"
        
        title_text = f"🔔 [{stock_name}] 배당락 D-4 (매수 권장)"
        details_text = (
            f"예상 배당락일: {date_str}\n\n"
            f"💰 배당 수령을 위해 계좌를 확인하세요.\n\n"
            f"🛑 [필독] 투자 유의사항\n"
            f"이 알림은 과거 데이터를 기반으로 생성된 '예상 일정'입니다."
        )

        title = quote(title_text)
        details = quote(details_text)
        
        return f"{base_url}&text={title}&dates={start_str}/{end_str}&details={details}"
    except Exception as e:
        logger.error(f"Calendar URL Error: {e}")
        return None


# -----------------------------------------------------------
# [SECTION 2] 시세 조회 및 유틸리티 함수
# -----------------------------------------------------------

def _fetch_naver_price(code):
    """네이버 모바일 API로 현재가 조회"""
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
    """DB Locked 에러 방지를 위한 안전 조회 로직"""
    try:
        code_str = str(code).strip()
        
        # 1. 국내 주식 (한투 API)
        if category == '국내':
            try:
                resp = broker.fetch_price(code_str)
                if resp and isinstance(resp, dict) and 'output' in resp:
                    if resp['output'] and resp['output'].get('stck_prpr'):
                        return int(resp['output']['stck_prpr'])
            except Exception as e:
                logger.warning(f"KIS Price Error ({code}): {e}")
                return None
        
        # 2. 해외 주식 (Yfinance)
        ticker_code = f"{code_str}.KS" if category == '국내' else code_str
        
        max_retries = 3
        for attempt in range(max_retries):
            try:
                ticker = yf.Ticker(ticker_code)
                price = ticker.fast_info.get('last_price')
                
                if not price:
                    hist = ticker.history(period="1d")
                    if not hist.empty:
                        price = hist['Close'].iloc[-1]
                
                if price: return float(price)
            
            except sqlite3.OperationalError: 
                if attempt < max_retries - 1:
                    time.sleep(0.5)
                    continue
                else:
                    logger.error(f"DB Locked Fail ({code}): Max retries exceeded")
            except Exception:
                break 
                
        return None
    except Exception as e:
        logger.error(f"Price Fetch Error ({code}): {e}")
        return None

def get_safe_price(broker, code, category):
    """안전하게 가격을 가져오며 실패 시 1회 더 재시도"""
    for _ in range(2):
        price = _fetch_price_raw(broker, code, category)
        if price is not None: return price
        time.sleep(0.3)
    return None

def classify_asset(row):
    """종목명과 코드를 분석하여 자산의 유형을 정밀 분류합니다."""
    name, symbol = str(row.get('종목명', '')).upper(), str(row.get('종목코드', '')).upper()
    
    if any(k in name or k in symbol for k in ['커버드콜', 'COVERED', 'QYLD', 'JEPI', 'JEPQ', 'NVDY', 'TSLY', 'QQQI', '타겟위클리']): return '🛡️ 커버드콜'
    if any(k in name or k in symbol for k in ['채권', '국채', 'BOND', 'TLT', '하이일드', 'HI-YIELD']): return '🏦 채권형'
    if '리츠' in name or 'REITS' in name or 'INFRA' in name or '인프라' in name: return '🏢 리츠형'
    if '혼합' in name: return '⚖️ 혼합형'
    return '📈 주식형'

def get_hedge_status(name, category):
    name_str = str(name).upper()
    if category == '해외': return "💲달러(직투)"
    if "환노출" in name_str or "UNHEDGED" in name_str: return "⚡환노출"
    if any(x in name_str for x in ["(H)", "헤지"]): return "🛡️환헤지(H)"
    return "⚡환노출" if any(x in name_str for x in ['미국', 'GLOBAL', 'S&P500', '나스닥', '국제']) else "-"


# -----------------------------------------------------------
# [SECTION 3] 데이터 로드 및 처리
# -----------------------------------------------------------

@st.cache_data(ttl=1800, show_spinner=False)
def load_and_process_data(df_raw, is_admin=False):
    if df_raw.empty: return pd.DataFrame()

    # 1. 데이터 전처리
    try:
        num_cols = ['연배당금', '연배당률', '현재가', '신규상장개월수', '연배당금_크롤링', '연배당금_크롤링_auto', 'TTM_연배당률(크롤링)']
        for col in num_cols:
            if col in df_raw.columns:
                df_raw[col] = pd.to_numeric(df_raw[col], errors='coerce').fillna(0)

        if '종목코드' in df_raw.columns:
            def clean_ticker(x):
                s = str(x).split('.')[0].strip()
                if s.isdigit(): return s.zfill(6) 
                return s.upper() 
            df_raw['종목코드'] = df_raw['종목코드'].apply(clean_ticker)

        if '배당락일' in df_raw.columns:
            df_raw['배당락일'] = df_raw['배당락일'].astype(str).replace(['nan', 'None', 'nan '], '-')

        if '자산유형' in df_raw.columns:
            df_raw['자산유형'] = df_raw['자산유형'].fillna('기타')
    except Exception as e:
        logger.error(f"Data Preprocessing Error: {e}")

    # 2. 브로커 초기화
    try:
        broker = mojito.KoreaInvestment(
            api_key=st.secrets["kis"]["app_key"],
            api_secret=st.secrets["kis"]["app_secret"],
            acc_no=st.secrets["kis"]["acc_no"],
            mock=True 
        )
    except:
        broker = None

    results = [None] * len(df_raw)
    
    # 3. 병렬 처리 작업자 함수
    def process_row(idx, row):
        try:
            code = str(row.get('종목코드', '')).strip()
            name = str(row.get('종목명', '')).strip()
            category = str(row.get('분류', '국내')).strip()
            
            # (A) 가격 조회
            price = get_safe_price(broker, code, category)
            if not price: price = 0

            # (B) 데이터 준비
            auto_div = float(row.get('연배당금_크롤링_auto', 0)) # 1순위
            manual_div = float(row.get('연배당금', 0))         # 3순위
            old_div = float(row.get('연배당금_크롤링', 0))      # 4순위
            saved_ttm_yield = float(row.get('TTM_연배당률(크롤링)', 0))  # 2순위

            # (C) 우선순위 로직
            final_div = 0
            calc_yield = 0
            status_msg = ""
            new_ttm_yield = 0 
            
            # 🥇 1순위: Auto
            if auto_div > 0:
                final_div = auto_div
                calc_yield = (final_div / price * 100) if price > 0 else 0
                status_msg = "⚡ Auto"

            else:
                # 🥈 2순위: TTM
                crawled_yield = 0
                pw_msg = ""
                if category == '국내':
                    try:
                        crawled_yield, pw_msg = get_ttm_playwright_sync(code)
                    except NameError:
                        crawled_yield = 0

                    if crawled_yield > 0:
                        calc_yield = crawled_yield
                        final_div = int(price * (crawled_yield / 100)) if price > 0 else 0
                        status_msg = pw_msg
                        new_ttm_yield = crawled_yield
                
                if calc_yield == 0 and saved_ttm_yield > 0:
                    calc_yield = saved_ttm_yield
                    final_div = int(price * (saved_ttm_yield / 100)) if price > 0 else 0
                    status_msg = f"💾 TTM(저장됨: {saved_ttm_yield}%)"
                    new_ttm_yield = saved_ttm_yield

                # 🥉 3순위: 수동
                if calc_yield == 0:
                    if manual_div > 0:
                        final_div = manual_div
                        calc_yield = (final_div / price * 100) if price > 0 else 0
                        status_msg = "🔧 수동"
                    elif old_div > 0:
                        final_div = old_div
                        calc_yield = (final_div / price * 100) if price > 0 else 0
                        status_msg = "⚠️ Old"
                    else:
                        status_msg = "❌ N/A"

            # (D) 신규 상장 종목 처리
            months = int(row.get('신규상장개월수', 0))
            if 0 < months < 12 and "수동" in status_msg:
                final_div = (manual_div / months * 12)
                calc_yield = (final_div / price * 100) if price > 0 else 0
                display_name = f"{name} ⭐"
            else:
                display_name = name

            price_fmt = f"{int(price):,}원" if category == '국내' else f"${price:.2f}"
            final_ttm_save = new_ttm_yield if new_ttm_yield > 0 else saved_ttm_yield

            csv_type = str(row.get('유형', '-'))
            auto_asset_type = classify_asset(row)
            final_type = '채권' if '채권' in auto_asset_type else \
                         '커버드콜' if '커버드콜' in auto_asset_type else \
                         '리츠' if '리츠' in auto_asset_type else csv_type

            return idx, {
                '코드': code,
                '종목명': display_name,
                '블로그링크': str(row.get('블로그링크', '#')),
                '금융링크': f"https://finance.naver.com/item/main.naver?code={code}" if category == '국내' else f"https://finance.yahoo.com/quote/{code}",
                '현재가': price_fmt,
                '연배당률': round(calc_yield, 2),
                '환구분': get_hedge_status(name, category),
                '배당락일': str(row.get('배당락일', '-')),
                '분류': category,
                '유형': final_type,
                '자산유형': auto_asset_type,
                '캘린더링크': None,
                'pure_name': name.replace("🚫 ", "").replace(" (필터대상)", ""),
                '신규상장개월수': months,
                '배당기록': str(row.get('배당기록', '')),
                '검색라벨': str(row.get('검색라벨', f"[{code}] {display_name}")),
                '비고': status_msg,
                '연배당금_크롤링_auto': auto_div,
                '연배당금': manual_div,
                '연배당금_크롤링': old_div,
                'TTM_연배당률(크롤링)': final_ttm_save 
            }
        except Exception as e:
            logger.error(f"Row Processing Error ({idx}): {e}")
            return idx, None

    with ThreadPoolExecutor(max_workers=10) as executor:
        futures = {executor.submit(process_row, idx, row): idx for idx, row in df_raw.iterrows()}
        for future in as_completed(futures):
            idx, result = future.result()
            results[idx] = result

    final_data = [r for r in results if r is not None]
    
    if final_data:
        result_df = pd.DataFrame(final_data)
        if '연배당률' in result_df.columns:
            return result_df.sort_values('연배당률', ascending=False)
        return result_df
    else:
        return pd.DataFrame()


# -----------------------------------------------------------
# [SECTION 4] 데이터 파일 관리 (GitHub/CSV)
# -----------------------------------------------------------

@st.cache_data(ttl=1800)
def load_stock_data_from_csv():
    import os
    file_path = "stocks.csv"

    for _ in range(3):
        try:
            if not os.path.exists(file_path):
                df_empty = pd.DataFrame()
                required_cols = ['종목코드', '종목명', '연배당금_크롤링_auto', '연배당률_크롤링', '배당기록', '연배당금_크롤링', 'TTM_연배당률(크롤링)']
                for c in required_cols:
                    df_empty[c] = pd.Series(dtype='object' if c in ['종목코드','종목명','배당기록'] else 'float')
                return df_empty

            df = pd.read_csv(file_path, dtype=str, encoding='utf-8-sig')
            
            def _normalize_col(c):
                if c is None: return ""
                s = str(c).replace('\ufeff', '').strip()
                s = "".join(ch for ch in s if ord(ch) >= 32)
                return s
            df.columns = [_normalize_col(c) for c in df.columns]

            if '연배당금_크롤링' not in df.columns: df['연배당금_크롤링'] = 0.0
            if '연배당금_크롤링_auto' not in df.columns: df['연배당금_크롤링_auto'] = 0.0
            if '연배당률_크롤링' not in df.columns: df['연배당률_크롤링'] = 0.0
            if '배당기록' not in df.columns: df['배당기록'] = ""
            if 'TTM_연배당률(크롤링)' not in df.columns: df['TTM_연배당률(크롤링)'] = 0.0
                
            if '종목코드' not in df.columns:
                df['종목코드'] = df.index.astype(str).apply(lambda x: x.zfill(6) if x.isdigit() else x)

            df['종목코드'] = df['종목코드'].astype(str).str.strip()
            return df
        except Exception as e:
            logger.warning(f"CSV load attempt failed: {e}")
            time.sleep(0.5)

    logger.error("CSV Load Failed after retries")
    return pd.DataFrame()


def save_to_github(df):
    """깃허브에 CSV로 덮어쓰기"""
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
    except Exception as e:
        logger.error(f"Github Save Error: {e}")
        return False, f"❌ 저장 실패: {str(e)}"


def reset_auto_data(code):
    """Auto 데이터 0으로 초기화"""
    try:
        df = load_stock_data_from_csv()
        idx = df[df['종목코드'] == code].index
        if not idx.empty:
            df.at[idx[0], '연배당금_크롤링_auto'] = 0.0
            df.to_csv("stocks.csv", index=False, encoding='utf-8-sig')
            return True, "초기화 완료! 이제 TTM이나 수동값을 사용합니다."
        return False, "종목을 찾을 수 없습니다."
    except Exception as e:
        return False, f"에러: {e}"

# -----------------------------------------------------------
# [SECTION 6] 실시간 배당 정보 크롤링 (Hybrid)
# -----------------------------------------------------------

def fetch_dividend_yield_hybrid(code, category):
    code = str(code).strip()
    if category == '국내':
        current_price = 0
        resp = None
        try:
            broker = mojito.KoreaInvestment(
                api_key=st.secrets["kis"]["app_key"],
                api_secret=st.secrets["kis"]["app_secret"],
                acc_no=st.secrets["kis"]["acc_no"],
                mock=True
            )
            resp = broker.fetch_price(code)
            if resp and 'output' in resp:
                current_price = float(resp['output'].get('stck_prpr', 0) or 0)
        except Exception:
            current_price = 0

        if current_price == 0:
            try:
                current_price = _fetch_naver_price(code) or 0
            except:
                current_price = 0

        latest_div = 0
        try:
            headers = {
                "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 15_0 like Mac OS X)",
                "Referer": f"https://m.stock.naver.com/domestic/stock/{code}/analysis"
            }
            hist_url = f"https://m.stock.naver.com/api/etf/{code}/dividend/history?page=1&pageSize=200&firstPageSize=200"
            r = requests.get(hist_url, headers=headers, timeout=6)
            if r.status_code == 200:
                j = r.json()
                items = []
                if isinstance(j, dict):
                    items = j.get("result") or j.get("items") or j.get("data") or []
                    if isinstance(items, dict):
                        items = items.get("items") or []
                elif isinstance(j, list):
                    items = j
                if isinstance(items, list) and items:
                    first = items[0]
                    amt = None
                    for k in ("dividendAmount", "dividend", "distribution", "amount", "value", "payAmount"):
                        if isinstance(first, dict) and k in first and first[k] is not None:
                            amt = first[k]
                            break
                    if isinstance(amt, str):
                        try:
                            amt = float(amt.replace(',', '').strip())
                        except:
                            amt = None
                    if amt:
                        latest_div = float(amt)
        except Exception as e:
            logger.warning(f"Dividend history request failed ({code}): {e}")
            latest_div = 0

        if current_price > 0 and latest_div > 0:
            try:
                yield_val = (latest_div * 12) / current_price * 100
                return round(yield_val, 2), f"✅ 실시간({int(latest_div)}원)"
            except Exception:
                pass

        try:
            if resp and 'output' in resp:
                backup = resp['output'].get('hts_dvsd_rate')
                if backup and backup != '-':
                    return float(backup), "✅ 한투API(백업)"
        except Exception:
            pass
        return 0.0, "⚠️ 조회 실패"

    else:
        try:
            ticker = yf.Ticker(code)
            price = None
            try:
                price = ticker.fast_info.get('last_price')
            except Exception:
                price = None

            annual_div_sum = 0.0
            try:
                divs = ticker.dividends
                if divs is not None and len(divs) > 0:
                    idx = divs.index
                    try:
                        tz = getattr(idx, 'tz', None)
                        if tz is not None:
                            cutoff = pd.Timestamp.now(tz=tz) - pd.Timedelta(days=365)
                        else:
                            cutoff = pd.Timestamp.now() - pd.Timedelta(days=365)
                    except Exception:
                        cutoff = pd.Timestamp.now() - pd.Timedelta(days=365)

                    try:
                        recent = divs[divs.index >= cutoff]
                    except Exception:
                        recent = divs.tail(4)
                    if recent.empty: recent = divs.tail(4)
                    annual_div_sum = float(recent.sum())
            except Exception:
                annual_div_sum = 0.0

            if not price:
                try:
                    hist = ticker.history(period="5d")
                    if not hist.empty:
                        price = float(hist['Close'].iloc[-1])
                except Exception:
                    price = None

            if price and price > 0 and annual_div_sum and annual_div_sum > 0:
                yield_pct = (annual_div_sum / price) * 100.0
                return round(yield_pct, 2), f"✅ 야후(계산: {annual_div_sum:.2f}/{price:.2f})"
            else:
                try:
                    info_dy = ticker.info.get('dividendYield')
                    if info_dy:
                        calc_val = info_dy * 100
                        return round(calc_val, 2), "✅ 야후(Info)"
                except Exception:
                    pass
            return 0.0, "⚠️ 데이터 없음"
        except Exception as e:
            return 0.0, "❌ 해외 에러"

def smart_update_and_save():
    """
    [스마트 전체 갱신 (국내 TTM + 해외 자동화)]
    """
    try:
        df = load_stock_data_from_csv()
        if df.empty: return False, "CSV 파일이 비어있습니다."
        
        updated_count = 0
        skipped_count = 0
        
        progress_bar = st.progress(0)
        status_text = st.empty()
        total = len(df)
        
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

            current_auto = float(row.get('연배당금_크롤링_auto', 0))
            current_manual = float(row.get('연배당금', 0))
            is_locked = (current_manual > 0) and (current_auto == 0)
            
            if category == '국내':
                if not is_locked:
                    try:
                        y_val, src = fetch_dividend_yield_hybrid(code, category)
                        if y_val > 0:
                            df.at[idx, '연배당률_크롤링'] = float(y_val)
                            m = re.search(r'\(([\d,\.]+)원\)', str(src))
                            if m:
                                val = int(m.group(1).replace(',', '').split('.')[0])
                                df.at[idx, '연배당금_크롤링_auto'] = float(val) * 12
                            updated_count += 1
                    except: pass

                if float(df.at[idx, '연배당금_크롤링_auto']) == 0:
                    try:
                        ttm_yield, _ = get_ttm_playwright_sync(code)
                        if ttm_yield > 0:
                            df.at[idx, 'TTM_연배당률(크롤링)'] = ttm_yield
                            if is_locked: updated_count += 1
                    except: pass

            elif category == '해외':
                if not is_locked:
                    try:
                        ticker = yf.Ticker(code)
                        divs = ticker.dividends
                        if not divs.empty:
                            now = pd.Timestamp.now(tz=divs.index.tz)
                            cutoff = now - pd.Timedelta(days=365)
                            recent_divs = divs[divs.index >= cutoff]
                            usd_sum = float(recent_divs.sum())
                            
                            if usd_sum > 0:
                                df.at[idx, '연배당금_크롤링_auto'] = usd_sum
                                price = ticker.fast_info.get('last_price')
                                if not price:
                                    hist = ticker.history(period="1d")
                                    if not hist.empty: price = hist['Close'].iloc[-1]
                                
                                if price and price > 0:
                                    yield_pct = (usd_sum / price) * 100
                                    df.at[idx, '연배당률_크롤링'] = round(yield_pct, 2)
                                updated_count += 1
                    except Exception:
                        pass

        df.to_csv("stocks.csv", index=False, encoding='utf-8-sig')
        if "github" in st.secrets:
            save_to_github(df)
            
        status_text.empty()
        progress_bar.empty()
        return True, f"✅ 스마트 갱신 완료! (갱신: {updated_count}개 / 스킵: {skipped_count}개)"
        
    except Exception as e:
        logger.error(f"Smart Update Error: {e}")
        return False, f"갱신 중 오류 발생: {e}"

def update_dividend_rolling(current_history_str, new_dividend_amount):
    """배당금 기록 갱신"""
    if pd.isna(current_history_str) or str(current_history_str).strip() == "":
        history = []
    else:
        try:
            history = [int(float(x)) for x in str(current_history_str).split('|') if x.strip()]
        except:
            history = []

    if len(history) >= 12:
        history.pop(0)
        
    history.append(int(new_dividend_amount))
    new_annual_total = sum(history)
    new_history_str = "|".join(map(str, history))
    return new_annual_total, new_history_str
