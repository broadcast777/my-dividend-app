"""
프로젝트: 배당 팽이 (Dividend Top) v3.2 (Mobile API Patch)
파일명: logic.py
설명: 금융 API 연동, 데이터 크롤링 (네이버 모바일 API 엔진 탑재)
업데이트: 2026.01.20
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
from logger import logger
import sqlite3 

# -----------------------------------------------------------
# [SECTION 1] 날짜 및 스케줄링 헬퍼
# -----------------------------------------------------------

def standardize_date_format(date_str):
    """날짜 포맷 정규화 (YYYY-MM-DD)"""
    s = str(date_str).strip()
    if re.match(r'^\d{4}-\d{2}-\d{2}$', s): return s
    s = s.replace('.', '-').replace('/', '-')
    match = re.match(r'^(\d{4})-(\d{1,2})-(\d{1,2})$', s)
    if match:
        y, m, d = match.groups()
        return f"{y}-{m.zfill(2)}-{d.zfill(2)}"
    return s

def parse_dividend_date(date_str):
    """날짜 문자열 파싱 (월말/월초/특정일)"""
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
    """ICS 캘린더 파일 생성"""
    ics_content = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//DividendPange//Portfolio//KO", "CALSCALE:GREGORIAN", "METHOD:PUBLISH"]
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
                    
                    description = (f"예상 배당락일: {event_date}\\n\\n💰 [{name}] 배당 수령을 위해 계좌를 확인하세요.\\n\\n🛑 [필독] 투자 유의사항\\n이 알림은 과거 데이터를 기반으로 생성된 '예상 일정'입니다.")
                    ics_content.extend(["BEGIN:VEVENT", f"DTSTART;VALUE=DATE:{dt_start}", f"DTEND;VALUE=DATE:{dt_end}", f"SUMMARY:🔔 [{name}] 배당락 D-4 (매수 권장)", f"DESCRIPTION:{description}", "END:VEVENT"])
                except ValueError: continue

    ics_content.append("END:VCALENDAR")
    return "\n".join(ics_content)

def get_google_cal_url(stock_name, date_str):
    """구글 캘린더 URL 생성"""
    try:
        target_date = parse_dividend_date(date_str)
        if not target_date or not isinstance(target_date, datetime.date): return None
        
        safe_buy_date = target_date - datetime.timedelta(days=4) 
        while safe_buy_date.weekday() >= 5: safe_buy_date -= datetime.timedelta(days=1)

        start_str = safe_buy_date.strftime("%Y%m%d")
        end_str = (safe_buy_date + datetime.timedelta(days=1)).strftime("%Y%m%d")
        base_url = "https://www.google.com/calendar/render?action=TEMPLATE"
        title = quote(f"🔔 [{stock_name}] 배당락 D-4 (매수 권장)")
        details = quote(f"예상 배당락일: {date_str}\n\n💰 배당 수령을 위해 계좌를 확인하세요.")
        
        return f"{base_url}&text={title}&dates={start_str}/{end_str}&details={details}"
    except Exception as e:
        logger.error(f"Calendar URL Error: {e}")
        return None

# -----------------------------------------------------------
# [SECTION 2] 시세 및 데이터 조회 (안전 강화됨)
# -----------------------------------------------------------

def _fetch_price_raw(broker, code, category):
    try:
        code_str = str(code).strip()
        if category == '국내':
            try:
                resp = broker.fetch_price(code_str)
                if resp and isinstance(resp, dict) and 'output' in resp:
                    if resp['output'] and resp['output'].get('stck_prpr'):
                        return int(resp['output']['stck_prpr'])
            except: pass
        
        ticker_code = f"{code_str}.KS" if category == '국내' else code_str
        for attempt in range(3): # Retry logic
            try:
                ticker = yf.Ticker(ticker_code)
                price = ticker.fast_info.get('last_price')
                if not price:
                    hist = ticker.history(period="1d")
                    if not hist.empty: price = hist['Close'].iloc[-1]
                if price: return float(price)
            except sqlite3.OperationalError: 
                time.sleep(0.5)
            except Exception: break
        return None
    except Exception: return None

def get_safe_price(broker, code, category):
    for _ in range(2):
        price = _fetch_price_raw(broker, code, category)
        if price is not None: return price
        time.sleep(0.3)
    return None

def classify_asset(row):
    name, symbol = str(row.get('종목명', '')).upper(), str(row.get('종목코드', '')).upper()
    if any(k in name or k in symbol for k in ['커버드콜', 'COVERED', 'QYLD', 'JEPI']): return '🛡️ 커버드콜'
    if any(k in name or k in symbol for k in ['채권', '국채', 'BOND', 'TLT']): return '🏦 채권형'
    if '리츠' in name or 'REITS' in name: return '🏢 리츠형'
    return '📈 주식형'

def get_hedge_status(name, category):
    name_str = str(name).upper()
    if category == '해외': return "💲달러(직투)"
    if "환노출" in name_str or "UNHEDGED" in name_str: return "⚡환노출"
    if any(x in name_str for x in ["(H)", "헤지"]): return "🛡️환헤지(H)"
    return "⚡환노출" if any(x in name_str for x in ['미국', 'GLOBAL']) else "-"

# -----------------------------------------------------------
# [SECTION 3] 데이터 처리 및 파일 관리
# -----------------------------------------------------------

@st.cache_data(ttl=1800, show_spinner=False)
def load_and_process_data(df_raw, is_admin=False):
    if df_raw.empty: return pd.DataFrame()
    try:
        num_cols = ['연배당금', '연배당률', '현재가', '신규상장개월수', '연배당금_크롤링']
        for col in num_cols:
            if col in df_raw.columns:
                df_raw[col] = pd.to_numeric(df_raw[col], errors='coerce').fillna(0)
        
        if '종목코드' in df_raw.columns:
            df_raw['종목코드'] = df_raw['종목코드'].apply(lambda x: str(x).split('.')[0].strip().zfill(6) if str(x).split('.')[0].strip().isdigit() else str(x).upper())
        
        if '배당락일' in df_raw.columns:
            df_raw['배당락일'] = df_raw['배당락일'].astype(str).replace(['nan', 'None', 'nan '], '-')
            
        if '자산유형' in df_raw.columns:
            df_raw['자산유형'] = df_raw['자산유형'].fillna('기타')
    except Exception: pass

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
            
            price = get_safe_price(broker, code, category) or 0
            
            crawled_div = float(row.get('연배당금_크롤링', 0))
            manual_div = float(row.get('연배당금', 0))        
            months = int(row.get('신규상장개월수', 0))

            target_div = (manual_div / months * 12) if (0 < months < 12 and manual_div > 0) else (crawled_div if crawled_div > 0 else manual_div)
            display_name = f"{name} ⭐" if (0 < months < 12) else name
            
            yield_val = (target_div / price * 100) if price > 0 else 0
            if is_admin and (yield_val < 2.0 or yield_val > 25.0): display_name = f"🚫 {display_name}"
            
            price_fmt = f"{int(price):,}원" if category == '국내' else f"${price:.2f}"
            auto_asset_type = classify_asset(row) 
            final_type = str(row.get('유형', '-'))
            if any(k in auto_asset_type for k in ['채권', '커버드콜', '리츠']): final_type = auto_asset_type.replace('🛡️ ', '').replace('🏦 ', '').replace('🏢 ', '')

            return idx, {
                '코드': code, '종목명': display_name,
                '블로그링크': str(row.get('블로그링크', '#')),
                '금융링크': f"https://m.stock.naver.com/domestic/stock/{code}/total" if category == '국내' else f"https://finance.yahoo.com/quote/{code}",
                '현재가': price_fmt, '연배당률': yield_val,
                '환구분': get_hedge_status(name, category),
                '배당락일': str(row.get('배당락일', '-')), '분류': category,
                '유형': final_type, '자산유형': auto_asset_type,
                'pure_name': name.replace("🚫 ", "").replace(" (필터대상)", ""), 
                '신규상장개월수': months,
                '배당기록': str(row.get('배당기록', ''))
            }
        except Exception: return idx, None

    with ThreadPoolExecutor(max_workers=10) as executor:
        futures = {executor.submit(process_row, idx, row): idx for idx, row in df_raw.iterrows()}
        for future in as_completed(futures):
            idx, result = future.result()
            results[idx] = result

    final_data = [r for r in results if r is not None]
    return pd.DataFrame(final_data).sort_values('연배당률', ascending=False) if final_data else pd.DataFrame()

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
        except Exception: time.sleep(0.5)
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
    except Exception as e:
        logger.error(f"Github Save Error: {e}")
        return False, f"❌ 저장 실패: {str(e)}"

# -----------------------------------------------------------
# [SECTION 4] 실시간 배당 정보 크롤링 (네이버 모바일 API 엔진)
# -----------------------------------------------------------

def fetch_dividend_yield_hybrid(code, category):
    code = str(code).strip()
    
    # [국내 주식]
    if category == '국내':
        # 1. KIS API (최우선)
        try:
            broker = mojito.KoreaInvestment(
                api_key=st.secrets["kis"]["app_key"],
                api_secret=st.secrets["kis"]["app_secret"],
                acc_no=st.secrets["kis"]["acc_no"],
                mock=True 
            )
            resp = broker.fetch_price(code)
            if resp and 'output' in resp:
                yield_str = resp['output'].get('hts_dvsd_rate', '0.0')
                if float(yield_str) > 0: return float(yield_str), "✅ 한투 API"
        except: pass

        # 2. [NEW] 네이버 모바일 API (사장님의 통찰력 적용!)
        # HTML을 긁는 게 아니라, 모바일 앱이 쓰는 진짜 데이터(JSON)를 가져옵니다.
        try:
            # 네이버 모바일 증권에서 사용하는 공식 API 주소입니다.
            url = f"https://api.stock.naver.com/stock/{code}/basic"
            headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/110.0.0.0 Safari/537.36'}
            
            res = requests.get(url, headers=headers, timeout=5)
            if res.status_code == 200:
                data = res.json()
                # API 응답에서 'dividendYield' (배당수익률) 필드 추출
                div_yield = data.get('dividendYield')
                
                if div_yield:
                    return float(div_yield), "✅ 네이버(Mobile)"
        except Exception as e:
            # API 실패 시 로그만 남기고 다음 단계(PC 크롤링)로 넘어갑니다.
            pass

        # 3. PC 버전 크롤링 (최후의 보루)
        try:
            url = f"https://finance.naver.com/item/main.naver?code={code}"
            headers = {'User-Agent': 'Mozilla/5.0'}
            response = requests.get(url, headers=headers, timeout=5)
            response.encoding = 'euc-kr' 

            # _dvr 태그 찾기
            dvr_match = re.search(r'<em id="_dvr">\s*([\d\.]+)\s*</em>', response.text)
            if dvr_match:
                val = float(dvr_match.group(1))
                if val > 0: return val, "✅ 네이버(PC)"
        except: pass

        return 0.0, "⚠️ 데이터 없음 (국내)"

    # [해외 주식]
    else:
        try:
            stock = yf.Ticker(code)
            dy = stock.info.get('dividendYield')
            if dy and dy > 0: return round(dy * 100, 2), "✅ 야후(Info)"
            
            divs = stock.dividends
            if not divs.empty:
                recent_total = divs.iloc[-12:].sum() if len(divs) > 12 else divs.sum()
                price = stock.fast_info.get('last_price')
                if price and price > 0:
                    val = (recent_total / price) * 100
                    if 0 < val < 50: return round(val, 2), f"✅ 야후(계산)"
            return 0.0, "⚠️ 데이터 없음"
        except Exception as e:
            return 0.0, f"❌ 해외 에러: {str(e)}"

def update_dividend_rolling(current_history_str, new_dividend_amount):
    """배당금 기록 갱신"""
    if pd.isna(current_history_str) or str(current_history_str).strip() == "":
        history = []
    else:
        try: history = [int(float(x)) for x in str(current_history_str).split('|') if x.strip()]
        except: history = []

    if len(history) >= 12: history.pop(0)
    history.append(int(new_dividend_amount))
    return sum(history), "|".join(map(str, history))
