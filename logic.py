import streamlit as st
import pandas as pd
import yfinance as yf
from concurrent.futures import ThreadPoolExecutor, as_completed
import time
import mojito 

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
