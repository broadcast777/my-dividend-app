"""
프로젝트: 배당 팽이 (Dividend Top) v2.1
파일명: logic.py
설명: 금융 API 연동 및 데이터 자동 보정 (해외 티커 00붙임 현상 수정 완료)
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
from github import Github

# -----------------------------------------------------------
# [SECTION 1] 시세 조회 및 유틸리티 함수
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
            except Exception:
                pass
        
        ticker_code = f"{code_str}.KS" if category == '국내' else code_str
        ticker = yf.Ticker(ticker_code)
        price = ticker.fast_info.get('last_price')
        if not price:
            hist = ticker.history(period="1d")
            if not hist.empty:
                price = hist['Close'].iloc[-1]
        return float(price) if price else None
    except Exception:
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
    
    # 1. 커버드콜 (옵션 매도)
    if any(k in name or k in symbol for k in ['커버드콜', 'COVERED', 'QYLD', 'JEPI', 'JEPQ', 'NVDY', 'TSLY', 'QQQI', '타겟위클리']): return '🛡️ 커버드콜'
    
    # 2. 채권 (국채, 회사채, 하이일드)
    if any(k in name or k in symbol for k in ['채권', '국채', 'BOND', 'TLT', '하이일드', 'HI-YIELD']): return '🏦 채권형'
    
    # 3. 리츠 (부동산)
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
# [SECTION 2] 구글 캘린더 연동 엔진 (기존 동일)
# -----------------------------------------------------------

def calculate_google_calendar_url(ticker_name, pay_date_str):
    try:
        import datetime, calendar, re
        from urllib.parse import quote

        today = datetime.date.today()
        target_date = None

        if not isinstance(pay_date_str, str): pay_date_str = str(pay_date_str)
        clean_str = pay_date_str.replace(" ", "").strip()

        if "매월" in clean_str:
            if "마지막" in clean_str or "말일" in clean_str or "월말" in clean_str:
                last_day_current = calendar.monthrange(today.year, today.month)[1]
                candidate_date = datetime.date(today.year, today.month, last_day_current)
                if candidate_date < today:
                    next_month = today.month + 1 if today.month < 12 else 1
                    next_year = today.year if today.month < 12 else today.year + 1
                    last_day_next = calendar.monthrange(next_year, next_month)[1]
                    target_date = datetime.date(next_year, next_month, last_day_next)
                else:
                    target_date = candidate_date
            else:
                numbers = re.findall(r'\d+', clean_str)
                if numbers:
                    day = int(numbers[0])
                    try:
                        candidate_date = datetime.date(today.year, today.month, day)
                    except ValueError:
                        last_day = calendar.monthrange(today.year, today.month)[1]
                        candidate_date = datetime.date(today.year, today.month, last_day)
                    if candidate_date < today:
                        next_month = today.month + 1 if today.month < 12 else 1
                        next_year = today.year if today.month < 12 else today.year + 1
                        try:
                            target_date = datetime.date(next_year, next_month, day)
                        except ValueError:
                            last_day = calendar.monthrange(next_year, next_month)[1]
                            target_date = datetime.date(next_year, next_month, last_day)
                    else:
                        target_date = candidate_date
                elif "초" in clean_str:
                    candidate_date = datetime.date(today.year, today.month, 1)
                    if candidate_date < today:
                        next_month = today.month + 1 if today.month < 12 else 1
                        next_year = today.year if today.month < 12 else today.year + 1
                        target_date = datetime.date(next_year, next_month, 1)
                    else:
                        target_date = candidate_date
                else:
                    return None
        elif "-" in clean_str or "." in clean_str:
            clean_str = clean_str.split("(")[0].replace(".", "-")
            try:
                target_date = datetime.datetime.strptime(clean_str, "%Y-%m-%d").date()
            except:
                return None
        else:
            return None

        if target_date is None: return None

        safe_buy_date = target_date - datetime.timedelta(days=3)
        while safe_buy_date.weekday() >= 5: 
            safe_buy_date -= datetime.timedelta(days=1)

        start_str = safe_buy_date.strftime("%Y%m%d")
        end_str = (safe_buy_date + datetime.timedelta(days=1)).strftime("%Y%m%d")

        title = quote(f"💰 [{ticker_name}] 매수 준비 (D-3)")
        details = quote(f"배당 기준일(예상): {target_date}\n✅ 안전 매수 추천일: {safe_buy_date} (오늘)\n\n⚠️ 주의: 본 일정은 과거 데이터 기반의 추정일입니다.")

        google_url = (f"https://www.google.com/calendar/render?action=TEMPLATE&text={title}&dates={start_str}/{end_str}&details={details}")
        return google_url

    except Exception as e:
        return None


# -----------------------------------------------------------
# [SECTION 3] 메인 데이터 로드 및 병렬 처리 엔진
# -----------------------------------------------------------

@st.cache_data(ttl=1800, show_spinner=False)
def load_and_process_data(df_raw, is_admin=False):
    """
    [개선됨] CSV 데이터를 읽어오되, 종목명 기반으로 '유형'을 자동 보정합니다.
    (예: CSV에 '고배당주'라고 써있어도 이름에 '채권'이 있으면 '채권'으로 강제 변환)
    """
    if df_raw.empty: return pd.DataFrame()

    # 1단계: 연료 필터링 (기존 로직)
    try:
        num_cols = ['연배당금', '연배당률', '현재가', '신규상장개월수', '연배당금_크롤링']
        for col in num_cols:
            if col in df_raw.columns:
                df_raw[col] = pd.to_numeric(df_raw[col], errors='coerce').fillna(0)

        # 🚨 [수정 완료] 숫자인 경우에만 0을 채우고(한국), 문자는 그대로 둡니다(미국).
        # 기존: .str.zfill(6) -> 무조건 6자리로 만듦 (JEPI -> 00JEPI 오류 발생)
        if '종목코드' in df_raw.columns:
            def clean_ticker(x):
                s = str(x).split('.')[0].strip()
                if s.isdigit(): return s.zfill(6) # 숫자면 한국 주식 (005930)
                return s.upper() # 문자면 미국 주식 (JEPI)
            
            df_raw['종목코드'] = df_raw['종목코드'].apply(clean_ticker)

        if '배당락일' in df_raw.columns:
            df_raw['배당락일'] = df_raw['배당락일'].astype(str).replace(['nan', 'None', 'nan '], '-')

        if '자산유형' in df_raw.columns:
            df_raw['자산유형'] = df_raw['자산유형'].fillna('기타')
    except: pass

    # 2단계: 병렬 시세 조회 및 자동 분류
    try:
        broker = mojito.KoreaInvestment(
            api_key=st.secrets["kis"]["app_key"],
            api_secret=st.secrets["kis"]["app_secret"],
            acc_no=st.secrets["kis"]["acc_no"],
            mock=True 
        )
    except:
        return pd.DataFrame()

    results = [None] * len(df_raw)
    
    def process_row(idx, row):
        try:
            code = str(row.get('종목코드', '')).strip()
            name = str(row.get('종목명', '')).strip()
            category = str(row.get('분류', '국내')).strip()
            
            # [시세 조회]
            price = get_safe_price(broker, code, category)
            if not price: price = 0 

            # [배당금 결정]
            crawled_div = float(row.get('연배당금_크롤링', 0))
            manual_div = float(row.get('연배당금', 0))        
            months = int(row.get('신규상장개월수', 0))

            if 0 < months < 12:
                target_div = (manual_div / months * 12) if manual_div > 0 else crawled_div
                display_name = f"{name} ⭐"
            else:
                target_div = crawled_div if crawled_div > 0 else manual_div
                display_name = name

            if price > 0:
                yield_val = (target_div / price) * 100
            else:
                yield_val = 0

            # 🚨 [필터링 해제 상태]
            if is_admin and (yield_val < 2.0 or yield_val > 25.0): display_name = f"🚫 {display_name}"

            price_fmt = f"{int(price):,}원" if category == '국내' else f"${price:.2f}"
            
            # 🚨 [핵심 업데이트] 자동 분류 보정 (Auto-Correction)
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
                '캘린더링크': calculate_google_calendar_url(display_name, str(row.get('배당락일', '-'))),
                'pure_name': name.replace("🚫 ", "").replace(" (필터대상)", ""), 
                '신규상장개월수': months,
                '배당기록': str(row.get('배당기록', '')),
                '검색라벨': str(row.get('검색라벨', f"[{code}] {display_name}"))
            }
        except:
            return idx, None

    with ThreadPoolExecutor(max_workers=5) as executor:
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
    except Exception:
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
        return False, f"❌ 저장 실패: {str(e)}"


# -----------------------------------------------------------
# [SECTION 5~6] (기존 배당금/하이브리드 크롤링 함수들 유지)
# -----------------------------------------------------------
# (기존 fetch_dividend_yield_hybrid 등 함수는 그대로 두시면 됩니다.)
# 편의를 위해 하단 생략 없이 전체 코드가 필요하다면 말씀해 주세요! 
# 위 코드까지만 덮어써도 핵심 기능은 작동합니다.
# -----------------------------------------------------------
# [SECTION 5] 배당금 및 포트폴리오 유틸리티
# -----------------------------------------------------------

def update_dividend_rolling(current_history_str, new_dividend_amount):
    """최근 12개월 배당 기록을 갱신하고 연간 합계를 산출합니다. (Rolling Window)"""
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

def generate_portfolio_ics(selected_stocks_data):
    """선택된 포트폴리오 종목들의 배당락 일정을 통합 ICS 파일 형식으로 생성합니다."""
    cal_content = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//DividendPange//Portfolio//KO",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH"
    ]
    
    today = datetime.date.today()
    
    for item in selected_stocks_data:
        name = item.get('종목', '종목명')
        pay_date_str = item.get('배당락일', '-')
        clean_str = str(pay_date_str).replace(" ", "").strip()
        
        # 내부 헬퍼: 타겟 날짜 도출
        def get_target_date_inner(y, m, txt):
            if "마지막" in txt or "말일" in txt or "월말" in txt:
                return datetime.date(y, m, calendar.monthrange(y, m)[1])
            elif "초" in txt and "매월" in txt:
                return datetime.date(y, m, 1)
            else:
                nums = re.findall(r'\d+', txt)
                if nums:
                    d = int(nums[0])
                    last_d = calendar.monthrange(y, m)[1]
                    return datetime.date(y, m, min(d, last_d))
            return None

        # 내부 헬퍼: 안전 매수일 도출
        def get_safe_buy_date_inner(base_d):
            s_d = base_d - datetime.timedelta(days=3)
            while s_d.weekday() >= 5: s_d -= datetime.timedelta(days=1)
            return s_d

        target_date = get_target_date_inner(today.year, today.month, clean_str)
        
        if not target_date:
            try:
                dt_part = clean_str.split("(")[0].replace(".", "-")
                target_date = datetime.datetime.strptime(dt_part, "%Y-%m-%d").date()
            except: continue

        safe_buy_date = get_safe_buy_date_inner(target_date)

        # 이미 지난 일정은 다음 달로 자동 이월
        is_recurring = any(x in clean_str for x in ["매월", "월말", "월초"])
        if is_recurring and safe_buy_date < today:
            next_m = today.month + 1 if today.month < 12 else 1
            next_y = today.year if today.month < 12 else today.year + 1
            target_date = get_target_date_inner(next_y, next_m, clean_str)
            safe_buy_date = get_safe_buy_date_inner(target_date)
        elif not is_recurring and safe_buy_date < today:
            continue

        # ICS 이벤트 블록 생성
        dt_start = safe_buy_date.strftime("%Y%m%d")
        dt_end = (safe_buy_date + datetime.timedelta(days=1)).strftime("%Y%m%d")
        
        event = [
            "BEGIN:VEVENT",
            f"DTSTART;VALUE=DATE:{dt_start}",
            f"DTEND;VALUE=DATE:{dt_end}",
            f"SUMMARY:💰 [{name}] 매수 준비 (D-3)",
            f"DESCRIPTION:배당 기준일(예상): {target_date}\\n"
              f"✅ 안전하게 오늘 매수하세요! (D-3일전)\\n\\n"
              f"⚠️ 필독: 본 알림은 과거 기록 기반의 추정일입니다.\\n"
              f"실제 지급일은 운용사 사정에 따라 변동될 수 있으니, "
              f"매수 전 반드시 증권사/공시를 통해 확정 일자를 확인하시기 바랍니다.",
            "STATUS:CONFIRMED",
            "sequence:0",
            "END:VEVENT"
        ]
        cal_content.extend(event)

    cal_content.append("END:VCALENDAR")
    return "\n".join(cal_content)


# -----------------------------------------------------------
# [SECTION 6] 실시간 배당 정보 크롤링 (Hybrid)
# -----------------------------------------------------------

def fetch_dividend_yield_hybrid(code, category):
    """
    한투 API, 야후 파이낸스, 네이버 금융을 교차 활용하여 실시간 배당수익률을 조회합니다.
    """
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

def fetch_dividend_amount_hybrid(code, category):
    """
    네이버 모바일 API 및 야후 파이낸스를 활용하여 실시간 연간 배당금(분배금) 총액을 조회합니다.
    ETF의 경우 분배금(distribution) API를 우선 활용합니다.
    """
    import requests
    import yfinance as yf
    import pandas as pd
    
    code = str(code).strip()
    
    if category == '국내':
        try:
            code = code.zfill(6)
            headers = {
                'User-Agent': 'Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36',
                'Referer': 'https://m.stock.naver.com/'
            }
            
            # [시도 A] 일반 주식 배당금 조회
            url_stock = f"https://api.stock.naver.com/stock/{code}/dividend"
            res = requests.get(url_stock, headers=headers, timeout=3)
            if res.status_code == 200:
                data = res.json()
                items = data.get('dividendHistory', []) or data.get('items', [])
                if items:
                    latest = items[0]
                    val = latest.get('dividendPerShare') or latest.get('dividend') or 0
                    val = float(str(val).replace(',', ''))
                    if val > 0:
                        return val * 12, "✅ 네이버(주식)"

            # [시도 B] ETF 분배금 조회
            url_etf = f"https://api.stock.naver.com/etf/{code}/distribution"
            res = requests.get(url_etf, headers=headers, timeout=3)
            if res.status_code == 200:
                data = res.json()
                dist_list = data.get('result', {}).get('distributionInfoList', [])
                if dist_list:
                    latest_dist = dist_list[0].get('amount', 0)
                    latest_dist = float(str(latest_dist).replace(',', ''))
                    if latest_dist > 0:
                        return latest_dist * 12, "✅ 네이버(ETF)"
        except Exception:
            pass
            
    # [해외 및 국내 백업 조회] 야후 파이낸스 활용
    try:
        ticker_symbol = f"{code}.KS" if category == '국내' else code
        stock = yf.Ticker(ticker_symbol)
        
        # 1순위: API 제공 Rate
        rate = stock.info.get('dividendRate')
        if rate and rate > 0:
            return float(rate), "✅ 야후(Rate)"
            
        # 2순위: 최근 1년치 실제 배당금 합산
        hist = stock.dividends
        if not hist.empty:
            if hist.index.tz is not None:
                hist.index = hist.index.tz_localize(None)
            one_year_ago = pd.Timestamp.now() - pd.Timedelta(days=365)
            recent_hist = hist[hist.index >= one_year_ago]
            total = recent_hist.sum()
            if total > 0:
                return float(total), "✅ 야후(합계)"
    except:
        pass

    return 0.0, "⚠️ 데이터없음"
