"""
프로젝트: 배당 팽이 (Dividend Top) v2.7
파일명: logic.py
설명: 금융 API 연동, 데이터 크롤링, 캘린더 파일 생성 등 핵심 비즈니스 로직 (통합본)
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
from logger import logger  # 로깅 시스템 연동

# -----------------------------------------------------------
# [SECTION 1] 날짜 및 스케줄링 헬퍼 (공통 도구)
# -----------------------------------------------------------

def parse_dividend_date(date_str):
    """
    다양한 형태의 날짜 문자열('매월 15일', '2024-01-01')을 컴퓨터가 이해하는 날짜로 변환합니다.
    """
    s = str(date_str).strip()
    today = datetime.date.today()
    
    # 1. YYYY-MM-DD 형식
    try:
        return datetime.datetime.strptime(s, "%Y-%m-%d").date()
    except ValueError:
        pass
    
    # 2. '매월 XX일' 형식
    day_match = re.search(r'(\d+)', s)
    if day_match and ('매월' in s or '일' in s):
        try:
            day = int(day_match.group(1))
            # 날짜가 오늘보다 지났으면 다음달, 아니면 이번달 (단순 예시)
            target_date = datetime.date(today.year, today.month, day)
            if target_date < today:
                next_month = today.month + 1 if today.month < 12 else 1
                year = today.year if today.month < 12 else today.year + 1
                try:
                    return datetime.date(year, next_month, day)
                except ValueError: # 2월 30일 같은 경우 말일로
                    last_day = calendar.monthrange(year, next_month)[1]
                    return datetime.date(year, next_month, last_day)
            return target_date
        except ValueError:
            pass
            
    return None # 변환 실패 시

def generate_portfolio_ics(portfolio_data):
    """
    [NEW] 선택된 포트폴리오를 '내 캘린더에 한번에 넣기' 위한 파일(.ics)을 생성합니다.
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
        date_info = str(item.get('배당락일', '-'))
        
        # 날짜 파싱 시도
        day_match = re.search(r'(\d+)', date_info)
        
        # '매월 XX일' 패턴이면 향후 12개월치 생성
        if day_match and ('매월' in date_info or '일' in date_info):
            day = int(day_match.group(1))
            for i in range(12):
                month = today.month + i
                year = current_year + (month - 1) // 12
                month = (month - 1) % 12 + 1
                
                try:
                    # 해당 월의 말일 체크
                    last_day = calendar.monthrange(year, month)[1]
                    safe_day = min(day, last_day)
                    
                    event_date = datetime.date(year, month, safe_day)
                    
                    # D-3 매수 알림일 계산
                    buy_date = event_date - datetime.timedelta(days=3)
                    # 주말이면 금요일로 당김
                    while buy_date.weekday() >= 5:
                        buy_date -= datetime.timedelta(days=1)
                        
                    dt_start = buy_date.strftime("%Y%m%d")
                    dt_end = (buy_date + datetime.timedelta(days=1)).strftime("%Y%m%d")
                    
                    ics_content.extend([
                        "BEGIN:VEVENT",
                        f"DTSTART;VALUE=DATE:{dt_start}",
                        f"DTEND;VALUE=DATE:{dt_end}",
                        f"SUMMARY:💰 [{name}] 매수 알림 (D-3)",
                        f"DESCRIPTION:배당 기준일(예상): {event_date}\\n안전하게 오늘 매수하세요!",
                        "END:VEVENT"
                    ])
                except ValueError:
                    continue

    ics_content.append("END:VCALENDAR")
    return "\n".join(ics_content)


# -----------------------------------------------------------
# [SECTION 2] 시세 조회 및 유틸리티 함수
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
            except Exception as e:
                logger.warning(f"KIS Price Error ({code}): {e}")
        
        ticker_code = f"{code_str}.KS" if category == '국내' else code_str
        ticker = yf.Ticker(ticker_code)
        price = ticker.fast_info.get('last_price')
        if not price:
            hist = ticker.history(period="1d")
            if not hist.empty:
                price = hist['Close'].iloc[-1]
        return float(price) if price else None
    except Exception as e:
        logger.error(f"Price Fetch Error ({code}): {e}")
        return None

def get_safe_price(broker, code, category):
    for _ in range(2):
        price = _fetch_price_raw(broker, code, category)
        if price is not None: return price
        time.sleep(0.5)
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

    try:
        num_cols = ['연배당금', '연배당률', '현재가', '신규상장개월수', '연배당금_크롤링']
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

    # 브로커 초기화
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
                '환구분': get_hedge_status(name, category),
                '배당락일': str(row.get('배당락일', '-')), 
                '분류': category,
                '유형': final_type, 
                '자산유형': auto_asset_type,
                '캘린더링크': None, # ICS 파일 생성으로 대체됨
                'pure_name': name.replace("🚫 ", "").replace(" (필터대상)", ""), 
                '신규상장개월수': months,
                '배당기록': str(row.get('배당기록', '')),
                '검색라벨': str(row.get('검색라벨', f"[{code}] {display_name}"))
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
    return pd.DataFrame(final_data).sort_values('연배당률', ascending=False) if final_data else pd.DataFrame()


# -----------------------------------------------------------
# [SECTION 4] 데이터 파일 관리 (GitHub/CSV)
# -----------------------------------------------------------

@st.cache_data(ttl=1800)
def load_stock_data_from_csv():
    import os
    file_path = "stocks.csv"
    if not os.path.exists(file_path):
        return pd.DataFrame()
    try:
        df = pd.read_csv(file_path, dtype={'종목코드': str})
        df.columns = df.columns.str.strip()
        if '연배당금_크롤링' not in df.columns: df['연배당금_크롤링'] = 0.0
        return df
    except Exception as e:
        logger.error(f"CSV Load Error: {e}")
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
    """한투 API, 야후 파이낸스, 네이버 금융을 교차 활용하여 실시간 배당수익률 조회"""
    code = str(code).strip()
    
    # [국내 주식 조회 로직]
    if category == '국내':
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
                if yield_str and yield_str != '-' and float(yield_str) > 0:
                    return float(yield_str), "✅ 한투 API"
        except: pass

        try:
            ticker_code = f"{code}.KS"
            stock = yf.Ticker(ticker_code)
            dy = stock.info.get('dividendYield')
            if dy and dy > 0: return round(dy * 100, 2), "✅ 야후(Info)"
            divs = stock.dividends
            if not divs.empty:
                if divs.index.tz is not None: divs.index = divs.index.tz_localize(None)
                one_year_ago = pd.Timestamp.now() - pd.Timedelta(days=365)
                recent_total = divs[divs.index >= one_year_ago].sum()
                price = stock.fast_info.get('last_price')
                if not price: 
                    hist = stock.history(period='1d')
                    if not hist.empty: price = hist['Close'].iloc[-1]
                if price and price > 0:
                    yield_cal = (recent_total / price) * 100
                    if yield_cal > 0: return round(yield_cal, 2), "✅ 야후(Rolling)"
        except: pass

        try:
            url = f"https://finance.naver.com/item/main.naver?code={code}"
            headers = {'User-Agent': 'Mozilla/5.0'}
            response = requests.get(url, headers=headers)
            response.encoding = 'euc-kr' 
            dfs = pd.read_html(response.text)
            for df in dfs:
                table_str = df.to_string()
                if "배당수익률" in table_str or "분배금수익률" in table_str:
                    for col in df.columns:
                        col_list = df[col].astype(str).tolist()
                        for val in col_list:
                            if "%" in val:
                                try:
                                    num = float(val.replace("%", "").strip())
                                    if 0 < num < 30: return num, "✅ 네이버(Table)"
                                except: pass
            if '_dvr' in response.text:
                part = response.text.split('<em id="_dvr">')[1]
                val = part.split('</em>')[0]
                return float(val), "✅ 네이버(ID)"
        except Exception as e:
            return 0.0, f"❌ 네이버 에러: {str(e)}"

        return 0.0, "⚠️ 데이터 없음 (국내)"

    # [해외 주식 조회 로직]
    else:
        try:
            stock = yf.Ticker(code)
            try:
                divs = stock.dividends
                if not divs.empty:
                    if divs.index.tz is not None:
                        divs.index = divs.index.tz_localize(None)
                    one_year_ago = pd.Timestamp.now() - pd.Timedelta(days=365)
                    recent_divs = divs[divs.index >= one_year_ago]
                    recent_total = recent_divs.sum()
                    price = stock.fast_info.get('last_price')
                    if not price or price <= 0:
                        hist = stock.history(period="1d")
                        if not hist.empty: price = hist['Close'].iloc[-1]
                    if price and price > 0 and recent_total > 0:
                        yield_cal = (recent_total / price) * 100
                        if yield_cal > 50: yield_cal = yield_cal / 100
                        if 0 < yield_cal < 50:
                            return round(yield_cal, 2), f"✅ 야후(계산:${recent_total:.2f})"
            except: pass 

            dy = stock.info.get('dividendYield')
            if dy and dy > 0: 
                calc_dy = dy * 100
                if calc_dy > 50: calc_dy = dy 
                return round(calc_dy, 2), "✅ 야후(Info)"
            return 0.0, "⚠️ 데이터 없음"
        except Exception as e:
            return 0.0, f"❌ 해외 에러: {str(e)}"

def update_dividend_rolling(current_history_str, new_dividend_amount):
    """배당금 기록 갱신"""
    if pd.isna(current_history_str) or str(current_history_str).strip() == "":
        history = []
    else:
        history = [int(float(x)) for x in str(current_history_str).split('|')]

    if len(history) >= 12:
        history.pop(0)
        
    history.append(int(new_dividend_amount))
    new_annual_total = sum(history)
    new_history_str = "|".join(map(str, history))
    return new_annual_total, new_history_str

# -----------------------------------------------------------
# [SECTION 7] (추가) 개별 구글 캘린더 링크 생성기
# -----------------------------------------------------------

def get_google_cal_url(stock_name, date_str):
    """
    단일 종목에 대한 구글 캘린더 일정 등록 URL을 생성합니다. (D-3일 기준)
    """
    try:
        # 1. 날짜 파싱 (기존 함수 재활용)
        target_date = parse_dividend_date(date_str)
        if not target_date: return None
        
        # 2. 안전 매수일 계산 (D-3)
        # datetime.date 객체인지 확인
        if isinstance(target_date, datetime.date):
            safe_date = target_date - datetime.timedelta(days=3)
        else:
            return None

        # 주말이면 금요일로 당김
        while safe_buy_date.weekday() >= 5:
            safe_buy_date -= datetime.timedelta(days=1)

        # 3. URL 생성
        start_str = safe_date.strftime("%Y%m%d")
        end_str = (safe_date + datetime.timedelta(days=1)).strftime("%Y%m%d")
        
        base_url = "https://www.google.com/calendar/render?action=TEMPLATE"
        title = quote(f"💰 [{stock_name}] 매수 알림 (D-3)")
        details = quote(f"배당 기준일: {date_str}\n안전하게 오늘 매수하세요!")
        
        return f"{base_url}&text={title}&dates={start_str}/{end_str}&details={details}"
    except:
        return None
