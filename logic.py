import streamlit as st
import pandas as pd
import yfinance as yf
from concurrent.futures import ThreadPoolExecutor, as_completed
import time
import mojito 
import datetime  # <--- 추가
import calendar  # <--- 추가
from urllib.parse import quote # <--- 추가

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
    입력: "매월 15일" 또는 "2025-12-30" (문자열)
    출력: 구글 캘린더 등록 링크 (URL 문자열)
    """
    try:
        today = datetime.date.today()
        target_date = None
        
        # 1. 데이터 클렌징 (공백 제거, 문자열 변환)
        if not isinstance(pay_date_str, str):
            pay_date_str = str(pay_date_str)
        clean_str = pay_date_str.replace(" ", "").strip()

        # 2. 날짜 파싱 로직 ("매월 15일" 처리)
        if "매월" in clean_str and "일" in clean_str:
            # "매월15일" -> 숫자 15 추출
            day_part = clean_str.replace("매월", "").replace("일", "")
            if not day_part.isdigit(): return None # 숫자가 아니면 패스
            
            day = int(day_part)
            
            # 이번 달 배당일 계산
            try:
                candidate_date = datetime.date(today.year, today.month, day)
            except ValueError:
                # 2월 30일 같은 경우 예외 처리 -> 그 달의 마지막 날로 설정
                last_day = calendar.monthrange(today.year, today.month)[1]
                candidate_date = datetime.date(today.year, today.month, last_day)

            # 이미 지났으면 다음 달로 설정
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
                
        # 3. 날짜 파싱 로직 ("2025-01-15" 처리)
        elif "-" in clean_str:
            target_date = datetime.datetime.strptime(clean_str, "%Y-%m-%d").date()
        
        else:
            return None # 알 수 없는 형식이면 링크 생성 안 함

        if target_date is None:
            return None

        # 4. 안전 매수일 (D-2) 계산
        safe_buy_date = target_date - datetime.timedelta(days=2)

        # 5. 주말 보정 (토요일이면 금요일로, 일요일이면 금요일로)
        # weekday(): 0=월, 5=토, 6=일
        while safe_buy_date.weekday() >= 5:
            safe_buy_date -= datetime.timedelta(days=1)

        # 6. 구글 캘린더 URL 생성
        # 날짜 포맷: YYYYMMDD
        start_str = safe_buy_date.strftime("%Y%m%d")
        end_str = (safe_buy_date + datetime.timedelta(days=1)).strftime("%Y%m%d")
        
        title = quote(f"[{ticker_name}] 매수 마감일 (D-2)")
        details = quote(f"배당 기준일: {target_date} \n안전하게 오늘까지 매수하세요!")
        
        google_url = (
            f"https://www.google.com/calendar/render?action=TEMPLATE"
            f"&text={title}"
            f"&dates={start_str}/{end_str}"
            f"&details={details}"
        )
        
        return google_url

    except Exception as e:
        # 에러 나면 멈추지 말고 그냥 None 반환 (버튼 안 보이게 처리)
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
