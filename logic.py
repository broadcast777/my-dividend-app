"""
프로젝트: 배당 팽이 (Dividend Top) v3.7 (FINAL FIX)
파일명: logic.py
설명: 12시간 전 안정 버전 + TTM API 계산 + 캘린더 문구 완벽 복구
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

# 로거 설정
if not logging.getLogger().handlers:
    logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# -----------------------------------------------------------
# [SECTION 0] TTM 데이터 확보 (API 계산기 + Playwright)
# -----------------------------------------------------------

def _ensure_browser_installed():
    """브라우저 자동 설치 헬퍼"""
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            try: p.chromium.launch(headless=True)
            except: subprocess.run(["playwright", "install", "chromium"], check=True)
    except: pass

def get_ttm_playwright_sync(code):
    """
    [TTM 구하기 - 업그레이드]
    1순위: 네이버 배당 API로 직접 합산 (속도 빠름, 액티브ETF 해결)
    2순위: 실패 시 Playwright로 화면 크롤링 (백업)
    """
    code = str(code).strip()
    
    # [1단계] 네이버 API로 직접 계산
    try:
        # 현재가 조회
        price_url = f"https://api.stock.naver.com/etf/{code}/basic"
        price_res = requests.get(price_url, timeout=3, headers={"User-Agent": "Mozilla/5.0"})
        current_price = 0
        if price_res.status_code == 200:
            d = price_res.json()
            if 'result' in d and 'closePrice' in d['result']:
                current_price = float(d['result']['closePrice'])

        # 배당 내역 조회
        hist_url = f"https://m.stock.naver.com/api/etf/{code}/dividend/history?pageSize=20"
        res = requests.get(hist_url, timeout=5, headers={"User-Agent": "Mozilla/5.0"})
        
        if res.status_code == 200 and current_price > 0:
            data = res.json()
            items = []
            if isinstance(data, list): items = data
            elif isinstance(data, dict):
                items = data.get('result', []) or data.get('items', [])
            
            if items:
                ttm_sum = 0
                cutoff_date = (datetime.date.today() - datetime.timedelta(days=365)).strftime("%Y%m%d")
                
                for item in items:
                    d_date = str(item.get('paymentDate') or item.get('dividendDate') or "").replace(".", "")
                    amt = item.get('dividendAmount') or item.get('amount') or 0
                    if d_date >= cutoff_date:
                        ttm_sum += float(amt)
                
                if ttm_sum > 0:
                    final_yield = round((ttm_sum / current_price) * 100, 2)
                    return final_yield, f"✅ API계산({int(ttm_sum)}원/{final_yield}%)"
    except Exception:
        pass

    # [2단계] Playwright 크롤링 (기존 방식 유지)
    yield_val = 0.0
    try:
        try: _ensure_browser_installed()
        except: pass

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True, args=["--no-sandbox"])
            context = browser.new_context(user_agent="Mozilla/5.0")
            page = context.new_page()
            url = f"https://m.stock.naver.com/item/main.nhn#/stocks/{code}"
            page.goto(url, timeout=30000)
            page.wait_for_timeout(2000)
            
            page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            page.wait_for_timeout(1000)
            text = page.inner_text("body")
            
            match = re.search(r'(?:배당수익률|분배금수익률).*?([\d\.]+)\s*%', text, re.DOTALL)
            if match: yield_val = float(match.group(1))
            browser.close()
            
            if yield_val > 0:
                return yield_val, f"✅ 웹크롤링({yield_val}%)"
    except Exception as e:
        logger.warning(f"Crawling Failed {code}: {e}")
        
    return 0.0, ""

# -----------------------------------------------------------
# [SECTION 1] 날짜 및 스케줄링 헬퍼 (문구 완벽 복구)
# -----------------------------------------------------------

def standardize_date_format(date_str):
    s = str(date_str).strip()
    if re.match(r'^\d{4}-\d{2}-\d{2}$', s): return s
    s = s.replace('.', '-').replace('/', '-')
    match = re.match(r'^(\d{4})-(\d{1,2})-(\d{1,2})$', s)
    if match: return f"{match.group(1)}-{match.group(2).zfill(2)}-{match.group(3).zfill(2)}"
    return s

def parse_dividend_date(date_str):
    s = standardize_date_format(str(date_str))
    today = datetime.date.today()
    try: return datetime.datetime.strptime(s, "%Y-%m-%d").date()
    except ValueError: pass
    
    is_end = any(k in s for k in ['말일', '월말', '마지막', 'END'])
    is_start = any(k in s for k in ['매월 초', '월초', 'BEGIN'])
    day_match = re.search(r'(\d+)', s)
    
    if is_end or is_start or (day_match and ('매월' in s or '일' in s)):
        try:
            if is_end: day = calendar.monthrange(today.year, today.month)[1]
            elif is_start: day = 1 
            else: day = int(day_match.group(1))
            
            try:
                last_day = calendar.monthrange(today.year, today.month)[1]
                safe_day = min(day, last_day)
                target = datetime.date(today.year, today.month, safe_day)
            except: target = today
            
            if target < today:
                nm = today.month + 1 if today.month < 12 else 1
                ny = today.year if today.month < 12 else today.year + 1
                nd = calendar.monthrange(ny, nm)[1]
                if is_end: r_day = nd
                elif is_start: r_day = 1
                else: r_day = min(day, nd)
                return datetime.date(ny, nm, r_day)
            return target
        except: pass
    return None 

def generate_portfolio_ics(portfolio_data):
    """ICS 파일 생성 (사용자 요청 문구 복구 완료)"""
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

        is_end = any(k in date_info for k in ['말일', '월말', '마지막', '30일'])
        is_start = any(k in date_info for k in ['매월 초', '월초', '1~3일'])
        day_match = re.search(r'(\d+)', date_info)
        
        target_day = None
        if is_end: target_day = 'END'
        elif is_start: target_day = 1
        elif day_match: target_day = int(day_match.group(1))
        
        fixed_date_obj = None
        if '-' in date_info or '.' in date_info:
             fixed_date_obj = parse_dividend_date(date_info)

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
                    
                    # [사용자 요청 문구 복구]
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
                except ValueError: continue

    ics_content.append("END:VCALENDAR")
    return "\n".join(ics_content)

def get_google_cal_url(stock_name, date_str):
    """구글 캘린더 URL (사용자 요청 문구 복구 완료)"""
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
        title_text = f"🔔 [{stock_name}] 배당락 D-4 (매수 권장)"
        
        # [사용자 요청 문구 복구]
        details_text = (
            f"예상 배당락일: {date_str}\n\n"
            f"💰 배당 수령을 위해 계좌를 확인하세요.\n\n"
            f"🛑 [필독] 투자 유의사항\n"
            f"이 알림은 과거 데이터를 기반으로 생성된 '예상 일정'입니다.\n"
            f"운용사 정책 변경(예: 15일→월말)으로 실제 배당일이 바뀔 수 있습니다.\n"
            f"안전한 투자를 위해, 매수 전 반드시 '운용사 공식 홈페이지' 공시를 확인해주세요."
        )
        
        title = quote(title_text)
        details = quote(details_text)
        return f"{base_url}&text={title}&dates={start_str}/{end_str}&details={details}"
    except: return None

# -----------------------------------------------------------
# [SECTION 2] 시세 조회 및 유틸리티 (기존 유지)
# -----------------------------------------------------------
def _fetch_naver_price(code):
    try:
        url = f"https://api.stock.naver.com/etf/{code}/basic"
        r = requests.get(url, headers={"User-Agent":"Mozilla/5.0"}, timeout=2)
        if r.status_code == 200:
            d = r.json()
            if 'result' in d and 'closePrice' in d['result']: return int(d['result']['closePrice'])
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
        
        t_code = f"{code_str}.KS" if category == '국내' else code_str
        for _ in range(3):
            try:
                tk = yf.Ticker(t_code)
                p = tk.fast_info.get('last_price')
                if not p:
                    h = tk.history(period="1d")
                    if not h.empty: p = h['Close'].iloc[-1]
                if p: return float(p)
            except sqlite3.OperationalError: time.sleep(0.5)
            except: break
        return None
    except: return None

def get_safe_price(broker, code, category):
    for _ in range(2):
        p = _fetch_price_raw(broker, code, category)
        if p: return p
        time.sleep(0.3)
    if category == '국내': return _fetch_naver_price(code)
    return 0

def classify_asset(row):
    n, c = str(row.get('종목명', '')).upper(), str(row.get('종목코드', '')).upper()
    if any(k in n or k in c for k in ['커버드콜', 'COVERED', 'QYLD', 'JEPI', 'JEPQ', 'NVDY', 'TSLY', 'QQQI', '타겟위클리']): return '🛡️ 커버드콜'
    if any(k in n or k in c for k in ['채권', '국채', 'BOND', 'TLT', '하이일드', 'HI-YIELD']): return '🏦 채권형'
    if '리츠' in n or 'REITS' in n: return '🏢 리츠형'
    if '혼합' in n: return '⚖️ 혼합형'
    return '📈 주식형'

def get_hedge_status(name, category):
    if category == '해외': return "💲달러(직투)"
    if "환노출" in str(name): return "⚡환노출"
    if "(H)" in str(name): return "🛡️환헤지(H)"
    return "⚡환노출"

# -----------------------------------------------------------
# [SECTION 3] 메인 데이터 로드 (TTM 값 연동)
# -----------------------------------------------------------
@st.cache_data(ttl=1800, show_spinner=False)
def load_and_process_data(df_raw, is_admin=False):
    if df_raw.empty: return pd.DataFrame()

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

            auto = float(row.get('연배당금_크롤링_auto', 0))
            man = float(row.get('연배당금', 0))
            old = float(row.get('연배당금_크롤링', 0))
            ttm_saved = float(row.get('TTM_연배당률(크롤링)', 0))

            final_div, calc_yield, msg = 0, 0, ""

            if auto > 0:
                final_div = auto
                if price > 0: calc_yield = (auto / price) * 100
                msg = "⚡ Auto"
            elif ttm_saved > 0:
                calc_yield = ttm_saved
                if price > 0: final_div = int(price * (ttm_saved / 100))
                msg = f"✅ API계산({ttm_saved}%)"
            elif man > 0:
                final_div = man
                if price > 0: calc_yield = (man / price) * 100
                msg = "🔧 수동"
            elif old > 0:
                final_div = old
                if price > 0: calc_yield = (old / price) * 100
                msg = "⚠️ Old"
            else:
                msg = "❌ N/A"

            months = int(row.get('신규상장개월수', 0))
            if 0 < months < 12 and "수동" in msg:
                final_div = (man / months) * 12
                if price > 0: calc_yield = (final_div / price) * 100
                name += " ⭐"

            p_fmt = f"{int(price):,}원" if category == '국내' else f"${price:.2f}"
            
            csv_type = str(row.get('유형', '-'))
            auto_asset_type = classify_asset(row) 
            final_type = csv_type
            if '채권' in auto_asset_type: final_type = '채권'
            elif '커버드콜' in auto_asset_type: final_type = '커버드콜'
            elif '리츠' in auto_asset_type: final_type = '리츠'

            return idx, {
                '코드': code, '종목명': name, '현재가': p_fmt, 
                '연배당률': round(calc_yield, 2), '환구분': get_hedge_status(name, category),
                '배당락일': str(row.get('배당락일', '-')), '분류': category, '유형': final_type, 
                '자산유형': auto_asset_type, '캘린더링크': get_google_cal_url(name, str(row.get('배당락일', '-'))), 
                'pure_name': name.replace("🚫 ", "").replace(" (필터대상)", ""), 
                '신규상장개월수': months, '배당기록': str(row.get('배당기록', '')),
                '검색라벨': str(row.get('검색라벨', f"[{code}] {name}")), '비고': msg, '블로그링크': str(row.get('블로그링크', '#')),
                '금융링크': '#', 
                '연배당금_크롤링_auto': auto, '연배당금': man, '연배당금_크롤링': old, 'TTM_연배당률(크롤링)': ttm_saved
            }
        except Exception as e: return idx, None

    with ThreadPoolExecutor(max_workers=10) as executor:
        futures = {executor.submit(process_row, i, r): i for i, r in df_raw.iterrows()}
        for f in as_completed(futures):
            i, res = f.result()
            results[i] = res
    final = [r for r in results if r]
    return pd.DataFrame(final).sort_values('연배당률', ascending=False) if final else pd.DataFrame()

# -----------------------------------------------------------
# [SECTION 4] 파일 관리 (기존 유지)
# -----------------------------------------------------------
@st.cache_data(ttl=1800)
def load_stock_data_from_csv():
    import os
    file_path = "stocks.csv"
    for _ in range(3):
        try:
            if not os.path.exists(file_path): return pd.DataFrame()
            df = pd.read_csv(file_path, dtype=str, encoding='utf-8-sig')
            def _normalize_col(c):
                if c is None: return ""
                s = str(c).replace('\ufeff', '').strip()
                s = "".join(ch for ch in s if ord(ch) >= 32)
                return s
            df.columns = [_normalize_col(c) for c in df.columns]
            
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
        repo.update_file(contents.path, "Update", df.to_csv(index=False).encode("utf-8"), contents.sha)
        return True, "✅ 깃허브 저장 성공!"
    except: return False, "❌ 저장 실패"

def reset_auto_data(code):
    try:
        df = load_stock_data_from_csv()
        idx = df[df['종목코드'] == code].index
        if not idx.empty:
            df.at[idx[0], '연배당금_크롤링_auto'] = 0.0
            df.to_csv("stocks.csv", index=False, encoding='utf-8-sig')
            return True, "초기화 완료"
        return False, "없음"
    except Exception as e: return False, str(e)

# -----------------------------------------------------------
# [SECTION 6] 배당 조회 (버튼 및 Auto용)
# -----------------------------------------------------------
# [logic.py의 fetch_dividend_yield_hybrid 함수를 이걸로 통째로 교체하세요]

def fetch_dividend_yield_hybrid(code, category):
    """
    [복구 + 강화]
    1. 네이버 API 시도 (빠름)
    2. 실패 시 HTML 정밀 크롤링 시도 (리츠/일반주식 대응 - 예전 방식 복구)
    """
    code = str(code).strip()
    
    if category == '국내':
        # ---------------------------------------------------
        # [시도 1] API (ETF 전용 - 빠름)
        # ---------------------------------------------------
        try:
            url = f"https://m.stock.naver.com/api/etf/{code}/dividend/history?pageSize=1"
            res = requests.get(url, timeout=2, headers={"User-Agent": "Mozilla/5.0"})
            if res.status_code == 200:
                data = res.json()
                items = data.get('result', {}).get('items', [])
                if items:
                    amt = items[0].get('dividendAmount') or items[0].get('amount') or 0
                    amt = float(str(amt).replace(',', ''))
                    
                    if amt > 0:
                        price = get_safe_price(None, code, '국내')
                        if price > 0:
                            y = (amt * 12) / price * 100
                            return round(y, 2), f"✅ API({int(amt)}원)"
        except: pass

        # ---------------------------------------------------
        # [시도 2] HTML 크롤링 (리츠/일반주식용 - 강력함)
        # ---------------------------------------------------
        try:
            # 네이버 금융 메인 페이지 (PC 버전이 데이터가 확실함)
            url = f"https://finance.naver.com/item/main.naver?code={code}"
            res = requests.get(url, timeout=3, headers={"User-Agent": "Mozilla/5.0"})
            html = res.text
            
            # 1. 현재가 찾기
            price = 0
            m_price = re.search(r'no_today.*<span class="blind">([\d,]+)</span>', html)
            if m_price:
                price = int(m_price.group(1).replace(',', ''))
            
            if price == 0:
                price = get_safe_price(None, code, '국내')

            # 2. 주당배당금(DPS) 찾기 (화면 중간 '주당배당금' 테이블)
            # "주당배당금" 텍스트 뒤에 나오는 숫자 중 가장 최근 것
            if "주당배당금" in html:
                # 테이블 행 찾기
                soup = BeautifulSoup(html, 'html.parser')
                dps_rows = soup.find_all('th', string=re.compile('주당배당금'))
                
                if dps_rows:
                    # 해당 행의 td들 가져오기
                    parent = dps_rows[0].parent
                    tds = parent.find_all('td')
                    # 뒤에서부터 유효한 숫자 찾기 (최근 예상치 or 확정치)
                    for td in reversed(tds):
                        txt = td.get_text().strip().replace(',', '')
                        if txt.isdigit() and int(txt) > 0:
                            dps = int(txt)
                            # 월배당인지 확인 불가하므로, 단순 수익률 계산보다는 값 반환에 의의
                            # 리츠의 경우 보통 연배당금이 찍힘
                            if price > 0:
                                y = (dps / price) * 100
                                return round(y, 2), f"✅ 웹크롤링({dps}원)"
                            break
        except: pass
        
        # ---------------------------------------------------
        # [시도 3] 모바일 페이지 텍스트 스캔 (최후통첩)
        # ---------------------------------------------------
        try:
            url = f"https://m.stock.naver.com/item/main.nhn#/stocks/{code}"
            res = requests.get(url, timeout=3, headers={"User-Agent": "Mozilla/5.0"})
            # 정규식으로 배당수익률 XX.XX% 찾기
            m = re.search(r'배당수익률.*?([\d\.]+)\s*%', res.text)
            if m:
                return float(m.group(1)), "✅ 웹스캔(%)"
        except: pass

        return 0.0, "⚠️ 조회 실패"

    else:
        # [해외 종목] (기존 유지)
        try:
            tk = yf.Ticker(code)
            divs = tk.dividends
            if not divs.empty:
                cut = pd.Timestamp.now(tz=divs.index.tz) - pd.Timedelta(days=365)
                usd = float(divs[divs.index >= cut].sum())
                p = tk.fast_info.get('last_price')
                if not p:
                    h = tk.history(period='1d')
                    if not h.empty: p = h['Close'].iloc[-1]
                
                if p and p > 0:
                    y = (usd / p) * 100
                    return round(y, 2), f"✅ 야후(${usd:.2f})"
        except: pass
        return 0.0, "⚠️ 데이터 없음"

# -----------------------------------------------------------
# [SECTION 7] 스마트 갱신 (TTM API 로직 추가)
# -----------------------------------------------------------
def smart_update_and_save():
    try:
        df = load_stock_data_from_csv()
        if df.empty: return False, "파일 없음"
        
        cnt, skip = 0, 0
        pbar, stext = st.progress(0), st.empty()
        total = len(df)
        
        try: _ensure_browser_installed()
        except: pass

        for i, row in df.iterrows():
            code = str(row['종목코드']).strip()
            cat = str(row.get('분류', '국내')).strip()
            name = str(row['종목명']).strip()
            
            pbar.progress((i+1)/total)
            stext.text(f"갱신 중: {name}")
            
            try: mon = int(row.get('신규상장개월수', 0))
            except: mon = 0
            if 0 < mon < 12: 
                skip += 1
                continue

            def tf(v): 
                try: return float(v)
                except: return 0.0
            
            curr_auto = tf(row.get('연배당금_크롤링_auto', 0))
            curr_man = tf(row.get('연배당금', 0))
            is_locked = (curr_man > 0) and (curr_auto == 0)
            
            if not is_locked:
                try:
                    y, msg = fetch_dividend_yield_hybrid(code, cat)
                    if y > 0:
                        df.at[i, '연배당률_크롤링'] = y
                        if cat == '국내':
                            m = re.search(r'\(([\d,\.]+)원\)', msg)
                            if m: df.at[i, '연배당금_크롤링_auto'] = float(m.group(1).replace(',', '')) * 12
                        else:
                            m = re.search(r'\$([\d\.]+)', msg)
                            if m: df.at[i, '연배당금_크롤링_auto'] = float(m.group(1))
                        cnt += 1
                except: pass
            
            # TTM 갱신 (API 계산)
            check_auto = tf(df.at[i, '연배당금_크롤링_auto'])
            if (check_auto == 0 or is_locked) and cat == '국내':
                try:
                    # 새로 추가된 TTM 함수 사용
                    ttm, _ = get_ttm_playwright_sync(code) 
                    if ttm > 0:
                        df.at[i, 'TTM_연배당률(크롤링)'] = float(ttm)
                        if is_locked: cnt += 1
                except: pass

        df.to_csv("stocks.csv", index=False, encoding='utf-8-sig')
        if "github" in st.secrets: save_to_github(df)
        
        stext.empty()
        pbar.empty()
        return True, f"✅ 완료! (갱신: {cnt}, 스킵: {skip})"
        
    except Exception as e: return False, f"에러: {e}"

def update_dividend_rolling(h_str, val):
    if pd.isna(h_str) or str(h_str).strip() == "": h = []
    else:
        try: h = [int(float(x)) for x in str(h_str).split('|') if x.strip()]
        except: h = []
    if len(h)>=12: h.pop(0)
    h.append(int(val))
    return sum(h), "|".join(map(str, h))
