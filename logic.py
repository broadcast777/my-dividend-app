"""
프로젝트: 배당 팽이 (Dividend Top) v2.9
파일명: logic.py
설명: 금융 API 연동, 데이터 크롤링, 캘린더 파일 생성 (데이터 무결성 강화 + 충돌 방지 패치 적용)
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
import sqlite3  # DB 에러 처리를 위해 추가


# -----------------------------------------------------------
# [SECTION 1] 날짜 및 스케줄링 헬퍼 (공통 도구)
# -----------------------------------------------------------

def standardize_date_format(date_str):
    """
    [NEW] 입력된 날짜 문자열을 'YYYY-MM-DD' 표준 포맷으로 1차 정규화합니다.
    (예: 2025.1.5 -> 2025-01-05, 2025/12/31 -> 2025-12-31)
    """
    s = str(date_str).strip()
    # 이미 YYYY-MM-DD 형식이면 패스
    if re.match(r'^\d{4}-\d{2}-\d{2}$', s):
        return s
    
    # 점(.)이나 슬래시(/)를 하이픈(-)으로 통일
    s = s.replace('.', '-').replace('/', '-')
    
    # 정규식으로 YYYY-M-D 패턴을 찾아 YYYY-MM-DD로 변환
    match = re.match(r'^(\d{4})-(\d{1,2})-(\d{1,2})$', s)
    if match:
        y, m, d = match.groups()
        return f"{y}-{m.zfill(2)}-{d.zfill(2)}"
    
    return s  # 변환 불가능하면 원본 반환 (parse_dividend_date에서 처리)

def parse_dividend_date(date_str):
    """
    다양한 형태의 날짜 문자열(월초, 월말, 특정일)을 datetime.date 객체로 변환합니다.
    """
    # 1. 포맷 표준화 시도
    s = standardize_date_format(str(date_str))
    today = datetime.date.today()
    
    # 2. YYYY-MM-DD 형식 파싱 시도
    try:
        return datetime.datetime.strptime(s, "%Y-%m-%d").date()
    except ValueError:
        pass
    
    # 3. 키워드 분석 (월말/월초/특정일)
    is_end_of_month = any(k in s for k in ['말일', '월말', '마지막', '하순', 'END'])
    is_start_of_month = any(k in s for k in ['매월 초', '월초', '1~3일', 'BEGIN'])
    
    # 숫자만 추출
    day_match = re.search(r'(\d+)', s)
    
    if is_end_of_month or is_start_of_month or (day_match and ('매월' in s or '일' in s)):
        try:
            if is_end_of_month:
                day = calendar.monthrange(today.year, today.month)[1] # 이번달 말일
            elif is_start_of_month:
                day = 1 
            else:
                day = int(day_match.group(1))
            
            # 이번 달 기준 날짜 생성
            try:
                # 해당 월에 없는 날짜(예: 2월 30일)면 말일로 자동 보정
                last_day_actual = calendar.monthrange(today.year, today.month)[1]
                safe_day = min(day, last_day_actual)
                target_date = datetime.date(today.year, today.month, safe_day)
            except ValueError:
                target_date = today # 안전 장치
            
            # 이미 지났으면 다음 달로 넘김
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
    (조건: D-4 알림 + 과거 일정 스킵 + 오늘부터 '올해 12월 31일'까지만 생성)
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
        # 데이터가 없을 경우 '-' 처리하여 에러 방지
        date_info = str(item.get('배당락일', '-')).strip()
        if date_info in ['-', 'nan', 'None', '']: continue

        # 1. 키워드 파싱
        is_end_of_month = any(k in date_info for k in ['말일', '월말', '마지막', '30일', '31일', '하순'])
        is_start_of_month = any(k in date_info for k in ['매월 초', '월초', '1~3일'])
        day_match = re.search(r'(\d+)', date_info)
        
        target_day = None
        if is_end_of_month: target_day = 'END'
        elif is_start_of_month: target_day = 1
        elif day_match: # '일' 글자가 없더라도 숫자가 있으면 시도
            target_day = int(day_match.group(1))
        
        # 날짜 포맷이 '2025-05-15' 처럼 고정일인 경우 처리 로직 추가
        fixed_date_obj = None
        if '-' in date_info or '.' in date_info:
             parsed = parse_dividend_date(date_info)
             if parsed: fixed_date_obj = parsed

        # 2. 스마트 날짜 계산 Loop
        if target_day is not None or fixed_date_obj:
            check_idx = 0
            
            # 고정 날짜 하나만 있는 경우 (연배당 등)
            if fixed_date_obj:
                 # D-4 계산 로직 공통화 필요하지만, 일단 여기서는 생략하고 반복문 로직 태움
                 # 만약 고정일이면 아래 반복문 대신 단건 처리로 빠져야 함.
                 # 여기서는 '매월' 배당 위주로 처리
                 pass 

            # 최대 12개월을 탐색하되, 해가 바뀌면 중단
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
                        continue # 처리 불가
                    
                    event_date = datetime.date(year, month, safe_day)
                    
                    # D-4 계산 (4일 전 알림)
                    buy_date = event_date - datetime.timedelta(days=4)
                    
                    # 주말이면 금요일로 당김
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
    [단일 등록용] 구글 캘린더 일정 등록 URL 생성 (D-4일 기준)
    """
    try:
        target_date = parse_dividend_date(date_str)
        if not target_date: return None
        
        if isinstance(target_date, datetime.date):
            safe_buy_date = target_date - datetime.timedelta(days=4) 
        else:
            return None

        # 주말이면 금요일로 당김
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
            f"이 알림은 과거 데이터를 기반으로 생성된 '예상 일정'입니다.\n"
            f"운용사 정책 변경(예: 15일→월말)으로 실제 배당일이 바뀔 수 있습니다.\n"
            f"안전한 투자를 위해, 매수 전 반드시 '운용사 공식 홈페이지' 공시를 확인해주세요."
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
    """네이버 모바일 API로 현재가 조회 (한투 실패 시 백업용)"""
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
    """
    [핵심 수정] DB Locked 에러 방지를 위한 안전 조회 로직
    """
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
                # 한투 에러는 로그만 남기고 yfinance 시도 안함 (국내는 yfinance 데이터 부실)
                logger.warning(f"KIS Price Error ({code}): {e}")
                return None
        
        # 2. 해외 주식 (Yfinance) - Locked 에러 주범
        ticker_code = f"{code_str}.KS" if category == '국내' else code_str
        
        # 🚨 [패치] yfinance가 내부적으로 sqlite 캐시를 쓰면서 충돌 발생
        # 충돌 시 잠시 대기 후 재시도 (Retry Pattern)
        max_retries = 3
        for attempt in range(max_retries):
            try:
                ticker = yf.Ticker(ticker_code)
                price = ticker.fast_info.get('last_price')
                
                # fast_info 실패 시 history 조회
                if not price:
                    hist = ticker.history(period="1d")
                    if not hist.empty:
                        price = hist['Close'].iloc[-1]
                
                if price: return float(price)
            
            except sqlite3.OperationalError: 
                # DB 잠금 에러 발생 시
                if attempt < max_retries - 1:
                    time.sleep(0.5) # 0.5초 대기 후 재시도
                    continue
                else:
                    logger.error(f"DB Locked Fail ({code}): Max retries exceeded")
            except Exception:
                break # 다른 에러면 재시도 의미 없음
                
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
# [SECTION 3] 메인 데이터 로드 및 병렬 처리 엔진
# -----------------------------------------------------------

@st.cache_data(ttl=1800, show_spinner=False)
def load_and_process_data(df_raw, is_admin=False):
    if df_raw.empty: return pd.DataFrame()

    # 1. 데이터 전처리 (결측치 방어)
    try:
        num_cols = ['연배당금', '연배당률', '현재가', '신규상장개월수', '연배당금_크롤링']
        for col in num_cols:
            if col in df_raw.columns:
                # 문자가 섞여있을 경우 강제 변환 후 NaN은 0으로
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
    
    # 3. 병렬 처리 작업자
    def process_row(idx, row):
        try:
            code = str(row.get('종목코드', '')).strip()
            name = str(row.get('종목명', '')).strip()
            category = str(row.get('분류', '국내')).strip()
            
            # 가격 조회 (Safe Logic 적용)
            price = get_safe_price(broker, code, category)
            if not price: price = 0 

            # [수정] 데이터 준비 (Auto, TTM, 수동, 기존)
            auto_val = float(row.get('연배당금_크롤링_auto', 0) or 0)
            ttm_rate = float(row.get('TTM_연배당률(크롤링)', 0) or 0)
            manual_val = float(row.get('연배당금', 0) or 0)
            old_crawled = float(row.get('연배당금_크롤링', 0) or 0)
            months = int(row.get('신규상장개월수', 0))

            # [수정] 우선순위 로직 적용 (신규 > Auto > TTM > 수동 > 기존)
            if 0 < months < 12 and manual_val > 0:
                target_div = (manual_val / months) * 12
                display_name = f"{name} ⭐({months}개월)"
            
            elif auto_val > 0: # 1순위: Auto
                target_div = auto_val
                display_name = name
                
            elif ttm_rate > 0 and price > 0: # 2순위: TTM
                target_div = price * (ttm_rate / 100)
                display_name = f"{name} (TTM)"
                
            elif manual_val > 0: # 3순위: 수동
                target_div = manual_val
                display_name = name
                
            else: # 4순위: 기존
                target_div = old_crawled
                display_name = name

            # 수익률 계산 (가격이 없으면 0)
            yield_val = (target_div / price * 100) if price > 0 else 0

            if is_admin and (yield_val < 2.0 or yield_val > 25.0): display_name = f"🚫 {display_name}"

            # ... (위쪽 로직은 그대로) ...
            
            # [수정] 배당금도 포맷팅 (원/달러)
            if category == '국내':
                price_fmt = f"{int(price):,}원"
                div_fmt = f"{int(target_div):,}원" # 348원
            else:
                price_fmt = f"${price:.2f}"
                div_fmt = f"${target_div:.2f}"   # $4.72

            csv_type = str(row.get('유형', '-'))
            auto_asset_type = classify_asset(row) 
            
            final_type = csv_type
            if '채권' in auto_asset_type: final_type = '채권'
            elif '커버드콜' in auto_asset_type: final_type = '커버드콜'
            elif '리츠' in auto_asset_type: final_type = '리츠'

            return idx, {
                '코드': code, 
                '종목명': display_name,
                '연배당금': div_fmt,  # 👈 [핵심] 이 줄이 빠져 있었습니다! 이제 348원이 보일 겁니다.
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
        except Exception as e:
            logger.error(f"Row Processing Error ({idx}): {e}")
            return idx, None

    # 스레드 풀 실행 (yfinance 충돌 완화를 위해 워커 수 조절 가능)
    with ThreadPoolExecutor(max_workers=10) as executor:
        futures = {executor.submit(process_row, idx, row): idx for idx, row in df_raw.iterrows()}
        for future in as_completed(futures):
            idx, result = future.result()
            results[idx] = result

    final_data = [r for r in results if r is not None]
    return pd.DataFrame(final_data).sort_values('연배당률', ascending=False) if final_data else pd.DataFrame()


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
                # 빈 프레임을 반환하되 필수 컬럼을 보장
                df_empty = pd.DataFrame()
                required_cols = ['종목코드', '종목명', '연배당금_크롤링_auto', '연배당률_크롤링', '배당기록', '연배당금_크롤링']
                for c in required_cols:
                    df_empty[c] = pd.Series(dtype='object' if c in ['종목코드','종목명','배당기록'] else 'float')
                return df_empty

            # encoding='utf-8-sig'로 BOM 제거 시도, 모든 컬럼을 우선 문자열로 읽음
            df = pd.read_csv(file_path, dtype=str, encoding='utf-8-sig')
            # 컬럼명 정규화: strip + BOM 제거 + 보이지 않는 문자 제거
            def _normalize_col(c):
                if c is None: return ""
                s = str(c)
                s = s.replace('\ufeff', '').strip()
                # 추가로 제어문자 제거
                s = "".join(ch for ch in s if ord(ch) >= 32)
                return s
            df.columns = [_normalize_col(c) for c in df.columns]

            # 필수 컬럼 보장: 없으면 기본값으로 생성
            if '연배당금_크롤링' not in df.columns:
                df['연배당금_크롤링'] = 0.0
            if '연배당금_크롤링_auto' not in df.columns:
                df['연배당금_크롤링_auto'] = 0.0
            if '연배당률_크롤링' not in df.columns:
                df['연배당률_크롤링'] = 0.0
            if '배당기록' not in df.columns:
                df['배당기록'] = ""
            if '종목코드' not in df.columns:
                # 인덱스를 코드로 사용하거나 빈 문자열로 채움
                df['종목코드'] = df.index.astype(str).apply(lambda x: x.zfill(6) if x.isdigit() else x)

            # 종목코드 컬럼도 문자열 정규화(공백 제거)
            df['종목코드'] = df['종목코드'].astype(str).str.strip()

            return df
        except Exception as e:
            logger.warning(f"CSV load attempt failed: {e}")
            time.sleep(0.5)

    logger.error("CSV Load Failed after retries")
    return pd.DataFrame()


def save_to_github(df):
    """
    깃허브에 CSV로 덮어쓰기(자동 갱신용).
    st.secrets에 github.token, repo_name, file_path가 설정되어 있어야 합니다.
    """
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

# ---------- 배당 판정 설정 ----------
DIV_OVERRIDE_REL_THRESHOLD = 0.30   # 기존 대비 상대 차이 30% 이상이면 의심
DIV_ABS_YIELD_THRESHOLD = 10.0      # 연배당률 10% 초과면 의심
DIV_MAX_ACCEPT_YIELD = 50.0         # 운영상 안전 상한
# -------------------------------------

def detect_special_dividend(annual_from_latest, existing_annual, price):
    """
    특별배당 의심 판정
    반환: (special_flag: bool, reason: str)
    """
    try:
        if annual_from_latest is None or annual_from_latest == 0:
            return False, ""
        # 절대 연배당률 기준
        if price and price > 0:
            yield_pct = (annual_from_latest / price) * 100.0
            if yield_pct > DIV_MAX_ACCEPT_YIELD:
                return True, f"yield_excess>{DIV_MAX_ACCEPT_YIELD}"
            if yield_pct > DIV_ABS_YIELD_THRESHOLD:
                return True, f"abs_yield>{DIV_ABS_YIELD_THRESHOLD}"
        # 기존값 대비 상대 차이
        if existing_annual and existing_annual > 0:
            rel = abs(annual_from_latest - existing_annual) / existing_annual
            if rel > DIV_OVERRIDE_REL_THRESHOLD:
                return True, f"rel_diff>{DIV_OVERRIDE_REL_THRESHOLD}"
        return False, ""
    except Exception as e:
        logger.warning(f"detect_special_dividend error: {e}")
        return False, ""


# -----------------------------------------------------------
# [SECTION 6] 실시간 배당 정보 크롤링 (Hybrid)
# -----------------------------------------------------------

def fetch_dividend_yield_hybrid(code, category):
    """
    국내: requests로 최신배당금 캡처 -> x12 / 한투 실시간 주가 계산
    해외: yfinance 기반 안정화 로직 (fast_info + dividends + history + fallback)
    """
    code = str(code).strip()

    if category == '국내':
        # (A) 한투 API로 '실시간 주가' 확보
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

        # (B) requests로 네이버 API 직접 호출 (Playwright 제거)
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

        # (C) 최종 실시간 배당률 계산
        if current_price > 0 and latest_div > 0:
            try:
                yield_val = (latest_div * 12) / current_price * 100
                return round(yield_val, 2), f"✅ 실시간({int(latest_div)}원)"
            except Exception:
                pass

        # (D) 백업: 한투 전산 배당률 반환 시도
        try:
            if resp and 'output' in resp:
                backup = resp['output'].get('hts_dvsd_rate')
                if backup and backup != '-':
                    return float(backup), "✅ 한투API(백업)"
        except Exception:
            pass

        # (E) 국내 최종 실패
        return 0.0, "⚠️ 조회 실패"

    else:
        # 해외: yfinance 안정화 로직 (fast_info + dividends 기반 계산)
        try:
            ticker = yf.Ticker(code)

            # 1) 현재가 확보 시도 (fast_info 우선)
            price = None
            try:
                price = ticker.fast_info.get('last_price')
            except Exception:
                price = None

            # 2) 배당 기록(최근 1년 합계) 확보 (tz-aware 안전 처리)
            annual_div_sum = 0.0
            try:
                divs = ticker.dividends
                if divs is not None and len(divs) > 0:
                    idx = divs.index
                    # cutoff를 인덱스 tz에 맞춰 생성
                    try:
                        tz = getattr(idx, 'tz', None)
                        if tz is not None:
                            cutoff = pd.Timestamp.now(tz=tz) - pd.Timedelta(days=365)
                        else:
                            cutoff = pd.Timestamp.now() - pd.Timedelta(days=365)
                    except Exception:
                        cutoff = pd.Timestamp.now() - pd.Timedelta(days=365)

                    # 안전 비교
                    try:
                        recent = divs[divs.index >= cutoff]
                    except Exception:
                        # 비교 실패 시 최근 4개로 대체
                        recent = divs.tail(4)

                    if recent.empty:
                        recent = divs.tail(4)
                    annual_div_sum = float(recent.sum())
            except Exception as e_div:
                logger.warning(f"yfinance dividends read failed for {code}: {e_div}")
                annual_div_sum = 0.0

            # 3) 가격이 없으면 history로 대체 시도
            if not price:
                try:
                    hist = ticker.history(period="5d")
                    if not hist.empty:
                        price = float(hist['Close'].iloc[-1])
                except Exception as e_hist:
                    logger.warning(f"yfinance history read failed for {code}: {e_hist}")
                    price = None

            # 4) 연배당률 계산 우선순위
            if price and price > 0 and annual_div_sum and annual_div_sum > 0:
                yield_pct = (annual_div_sum / price) * 100.0
                return round(yield_pct, 2), f"✅ 야후(계산: {annual_div_sum:.2f}/{price:.2f})"
            else:
                # fallback: info.dividendYield 시도
                try:
                    info_dy = ticker.info.get('dividendYield')
                    if info_dy:
                        calc_val = info_dy * 100
                        return round(calc_val, 2), "✅ 야후(Info)"
                except Exception as e_info:
                    logger.warning(f"yfinance info.dividendYield failed for {code}: {e_info}")

            # 모든 시도 실패 시
            return 0.0, "⚠️ 데이터 없음"
        except Exception as e:
            logger.exception(f"해외 배당 조회 예외: {code} - {e}")
            return 0.0, "❌ 해외 에러"

# -----------------------------------------------------------
# [SECTION 7] 스마트 업데이트 (전체 종목 일괄 갱신)
# -----------------------------------------------------------

def _fetch_domestic_sensor(code):
    """(내부용) 네이버에서 연배당금(Auto)과 TTM수익률 가져오기"""
    try:
        headers = {
            "User-Agent": "Mozilla/5.0", 
            "Referer": f"https://m.stock.naver.com/domestic/stock/{code}/analysis"
        }
        # 1. 배당금 내역 (pageSize=200으로 넓게 탐색)
        hist_url = f"https://m.stock.naver.com/api/etf/{code}/dividend/history?page=1&pageSize=200"
        r = requests.get(hist_url, headers=headers, timeout=5)
        
        auto_amt = 0.0
        if r.status_code == 200:
            items = r.json().get('result', {}).get('items', [])
            if items:
                # 첫 번째 유효한 배당금 찾기
                first = items[0]
                for k in ["dividendAmount", "dividend", "distribution"]:
                    if k in first and first[k]:
                        auto_amt = float(str(first[k]).replace(',', '')) * 12
                        break
                        
        # 2. TTM 수익률 (정보 페이지)
        info_url = f"https://m.stock.naver.com/api/stock/{code}/integration"
        r2 = requests.get(info_url, headers=headers, timeout=5)
        ttm_rate = 0.0
        if r2.status_code == 200:
            ttm_rate = float(r2.json().get('totalInfo', {}).get('dividendYield', 0))
            
        return auto_amt, ttm_rate
    except:
        return 0.0, 0.0

def _fetch_overseas_sensor(code):
    """(내부용) 야후에서 연배당금($)과 TTM수익률 가져오기"""
    try:
        ticker = yf.Ticker(code)
        # 1. 연배당금 (최근 1년 합계)
        divs = ticker.dividends
        if not divs.empty:
            cutoff = pd.Timestamp.now(tz=divs.index.tz) - pd.Timedelta(days=365)
            annual_sum = float(divs[divs.index >= cutoff].sum())
        else:
            annual_sum = 0.0
            
        # 2. TTM 수익률
        ttm_yield = ticker.info.get('trailingAnnualDividendYield', 0)
        if ttm_yield == 0: ttm_yield = ticker.info.get('dividendYield', 0)
        
        # 0.08 -> 8.0 변환
        if 0 < ttm_yield < 1: ttm_yield *= 100
            
        return annual_sum, round(ttm_yield, 2)
    except:
        return 0.0, 0.0

def smart_update_and_save():
    """
    [핵심] 앱에서 버튼 누르면 실행되는 함수 (성공/실패/보호 카운팅 기능 추가)
    모든 종목을 돌며 Auto(1순위)와 TTM(2순위) 데이터를 채우고 깃허브에 저장합니다.
    """
    import sys
    import time
    import streamlit as st # 화면 표시용
    
    try:
        # 1. CSV 파일 로드
        df = load_stock_data_from_csv()
        if df.empty: return False, "❌ CSV 파일을 찾을 수 없거나 비어있습니다."
        
        total_count = len(df)
        success_count = 0
        fail_count = 0
        protected_count = 0 # 신규 상장 보호 카운트
        
        # [UI] 진행률 표시줄
        progress_text = "데이터 갱신 시작..."
        my_bar = st.progress(0, text=progress_text)
        status_text = st.empty() # 실시간 상태 메시지
        
        # 2. 전체 종목 루프
        for idx, row in df.iterrows():
            code = str(row['종목코드']).strip()
            name = row['종목명']
            category = str(row.get('분류', '국내')).strip()
            
            # 신규 상장 개월수 확인
            try: months = int(row.get('신규상장개월수', 0))
            except: months = 0
            
            # -----------------------------------------------------
            # [조건] 신규 상장(1년 미만)은 크롤링 보호 (기존 데이터 유지)
            # -----------------------------------------------------
            if 0 < months < 12:
                protected_count += 1
                status_text.markdown(f"🛡️ **[{idx+1}/{total_count}] {name}** (신규 {months}개월) -> 보호됨(건너뜀)")
                time.sleep(0.05) # 너무 빠르면 안 보여서 살짝 대기
                # 진행률 바 업데이트만 하고 다음으로 넘어감
                my_bar.progress((idx + 1) / total_count, text=f"진행률: {int((idx+1)/total_count*100)}%")
                continue
            
            # -----------------------------------------------------
            # [일반] 나머지 종목은 크롤링 진행
            # -----------------------------------------------------
            status_text.markdown(f"🔄 **[{idx+1}/{total_count}] {name}** 데이터 수집 중...")
            
            try:
                if category == '국내':
                    val, rate = _fetch_domestic_sensor(code)
                else:
                    val, rate = _fetch_overseas_sensor(code)
                
                # 데이터 업데이트 (값이 0보다 클 때만)
                if val > 0: df.at[idx, '연배당금_크롤링_auto'] = val
                if rate > 0: df.at[idx, 'TTM_연배당률(크롤링)'] = rate
                
                success_count += 1
                
            except Exception as e:
                fail_count += 1
                logger.warning(f"Update fail {code}: {e}")
                # 실패해도 멈추지 않고 진행
            
            # 서버 부하 방지 및 진행률 업데이트
            time.sleep(0.1) 
            my_bar.progress((idx + 1) / total_count, text=f"진행률: {int((idx+1)/total_count*100)}%")
                
        # 3. 마무리 및 저장
        final_msg = f"✨ 완료! (성공: {success_count} / 실패: {fail_count} / 🛡️신규보호: {protected_count}개)"
        status_text.success(final_msg)
        my_bar.empty() # 진행바 제거
        
        # 깃허브 저장
        if hasattr(sys.modules[__name__], 'save_to_github'):
            return save_to_github(df)
        else:
            df.to_csv("stocks.csv", index=False, encoding='utf-8-sig')
            return True, f"✅ 로컬 저장 완료! {final_msg}"
            
    except Exception as e:
        return False, f"스마트 업데이트 실패: {e}"



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
