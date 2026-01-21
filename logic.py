"""
프로젝트: 배당 팽이 (Dividend Top) v3.0 (Updated)
파일명: logic.py
설명: 금융 API 연동, 데이터 크롤링, 캘린더 파일 생성 (데이터 무결성 강화 + 충돌 방지 패치 적용 + 자동 크롤링 방어 로직)
업데이트: 2026.01.21
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


# [코랩 검증] 데이터 추출용 키 후보
DATE_KEYS = ["exDividendAt","localDate","exDate","date","dateTime","payDate","recordDate"]
AMT_KEYS = ["dividendAmount","dividend","distribution","amount","value","payAmount","pay_amount"]


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

def fetch_latest_dividend_amount(code):
    """
    [2중 방어] 
    1순위: 최근 배당금(51원) x 12 (가장 최신 트렌드 반영)
    2순위: TTM(345원) (지난 1년간 실제 지급 총액, 안전빵)
    결과: '연간 배당금 총액'을 반환함
    """
    headers = {
        "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 15_0 like Mac OS X)", 
        "Referer": f"https://m.stock.naver.com/domestic/stock/{code}/analysis"
    }
    
    # ---------------------------------------------------------
    # [1단계] History API 찌르기 (최신 배당금 x 12)
    # ---------------------------------------------------------
    try:
        url_hist = f"https://m.stock.naver.com/api/etf/{code}/dividend/history?page=1&pageSize=20"
        res = requests.get(url_hist, headers=headers, timeout=3)
        if res.status_code == 200:
            data = res.json()
            items = []
            if isinstance(data, list): items = data
            elif isinstance(data, dict):
                items = data.get('result', {}).get('items') or data.get('items') or []
            
            if items:
                first = items[0]
                for k in ["dividend", "dividendAmount", "amount"]:
                    if k in first and first[k]:
                        one_time = float(str(first[k]).replace(',', ''))
                        # 1회분을 연배당으로 환산해서 반환
                        return one_time * 12 
    except:
        pass # 1단계 실패 시 조용히 2단계로 이동

    # ---------------------------------------------------------
    # [2단계] TTM API 찌르기 (1년치 합계) - 여기가 후속 로직!
    # ---------------------------------------------------------
    try:
        url_ttm = f"https://m.stock.naver.com/api/stock/{code}/etfAnalysis"
        res = requests.get(url_ttm, headers=headers, timeout=3)
        if res.status_code == 200:
            data = res.json()
            # TTM 데이터 파싱
            div_data = data.get("dividend", {}) or data.get("result", {}).get("dividend", {})
            ttm_amt = div_data.get("dividendPerShareTtm")
            
            if ttm_amt:
                # TTM은 이미 연간 합계이므로 그대로 반환
                return float(str(ttm_amt).replace(',', ''))
    except:
        pass # 2단계도 실패하면 None 반환

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
        num_cols = ['연배당금', '연배당률', '현재가', '신규상장개월수', '연배당금_크롤링', '연배당금_크롤링_auto', '연배당률_크롤링']

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
            
            # 가격 조회
            price = get_safe_price(broker, code, category)
            if not price: price = 0

            # ==========================================================
            # [수정] 3중 철벽 방어 로직 (Live -> Cache -> Manual)
            # ==========================================================
            
            # 0. 변수 초기화
            auto_annual_div = None  # 이번에 가져올 실시간 값
            saved_auto_div = float(row.get('연배당금_크롤링_auto', 0)) # CSV에 저장된 지난번 값
            
            # 1. [1차/2차 방어] 실시간 크롤링 시도 (History -> TTM)
            if category == '국내':
                auto_annual_div = fetch_latest_dividend_amount(code)
                
                if auto_annual_div:
                    # 성공! -> CSV 업데이트 준비
                    row['연배당금_크롤링_auto'] = auto_annual_div
                    if price > 0:
                        row['연배당률_크롤링'] = round((auto_annual_div / price) * 100, 2)
                else:
                    # 실패! -> [3차 방어] CSV에 있던 지난번 값 재사용 (캐시)
                    if saved_auto_div > 0:
                        auto_annual_div = saved_auto_div
                        # (선택) 로그에 남기기: print(f"{code} API 실패, 캐시 데이터 사용")

            # 2. 최종 배당금 결정 (우선순위: 실시간/캐시 > 과거크롤링 > 수동)
            manual_div = float(row.get('연배당금', 0))
            orig_crawled = float(row.get('연배당금_크롤링', 0) or 0)
            months = int(row.get('신규상장개월수', 0))

            if auto_annual_div and auto_annual_div > 0:
                # 깡패 모드: (방금 가져왔든, 저장된 거든) 자동 데이터가 있으면 씀
                target_div = auto_annual_div
                display_name = f"{name} ⭐" if 0 < months < 12 else name
                
            else:
                # 쭈구리 모드: 3차 방어까지 다 뚫림 -> 기존 수동/구버전 데이터 사용
                if 0 < months < 12:
                    target_div = (manual_div / months * 12) if manual_div > 0 else (orig_crawled or 0)
                    display_name = f"{name} ⭐"
                else:
                    target_div = orig_crawled if orig_crawled > 0 else manual_div
                    display_name = name
            # ==========================================================
            
            # 연배당률 계산
            yield_val = (target_div / price * 100) if price > 0 else 0

            if is_admin and (yield_val < 2.0 or yield_val > 25.0):
                display_name = f"🚫 {display_name}"

            price_fmt = f"{int(price):,}원" if category == '국내' else f"${price:.2f}"
            
            csv_type = str(row.get('유형', '-'))
            auto_asset_type = classify_asset(row) 
            
            final_type = csv_type
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
                '연배당금_크롤링_auto': row.get('연배당금_크롤링_auto', 0),
                '연배당률_크롤링': row.get('연배당률_크롤링', None),
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
    
    # 🚨 [패치] 파일 접근 충돌 방지 (Retry Logic)
    for _ in range(3):
        try:
            if not os.path.exists(file_path):
                return pd.DataFrame()
            
            df = pd.read_csv(file_path, dtype={'종목코드': str})
            df.columns = df.columns.str.strip()
            if '연배당금_크롤링' not in df.columns: df['연배당금_크롤링'] = 0.0

            # <<< 여기에 새 컬럼 기본값 채우기 시작 >>>
            if '연배당금_크롤링_auto' not in df.columns:
                df['연배당금_크롤링_auto'] = 0.0
            if '연배당률_크롤링' not in df.columns:
                df['연배당률_크롤링'] = 0.0
            # <<< 여기에 새 컬럼 기본값 채우기 끝 >>>

            return df
        except Exception:
            time.sleep(0.5) # 잠겨있으면 0.5초 대기
    
    logger.error("CSV Load Failed after retries")
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
# [SECTION 6] 실시간 배당 정보 크롤링 (Hybrid)
# -----------------------------------------------------------

def fetch_dividend_yield_hybrid(code, category):
    """
    국내: Playwright 최신배당금 캡처 -> x12 / 한투 실시간 주가 계산
    해외: 야후 파이낸스 연배당률 유지
    """
    code = str(code).strip()
    
    if category == '국내':
        # (A) 한투 API로 '실시간 주가' 확보
        current_price = 0
        try:
            broker = mojito.KoreaInvestment(api_key=st.secrets["kis"]["app_key"], api_secret=st.secrets["kis"]["app_secret"], acc_no=st.secrets["kis"]["acc_no"], mock=True)
            resp = broker.fetch_price(code)
            if resp and 'output' in resp:
                current_price = float(resp['output'].get('stck_prpr', 0))
        except: pass
        
        if current_price == 0: current_price = _fetch_naver_price(code) # 백업 시도
        
        # (B) Playwright로 네이버 API 가로채기 (최신 배당금 1건)
        latest_div = 0
        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                page = browser.new_page()
                api_url = f"https://m.stock.naver.com/api/etf/{code}/dividend/history"
                page.goto(f"https://m.stock.naver.com/etf/{code}/dividend", wait_until="networkidle")
                content = page.evaluate(f"fetch('{api_url}').then(res => res.json())")
                
                if content and 'result' in content and 'items' in content['result']:
                    items = content['result']['items']
                    if items: latest_div = float(str(items[0].get('dividend', 0)).replace(',', ''))
                browser.close()
        except Exception as e:
            logger.error(f"❌ Playwright 실패: {e}")

        # (C) 최종 실시간 배당률 계산
        if current_price > 0 and latest_div > 0:
            yield_val = (latest_div * 12) / current_price * 100
            return round(yield_val, 2), f"✅ 실시간({int(latest_div)}원)"
        
        # [백업] 실패 시 한투 전산 배당률이라도 반환
        try:
            if resp and 'output' in resp:
                backup = resp['output'].get('hts_dvsd_rate')
                if backup and backup != '-': return float(backup), "✅ 한투API(백업)"
        except: pass
        return 0.0, "⚠️ 조회 실패"

    else:
        # [해외] 야후 파이낸스 로직 (기존 유지)
        try:
            stock = yf.Ticker(code)
            dy = stock.info.get('dividendYield')
            if dy:
                calc_val = dy * 100
                if calc_val > 50: calc_val = dy # 뻥튀기 보정
                return round(calc_val, 2), "✅ 야후(Info)"
            return 0.0, "⚠️ 데이터 없음"
        except: return 0.0, "❌ 해외 에러"

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
