"""
프로젝트: 배당 팽이 (Dividend Top) - 핵심 로직 모듈
파일명: logic.py
설명: 데이터 크롤링, 우선순위 로직(Auto/TTM/Manual), GitHub 연동, 캘린더 생성 등 백엔드 기능 담당
최종 정리: 2026.01.24
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
import sys

# =============================================================================
# [SECTION 1] 날짜 계산 및 캘린더 유틸리티
# =============================================================================

def standardize_date_format(date_str):
    """
    날짜 문자열 정규화 (YYYY.MM.DD 등 -> YYYY-MM-DD)
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
    배당락일 파싱 (월초/월말/특정일 텍스트를 실제 날짜 객체로 변환)
    """
    s = standardize_date_format(str(date_str))
    today = datetime.date.today()
    
    # 1. 표준 날짜 형식 시도
    try:
        return datetime.datetime.strptime(s, "%Y-%m-%d").date()
    except ValueError:
        pass
    
    # 2. 텍스트 패턴 분석 (말일, 월초 등)
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
            
            # 날짜 보정 (2월 30일 방지 등)
            try:
                last_day_actual = calendar.monthrange(today.year, today.month)[1]
                safe_day = min(day, last_day_actual)
                target_date = datetime.date(today.year, today.month, safe_day)
            except ValueError:
                target_date = today 
            
            # 이미 지난 날짜면 다음 달로 설정
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
    전체 포트폴리오 캘린더 파일(.ics) 생성 (D-4 알림 포함)
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

        # 향후 12개월 일정 생성
        if target_day is not None or fixed_date_obj:
            check_idx = 0
            if fixed_date_obj:
                 pass 

            while check_idx < 12:
                month_calc = today.month + check_idx
                year = current_year + (month_calc - 1) // 12
                month = (month_calc - 1) % 12 + 1
                check_idx += 1 
                
                if year > current_year: break
                
                try:
                    last_day_of_month = calendar.monthrange(year, month)[1]
                    
                    if target_day == 'END':
                        safe_day = last_day_of_month
                    elif isinstance(target_day, int):
                        safe_day = min(target_day, last_day_of_month)
                    else:
                        continue 
                    
                    event_date = datetime.date(year, month, safe_day)
                    
                    # D-4 매수 권장일 계산 (주말 제외)
                    buy_date = event_date - datetime.timedelta(days=4)
                    while buy_date.weekday() >= 5: 
                        buy_date -= datetime.timedelta(days=1)
                    
                    if buy_date < today: continue
                        
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
    구글 캘린더 등록 링크 생성 (단건)
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


# =============================================================================
# [SECTION 2] 가격 조회 및 자산 분류 유틸리티
# =============================================================================

def _fetch_naver_price(code):
    """네이버 API 백업 가격 조회"""
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
    주가 조회 통합 함수 (한투 API 우선 -> 실패 시 YFinance/네이버)
    * SQLite Locked 에러 방지를 위한 재시도 로직 포함
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
                # DB 잠금 에러 발생 시 대기 후 재시도
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
    """가격 조회 래퍼 (실패 시 1회 재시도)"""
    for _ in range(2):
        price = _fetch_price_raw(broker, code, category)
        if price is not None: return price
        time.sleep(0.3)
    return None

def classify_asset(row):
    """종목명 기반 자산 유형 분류 (커버드콜, 리츠, 채권 등)"""
    name, symbol = str(row.get('종목명', '')).upper(), str(row.get('종목코드', '')).upper()
    
    if any(k in name or k in symbol for k in ['커버드콜', 'COVERED', 'QYLD', 'JEPI', 'JEPQ', 'NVDY', 'TSLY', 'QQQI', '타겟위클리']): return '🛡️ 커버드콜'
    if any(k in name or k in symbol for k in ['채권', '국채', 'BOND', 'TLT', '하이일드', 'HI-YIELD']): return '🏦 채권형'
    if '리츠' in name or 'REITS' in name or 'INFRA' in name or '인프라' in name: return '🏢 리츠형'
    if '혼합' in name: return '⚖️ 혼합형'
    return '📈 주식형'

def get_hedge_status(name, category):
    """환헤지 여부 판별"""
    name_str = str(name).upper()
    if category == '해외': return "💲달러(직투)"
    if "환노출" in name_str or "UNHEDGED" in name_str: return "⚡환노출"
    if any(x in name_str for x in ["(H)", "헤지"]): return "🛡️환헤지(H)"
    return "⚡환노출" if any(x in name_str for x in ['미국', 'GLOBAL', 'S&P500', '나스닥', '국제']) else "-"


# =============================================================================
# [SECTION 3] 메인 데이터 로드 및 처리 (우선순위 엔진)
# =============================================================================

@st.cache_data(ttl=1800, show_spinner=False)
def load_and_process_data(df_raw, is_admin=False):
    """
    CSV 데이터를 불러와 포맷팅하고, 우선순위 로직에 따라 최종 표시 값을 결정함.
    [우선순위] 신규상장 > Auto(크롤링) > TTM(과거실적) > Manual(수동)
    """
    if df_raw.empty: return pd.DataFrame()

    # 1. 컬럼명 공백 제거
    df_raw.columns = df_raw.columns.str.strip()
    
    try:
        # 수치형 컬럼 강제 변환 (콤마 제거 포함)
        num_cols = [
            '연배당금', '연배당률', '현재가', '신규상장개월수', 
            '연배당금_크롤링', '연배당금_크롤링_auto', 'TTM_연배당률(크롤링)'
        ]
        for col in num_cols:
            if col in df_raw.columns:
                df_raw[col] = pd.to_numeric(df_raw[col].astype(str).str.replace(',', ''), errors='coerce').fillna(0)

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

    # 2. 브로커(한투 API) 초기화
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
    
    # 3. 행별 병렬 처리 함수
    def process_row(idx, row):
        try:
            code = str(row.get('종목코드', '')).strip()
            name = str(row.get('종목명', '')).strip()
            category = str(row.get('분류', '국내')).strip()
            
            # 가격 조회
            price = get_safe_price(broker, code, category)
            if not price: price = 0 

            # 데이터 추출
            auto_val = float(row.get('연배당금_크롤링_auto', 0) or 0)
            ttm_rate = float(row.get('TTM_연배당률(크롤링)', 0) or 0)
            manual_val = float(row.get('연배당금', 0) or 0)
            old_crawled = float(row.get('연배당금_크롤링', 0) or 0)
            months = int(row.get('신규상장개월수', 0))

            # [핵심] 표시 우선순위 결정 로직
            # 0순위: 신규 상장주 (초기 데이터 부족 시 수동 월할 계산)
            if 0 < months < 12 and manual_val > 0:
                target_div = (manual_val / months) * 12
                display_name = f"{name} ⭐({months}개월)"
            
            # 1순위: Auto (자동 크롤링 값, -1.0이면 잠금 처리되어 건너뜀)
            elif auto_val > 0: 
                target_div = auto_val
                display_name = name
                
            # 2순위: TTM (과거 12개월 실적 기반 역산)
            elif ttm_rate > 0 and price > 0: 
                target_div = price * (ttm_rate / 100)
                display_name = f"{name} (TTM)"
                
            # 3순위: 수동 입력값
            elif manual_val > 0: 
                target_div = manual_val
                display_name = name
                
            # 4순위: 구버전 크롤링 데이터
            else: 
                target_div = old_crawled
                display_name = name

            # 수익률 계산
            yield_val = (target_div / price * 100) if price > 0 else 0

            if is_admin and (yield_val < 2.0 or yield_val > 25.0): display_name = f"🚫 {display_name}"

            # 포맷팅
            if category == '국내':
                price_fmt = f"{int(price):,}원"
                div_fmt = f"{int(target_div):,}원"
            else:
                price_fmt = f"${price:.2f}"
                div_fmt = f"${target_div:.2f}"

            csv_type = str(row.get('유형', '-'))
            auto_asset_type = classify_asset(row) 
            
            final_type = csv_type
            if '채권' in auto_asset_type: final_type = '채권'
            elif '커버드콜' in auto_asset_type: final_type = '커버드콜'
            elif '리츠' in auto_asset_type: final_type = '리츠'

            return idx, {
                '코드': code, 
                '종목명': display_name,
                '연배당금': div_fmt,
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

    # ThreadPool로 병렬 실행
    with ThreadPoolExecutor(max_workers=10) as executor:
        futures = {executor.submit(process_row, idx, row): idx for idx, row in df_raw.iterrows()}
        for future in as_completed(futures):
            idx, result = future.result()
            results[idx] = result

    final_data = [r for r in results if r is not None]
    return pd.DataFrame(final_data).sort_values('연배당률', ascending=False) if final_data else pd.DataFrame()


# =============================================================================
# [SECTION 4] 파일 I/O (CSV & GitHub)
# =============================================================================

@st.cache_data(ttl=1800)
def load_stock_data_from_csv():
    """로컬 CSV 파일 로드 및 필수 컬럼 검증"""
    import os
    
    file_path = "stocks.csv"
    if not os.path.exists(file_path): return pd.DataFrame()

    try:
        df = pd.read_csv(file_path, encoding='utf-8-sig', dtype=str)
        df.columns = df.columns.str.strip()

        # 관리하는 핵심 컬럼 15개 정의
        valid_cols = [
            '종목코드', '종목명', '연배당금', '분류', '블로그링크', 
            '배당락일', '신규상장개월수', '배당기록', '연배당률', 
            '연배당금_크롤링', '연배당률_크롤링', '유형', '검색라벨', 
            '연배당금_크롤링_auto', 'TTM_연배당률(크롤링)'
        ]

        # 중복 제거 및 누락 컬럼 생성
        df = df.loc[:, ~df.columns.duplicated()]
        for col in valid_cols:
            if col not in df.columns:
                df[col] = "0.0"
        
        df = df[valid_cols]

        # 결측값 0.0 처리
        numeric_cols = ['연배당금_크롤링_auto', 'TTM_연배당률(크롤링)', '연배당금_크롤링', '연배당금']
        for col in numeric_cols:
            df[col] = df[col].fillna("0.0").str.replace(',', '')

        return df

    except Exception as e:
        print(f"CSV 로드 실패: {e}")
        return pd.DataFrame()


def save_to_github(df):
    """GitHub API를 통해 CSV 파일 업데이트"""
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


# =============================================================================
# [SECTION 6] 단일 종목 실시간 조회 (돋보기 버튼)
# =============================================================================

def fetch_dividend_yield_hybrid(code, category):
    """
    개별 종목 배당률 실시간 조회 (돋보기 버튼용)
    국내: 네이버 API / 해외: YFinance
    """
    code = str(code).strip()

    if category == '국내':
        # (A) 현재가 조회 (한투 -> 네이버 백업)
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

        # (B) 배당금 내역 조회 (네이버 API)
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

        # (C) 배당률 계산
        if current_price > 0 and latest_div > 0:
            try:
                yield_val = (latest_div * 12) / current_price * 100
                return round(yield_val, 2), f"✅ 실시간({int(latest_div)}원)"
            except Exception:
                pass

        # (D) 백업
        try:
            if resp and 'output' in resp:
                backup = resp['output'].get('hts_dvsd_rate')
                if backup and backup != '-':
                    return float(backup), "✅ 한투API(백업)"
        except Exception:
            pass

        return 0.0, "⚠️ 조회 실패"

    else:
        # 해외: YFinance 조회
        try:
            ticker = yf.Ticker(code)

            # 1) 현재가
            price = None
            try:
                price = ticker.fast_info.get('last_price')
            except Exception:
                price = None

            # 2) 배당 내역 (최근 1년)
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

                    if recent.empty:
                        recent = divs.tail(4)
                    annual_div_sum = float(recent.sum())
            except Exception as e_div:
                logger.warning(f"yfinance dividends read failed for {code}: {e_div}")
                annual_div_sum = 0.0

            # 3) fallback 가격
            if not price:
                try:
                    hist = ticker.history(period="5d")
                    if not hist.empty:
                        price = float(hist['Close'].iloc[-1])
                except Exception as e_hist:
                    logger.warning(f"yfinance history read failed for {code}: {e_hist}")
                    price = None

            # 4) 계산
            if price and price > 0 and annual_div_sum and annual_div_sum > 0:
                yield_pct = (annual_div_sum / price) * 100.0
                return round(yield_pct, 2), f"✅ 야후(계산: {annual_div_sum:.2f}/{price:.2f})"
            else:
                try:
                    info_dy = ticker.info.get('dividendYield')
                    if info_dy:
                        calc_val = info_dy * 100
                        return round(calc_val, 2), "✅ 야후(Info)"
                except Exception as e_info:
                    logger.warning(f"yfinance info.dividendYield failed for {code}: {e_info}")

            return 0.0, "⚠️ 데이터 없음"
        except Exception as e:
            logger.exception(f"해외 배당 조회 예외: {code} - {e}")
            return 0.0, "❌ 해외 에러"

# =============================================================================
# [SECTION 7] 스마트 업데이트 (전체 종목 갱신)
# =============================================================================

def _fetch_domestic_sensor(code):
    """국내 ETF 센서: 네이버 API 파싱"""
    from datetime import datetime, timedelta

    headers = {
        "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 15_0 like Mac OS X)",
        "Referer": f"https://m.stock.naver.com/domestic/stock/{code}/analysis"
    }

    try:
        # 현재가
        price = 0
        price_url = f"https://api.stock.naver.com/etf/{code}/basic"
        r_p = requests.get(price_url, headers=headers, timeout=5)
        if r_p.status_code == 200:
            price = float(r_p.json().get('result', {}).get('closePrice', 0))

        # 배당 내역
        hist_url = f"https://m.stock.naver.com/api/etf/{code}/dividend/history?page=1&pageSize=200&firstPageSize=200"
        res = requests.get(hist_url, headers=headers, timeout=5)

        auto_amt, ttm_rate = 0.0, 0.0

        if res.status_code == 200:
            j = res.json()
            items = []
            if isinstance(j, dict):
                items = j.get("result") or j.get("items") or j.get("data") or []
                if isinstance(items, dict): 
                    items = items.get("items") or []
            elif isinstance(j, list):
                items = j

            if items:
                # [Auto] 최신 배당금 연환산
                first = items[0]
                latest_div = 0
                for k in ("dividendAmount", "dividend", "distribution", "amount", "value", "payAmount"):
                    if k in first and first[k] is not None:
                        latest_div = float(str(first[k]).replace(',', ''))
                        break
                
                auto_amt = latest_div * 12

                # [TTM] 최근 1년 실제 지급액 합산
                cutoff = (datetime.now() - timedelta(days=365)).strftime("%Y%m%d")
                ttm_sum = 0
                for item in items:
                    d_str = str(item.get('playDate') or item.get('date', '')).replace('.', '').replace('-', '')
                    if d_str >= cutoff:
                        val = 0
                        for k in ("dividendAmount", "dividend", "distribution", "amount"):
                            if k in item and item[k] is not None:
                                val = float(str(item[k]).replace(',', ''))
                                break
                        ttm_sum += val
                    else: 
                        break

                if price > 0:
                    ttm_rate = round((ttm_sum / price) * 100, 2)

        return auto_amt, ttm_rate
    except Exception:
        return 0.0, 0.0


def _fetch_overseas_sensor(code):
    """
    해외 ETF 센서: '폭탄 배당' 왜곡 방지 로직 적용
    TTM(과거 1년 합계)과 Forward(최근월*12)를 비교하여 괴리가 크면 Forward 채택
    """
    import yfinance as yf
    import pandas as pd 
    
    try:
        ticker = yf.Ticker(code)
        
        # 1. 현재가
        try:
            price = ticker.fast_info['last_price']
        except:
            history = ticker.history(period='1d')
            if history.empty: return 0, 0
            price = history['Close'].iloc[-1]
            
        if price <= 0: return 0, 0

        # 2. 배당률 계산 (Forward vs TTM 비교)
        rate = 0.0
        val = 0.0
        
        try:
            dividends = ticker.dividends
            if not dividends.empty:
                # 최신 배당금
                last_div = float(dividends.iloc[-1])
                
                # 과거 1년 합계 (TTM)
                ttm_div = float(dividends.iloc[-12:].sum())
                
                ttm_yield = (ttm_div / price) * 100
                forward_yield = (last_div * 12 / price) * 100
                
                # QYLG 등 특별배당 이슈 대응: 차이가 5%p 이상이면 Forward 우선
                if abs(ttm_yield - forward_yield) > 5.0:
                    val = last_div * 12
                    rate = forward_yield
                else:
                    val = ttm_div
                    rate = ttm_yield
            else:
                val = ticker.info.get('dividendRate', 0)
                rate = ticker.info.get('dividendYield', 0) * 100
                
        except Exception:
            val = ticker.info.get('trailingAnnualDividendRate', 0)
            rate = ticker.info.get('trailingAnnualDividendYield', 0) * 100

        if 0 < rate < 1: rate *= 100

        return val, round(rate, 2)

    except Exception as e:
        return 0.0, 0.0

def reset_auto_data(code):
    """Auto 데이터를 -1.0으로 설정하여 스마트 갱신에서 보호(잠금)"""
    try:
        df = load_stock_data_from_csv()
        
        if code in df['종목코드'].values:
            df.loc[df['종목코드'] == code, '연배당금_크롤링_auto'] = -1.0
            
            success, msg = save_to_github(df)
            if success:
                return True, f"✅ [{code}] 보호 모드 활성화 (스마트 갱신 제외)"
            else:
                return False, f"❌ 저장 실패: {msg}"
        return False, "❌ 종목 코드를 찾을 수 없습니다."
    except Exception as e:
        return False, f"❌ 오류 발생: {e}"

def smart_update_and_save():
    """전체 종목 배당 정보 일괄 업데이트 로직"""
    import time
    import streamlit as st
    
    try:
        df = load_stock_data_from_csv()
        if df.empty: return False, "❌ CSV 파일을 찾을 수 없습니다.", []
        
        if 'TTM_연배당률(크롤링)' not in df.columns:
            df['TTM_연배당률(크롤링)'] = 0.0
        
        total_count = len(df)
        success_count = 0
        fail_count = 0
        protected_count = 0
        failed_list = []
        
        my_bar = st.progress(0, text="스마트 업데이트 중...")
        status_text = st.empty()
        
        for idx, row in df.iterrows():
            code = str(row['종목코드']).strip()
            name = row['종목명']
            category = str(row.get('분류', '국내')).strip()
            
            # 신규 상장 종목은 건너뜀
            try: months = int(row.get('신규상장개월수', 0))
            except: months = 0
            if 0 < months < 12:
                protected_count += 1
                my_bar.progress((idx + 1) / total_count)
                continue
            
            # 잠금 상태 확인 (-1.0)
            current_auto = float(row.get('연배당금_크롤링_auto', 0) or 0)
            
            status_text.markdown(f"🔄 **[{idx+1}/{total_count}] {name}** 데이터 수집 중...")
            
            try:
                # 센서 작동
                if category == '국내':
                    val, rate = _fetch_domestic_sensor(code)
                else:
                    val, rate = _fetch_overseas_sensor(code)
                
                data_updated = False
                
                # 1) Auto 값 저장 (잠금 상태가 아닐 때만)
                if current_auto == -1.0:
                    pass 
                elif val > 0:
                    df.at[idx, '연배당금_크롤링_auto'] = float(val)
                    data_updated = True
                
                # 2) TTM 값 저장 (무조건 최신화)
                if rate > 0:
                    df.at[idx, 'TTM_연배당률(크롤링)'] = float(rate)
                    data_updated = True
                
                if data_updated:
                    success_count += 1
                elif current_auto == -1.0:
                    protected_count += 1
                else:
                    fail_count += 1
                    failed_list.append(name)
                    
            except Exception:
                fail_count += 1
                failed_list.append(name)
            
            time.sleep(0.05)
            my_bar.progress((idx + 1) / total_count)
                
        my_bar.empty()
        status_text.empty()
        st.session_state['df_dirty'] = df
        
        return True, f"✨ 완료! (성공:{success_count}, 실패:{fail_count}, 🔒보호:{protected_count})", failed_list
            
    except Exception as e:
        return False, f"오류 발생: {e}", []

def update_dividend_rolling(current_history_str, new_dividend_amount):
    """최근 12개월 배당 기록 갱신 헬퍼"""
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
