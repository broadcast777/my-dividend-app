import streamlit as st
import pandas as pd
import yfinance as yf
from concurrent.futures import ThreadPoolExecutor, as_completed
import time
import mojito 
import datetime  # <--- 추가
import calendar  # <--- 추가
from urllib.parse import quote # <--- 추가
import re
import requests
# --- [1] 시세 조회 및 유틸 함수 ---
def _fetch_price_raw(broker, code, category):
    try:
        code_str = str(code).strip()
        # 1. 국내 종목 (한투 API)
        if category == '국내':
            try:
                resp = broker.fetch_price(code_str)
                if resp and isinstance(resp, dict) and 'output' in resp:
                    if resp['output'] and resp['output'].get('stck_prpr'):
                        return int(resp['output']['stck_prpr'])
            except Exception:
                pass
        
        # 2. 해외/국내 백업 (yfinance)
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
    name, symbol = str(row.get('종목명', '')).upper(), str(row.get('종목코드', '')).upper()
    if any(k in name or k in symbol for k in ['커버드콜', 'COVERED', 'QYLD', 'JEPI', 'JEPQ', 'NVDY', 'TSLY', 'QQQI']): return '🛡️ 커버드콜'
    if '혼합' in name: return '⚖️ 혼합형'
    if any(k in name or k in symbol for k in ['채권', '국채', 'BOND', 'TLT', '하이일드']): return '🏦 채권형'
    if '리츠' in name or 'REITS' in name: return '🏢 리츠형'
    return '📈 주식형'

def get_hedge_status(name, category):
    name_str = str(name).upper()
    if category == '해외': return "💲달러(직투)"
    if "환노출" in name_str or "UNHEDGED" in name_str: return "⚡환노출"
    if any(x in name_str for x in ["(H)", "헤지", "합성"]): return "🛡️환헤지(H)"
    return "⚡환노출" if any(x in name_str for x in ['미국', 'GLOBAL', 'S&P500', '나스닥']) else "-"


def calculate_google_calendar_url(ticker_name, pay_date_str):
    """
    [최종 완벽 버전] 
    1. "매월 15일" -> 15일 인식
    2. "매월 마지막 영업일" / "말일" -> 자동으로 그 달의 마지막 날짜(28~31) 계산
    3. 주말/공휴일 피해서 D-2 계산
    """
    try:
        today = datetime.date.today()
        target_date = None
        
        if not isinstance(pay_date_str, str):
            pay_date_str = str(pay_date_str)
        clean_str = pay_date_str.replace(" ", "").strip()

        # =========================================================
        # [수정] "마지막" / "말일" 처리 로직 추가
        # =========================================================
        
        if "매월" in clean_str:
            # Case 1: "마지막" 또는 "말일"이라는 글자가 있는 경우
            if "마지막" in clean_str or "말일" in clean_str:
                # 1. 이번 달의 마지막 날짜 구하기
                last_day_current = calendar.monthrange(today.year, today.month)[1]
                candidate_date = datetime.date(today.year, today.month, last_day_current)
                
                # 2. 이미 지났으면 다음 달의 마지막 날짜로 설정
                if candidate_date < today:
                    next_month = today.month + 1 if today.month < 12 else 1
                    next_year = today.year if today.month < 12 else today.year + 1
                    last_day_next = calendar.monthrange(next_year, next_month)[1]
                    target_date = datetime.date(next_year, next_month, last_day_next)
                else:
                    target_date = candidate_date

            # Case 2: 숫자가 있는 경우 ("15일", "초" 등)
            else:
                numbers = re.findall(r'\d+', clean_str)
                if numbers:
                    day = int(numbers[0]) # 첫 번째 숫자 채택
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
                else:
                    # "매월"은 있는데 숫자도 없고 말일도 아니면 (예: "매월 초")
                    # 보통 '초'는 1일로 간주
                    if "초" in clean_str:
                        # (위와 동일한 로직으로 1일 처리)
                        day = 1
                        # ... (1일 기준 로직 중복 생략, 위 로직 탄다고 가정)
                        # 코드가 길어지니 간단히 처리:
                        candidate_date = datetime.date(today.year, today.month, 1)
                        if candidate_date < today:
                            next_month = today.month + 1 if today.month < 12 else 1
                            next_year = today.year if today.month < 12 else today.year + 1
                            target_date = datetime.date(next_year, next_month, 1)
                        else:
                            target_date = candidate_date
                    else:
                        return None

        # Case 3: 하이픈/점 날짜 ("2025-01-15")
        elif "-" in clean_str or "." in clean_str:
            clean_str = clean_str.split("(")[0] # 괄호 제거
            clean_str = clean_str.replace(".", "-") # 점을 하이픈으로 통일
            try:
                target_date = datetime.datetime.strptime(clean_str, "%Y-%m-%d").date()
            except:
                return None
        
        else:
            return None 

        if target_date is None: return None

    # ▼▼▼ [여기서부터 덮어쓰기 시작] ▼▼▼
        
        # 2. D-3 (3일 전) 안전 매수일 계산 (수정됨: days=2 -> days=3)
        safe_buy_date = target_date - datetime.timedelta(days=3)
        
        # 주말 보정 (토/일이면 금요일로)
        while safe_buy_date.weekday() >= 5:
            safe_buy_date -= datetime.timedelta(days=1)

        start_str = safe_buy_date.strftime("%Y%m%d")
        end_str = (safe_buy_date + datetime.timedelta(days=1)).strftime("%Y%m%d")
        
        # 3. 문구 수정 (매수 마감 -> 매수 준비 / 경고 문구 추가)
        title = quote(f"💰 [{ticker_name}] 매수 준비 (D-3)")
        
        details = quote(
            f"배당 기준일(예상): {target_date}\n"
            f"✅ 안전 매수 추천일: {safe_buy_date} (오늘)\n\n"
            f"⚠️ 주의: 본 일정은 과거 데이터 기반의 추정일입니다.\n"
            f"실제 배당락일은 운용사 사정이나 휴장에 따라 변동될 수 있으니, "
            f"매수 전 반드시 증권사 앱에서 확정 일자를 재확인해주세요!"
        )
        
        google_url = (
            f"https://www.google.com/calendar/render?action=TEMPLATE"
            f"&text={title}"
            f"&dates={start_str}/{end_str}"
            f"&details={details}"
        )
        return google_url
        # ▲▲▲ [여기까지 덮어쓰기 끝] ▲▲▲

    except Exception as e:
        print(f"Calendar Error: {e}") 
        return None

# --- [2] 메인 데이터 로직 (스마트 계산 복구) ---
@st.cache_data(ttl=600, show_spinner=False)
def load_and_process_data(df_raw, is_admin=False):
    if df_raw.empty: return pd.DataFrame()
    
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
            
            price = get_safe_price(broker, code, category)
            if not price: return idx, None

            # [핵심 수정] 신규 상장주면 알아서 1년치로 환산해주는 로직
            raw_div = float(row.get('연배당금', 0))
            months = int(row.get('신규상장개월수', 0))
            
            # months가 0보다 크면(신규면) "지금까지 받은 돈 / 개월수 * 12" 로 연환산
            if months > 0:
                annual_div = (raw_div / months) * 12
                display_name = f"{name} ⭐" # 별표 표시
            else:
                annual_div = raw_div
                display_name = name

            yield_val = (annual_div / price) * 100
            
            # 필터링
            if not is_admin and (yield_val < 2.0 or yield_val > 25.0): return idx, None
            if is_admin and (yield_val < 2.0 or yield_val > 25.0): display_name = f"🚫 {display_name}"

            price_fmt = f"{int(price):,}원" if category == '국내' else f"${price:.2f}"
            
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
                '자산유형': classify_asset(row),
                '캘린더링크': calculate_google_calendar_url(display_name, str(row.get('배당락일', '-'))),
                'pure_name': name.replace("🚫 ", "").replace(" (필터대상)", ""), # 순수 이름 저장
                '신규상장개월수': months
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

# --- [3] 데이터 로드 ---
@st.cache_data(ttl=600)
def load_stock_data_from_csv():
    url = "https://raw.githubusercontent.com/broadcast777/my-dividend-app/main/stocks.csv"
    try:
        return pd.read_csv(url, dtype={'종목코드': str})
    except:
        return pd.DataFrame()

# --- [4] 배당금 갱신 로직 (스마트 Rolling) ---
def update_dividend_rolling(current_history_str, new_dividend_amount):
    if pd.isna(current_history_str) or str(current_history_str).strip() == "":
        history = []
    else:
        history = [int(float(x)) for x in str(current_history_str).split('|')]

    # 12개가 꽉 찼을 때만 맨 앞을 삭제 (신규 상장주는 그냥 쌓임)
    if len(history) >= 12:
        history.pop(0)
        
    history.append(int(new_dividend_amount))
    
    new_annual_total = sum(history)
    new_history_str = "|".join(map(str, history))
    
    return new_annual_total, new_history_str

# [logic.py 맨 아래에 추가]

def generate_portfolio_ics(selected_stocks_data):
    """
    선택된 종목들의 일정 데이터를 받아서 
    하나의 통합 ICS(캘린더 파일) 텍스트를 생성함
    """
    cal_content = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//DividendPange//Portfolio//KO",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH"
    ]
    
    today = datetime.date.today()
    
    for item in selected_stocks_data:
        # 1. 데이터 가져오기
        name = item.get('종목', '종목명')
        pay_date_str = item.get('배당락일', '-')
        
        # 2. 날짜 계산 (아까 그 로직 재사용)
        # (코드를 재사용하기 위해 logic.py 안의 함수를 호출하거나 로직을 가져옴)
        # 여기서 간단히 처리하기 위해 calculate_google_calendar_url 내부 로직을 
        # 살짝 변형해서 날짜만 추출하는 게 정석이지만, 
        # 편의상 '배당락일' 텍스트를 파싱하는 핵심 로직만 가져옵니다.
        
        target_date = None
        clean_str = str(pay_date_str).replace(" ", "").strip()
        
        # 날짜 파싱 (숫자 추출)
        numbers = re.findall(r'\d+', clean_str)
        if "마지막" in clean_str or "말일" in clean_str:
             last_day = calendar.monthrange(today.year, today.month)[1]
             target_date = datetime.date(today.year, today.month, last_day)
        elif numbers:
             day = int(numbers[0])
             try:
                 target_date = datetime.date(today.year, today.month, day)
             except:
                 target_date = datetime.date(today.year, today.month, 1) # 에러나면 1일로
        elif "-" in clean_str or "." in clean_str:
             try:
                clean_str = clean_str.split("(")[0].replace(".", "-")
                target_date = datetime.datetime.strptime(clean_str, "%Y-%m-%d").date()
             except: pass
             # ▼▼▼ [여기서부터 덮어쓰기 시작] ▼▼▼
        # 날짜가 유효하면 D-3 계산 (수정됨)
        if target_date:
            # 과거면 내년/다음달 처리 (간소화 로직)
            if target_date < today:
                 if today.month == 12:
                     target_date = datetime.date(today.year + 1, 1, target_date.day)
                 else:
                     try:
                        target_date = datetime.date(today.year, today.month + 1, target_date.day)
                     except:
                        target_date = datetime.date(today.year, today.month + 1, 28)

            # D-3 계산 (days=3)
            safe_buy_date = target_date - datetime.timedelta(days=3)
            while safe_buy_date.weekday() >= 5:
                safe_buy_date -= datetime.timedelta(days=1)
            
            # ICS 포맷 생성
            dt_start = safe_buy_date.strftime("%Y%m%d")
            dt_end = (safe_buy_date + datetime.timedelta(days=1)).strftime("%Y%m%d")
            
            event = [
                "BEGIN:VEVENT",
                f"DTSTART;VALUE=DATE:{dt_start}",
                f"DTEND;VALUE=DATE:{dt_end}",
                f"SUMMARY:💰 [{name}] 매수 준비 (D-3)",  # 제목 변경됨
                f"DESCRIPTION:배당 기준일(예상): {target_date}\\n"  # 내용 변경됨
                  f"✅ 안전하게 오늘 매수하세요! (D-3일전)\\n\\n"
                  f"⚠️ 필독: 본 알림은 과거 기록 기반의 추정일입니다.\\n"
                  f"실제 지급일은 운용사 사정에 따라 변동될 수 있으니, "
                  f"매수 전 반드시 증권사/공시를 통해 확정 일자를 확인하시기 바랍니다.",
                "STATUS:CONFIRMED",
                "sequence:0",
                "END:VEVENT"
            ]
            cal_content.extend(event)
        # ▲▲▲ [여기까지 덮어쓰기 끝] ▲▲▲

    cal_content.append("END:VCALENDAR")
    return "\n".join(cal_content)

# [logic.py]

# [logic.py]

# [logic.py]

# [logic.py]

def fetch_dividend_yield_hybrid(code, category):
    """
    1단계: 한투 API (국내 전용)
    2단계: 야후 파이낸스 (국내 백업 + 해외 메인)
    3단계: 네이버 금융 (국내 최후 수단)
    * 해외 주식(ETF) 로직 대폭 강화 (현재가 조회 실패 방어)
    """
    code = str(code).strip()
    
    # ===============================================
    # [영역 1] 🇰🇷 국내 주식 (한투 -> 야후 -> 네이버)
    # ===============================================
    if category == '국내':
        # 1. 한투 API
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

        # 2. 야후 파이낸스 (국내 백업)
        try:
            ticker_code = f"{code}.KS"
            stock = yf.Ticker(ticker_code)
            
            # Info 확인
            dy = stock.info.get('dividendYield')
            if dy and dy > 0: return round(dy * 100, 2), "✅ 야후(Info)"
            
            # 직접 계산
            divs = stock.dividends
            if not divs.empty:
                if divs.index.tz is not None: divs.index = divs.index.tz_localize(None)
                one_year_ago = pd.Timestamp.now() - pd.Timedelta(days=365)
                recent_total = divs[divs.index >= one_year_ago].sum()
                
                # 현재가 (국내)
                price = stock.fast_info.get('last_price')
                if not price: 
                    hist = stock.history(period='1d')
                    if not hist.empty: price = hist['Close'].iloc[-1]
                
                if price and price > 0:
                    yield_cal = (recent_total / price) * 100
                    if yield_cal > 0: return round(yield_cal, 2), "✅ 야후(Rolling)"
        except: pass

        # 3. 네이버 금융 (최후의 보루)
        try:
            url = f"https://finance.naver.com/item/main.naver?code={code}"
            headers = {'User-Agent': 'Mozilla/5.0'}
            response = requests.get(url, headers=headers)
            response.encoding = 'euc-kr' 
            
            # ETF용 Table 파싱
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
                                
            # ID 파싱
            if '_dvr' in response.text:
                part = response.text.split('<em id="_dvr">')[1]
                val = part.split('</em>')[0]
                return float(val), "✅ 네이버(ID)"
        except Exception as e:
            return 0.0, f"❌ 네이버 에러: {str(e)}"

        return 0.0, "⚠️ 데이터 없음 (국내)"
        # ===============================================
    # [영역 2] 🇺🇸 해외 주식 (순서 변경: 직접 계산 우선!)
    # ===============================================
    else:
        try:
            stock = yf.Ticker(code)
            
            # -----------------------------------------------------------
            # [1순위] 배당금 내역으로 직접 계산 (가장 정확함)
            # -----------------------------------------------------------
            try:
                divs = stock.dividends
                
                if not divs.empty:
                    # Timezone 제거
                    if divs.index.tz is not None:
                        divs.index = divs.index.tz_localize(None)
                    
                    # 최근 1년 합계 계산
                    one_year_ago = pd.Timestamp.now() - pd.Timedelta(days=365)
                    recent_divs = divs[divs.index >= one_year_ago]
                    recent_total = recent_divs.sum()
                    
                    # 현재가 조회 (2중 안전장치)
                    price = stock.fast_info.get('last_price')
                    if not price or price <= 0:
                        hist = stock.history(period="1d")
                        if not hist.empty:
                            price = hist['Close'].iloc[-1]
                    
                    # 최종 계산
                    if price and price > 0 and recent_total > 0:
                        yield_cal = (recent_total / price) * 100
                        # 400% 같은 이상치 필터링 (보통 배당이 100% 넘을 순 없음)
                        if 0 < yield_cal < 100: 
                            return round(yield_cal, 2), f"✅ 야후(계산:${recent_total:.2f})"
            except:
                pass # 계산 실패하면 아래 Info로 넘어감

            # -----------------------------------------------------------
            # [2순위] Info에서 가져오기 (계산 실패 시 백업용)
            # -----------------------------------------------------------
            dy = stock.info.get('dividendYield')
            if dy and dy > 0: 
                # 야후는 0.041 (=4.1%) 형태로 줌
                return round(dy * 100, 2), "✅ 야후(Info)"
                
            return 0.0, "⚠️ 데이터 없음"
            
        except Exception as e:
            return 0.0, f"❌ 해외 에러: {str(e)}"
