import streamlit as st
import pandas as pd
import requests
from bs4 import BeautifulSoup
import yfinance as yf
from concurrent.futures import ThreadPoolExecutor, as_completed
import time
import mojito 

def _fetch_price_raw(broker, code, category):
    try:
        code_str = str(code).strip()
        
        # --- [1단계] 국내 종목: 한투 API 우선 시도 ---
        if category == '국내':
            try:
                resp = broker.fetch_price(code_str)
                if resp and isinstance(resp, dict) and 'output' in resp:
                    if resp['output'] and resp['output'].get('stck_prpr'):
                        return int(resp['output']['stck_prpr'])
            except Exception:
                pass

        # --- [2단계] 백업 로직: yfinance 사용 ---
        if category == '국내':
            ticker_code = f"{code_str}.KS"
        else:
            ticker_code = code_str
            
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
    max_retries = 2
    for attempt in range(max_retries):
        price = _fetch_price_raw(broker, code, category)
        if price is not None:
            return price
        if attempt < max_retries - 1:
            time.sleep(0.5)
    return None

def classify_asset(row):
    name = str(row.get('종목명', '')).upper()
    symbol = str(row.get('종목코드', '')).upper()
    covered = ['커버드콜', 'COVERED CALL', '프리미엄', 'PREMIUM', '+10%', '옵션', 'OPTION', 'QYLD', 'JEPI', 'JEPQ', 'XYLD', 'RYLD', 'NVDY', 'TSLY', 'CONY', 'MSTY', 'ULTRA', 'QQQI', 'GPIQ', 'XYLG', 'QYLG', 'TLTW', 'SVOL']
    bond = ['채권', '국채', 'BOND', '단기채', 'TREASURY', '하이일드', 'HIGH YIELD', 'PFF', '국제금', '골드', 'GOLD', 'BIL', 'SHV', 'SGOV', 'T-BILL', 'TLT']
    
    if any(k in name for k in covered) or any(k in symbol for k in covered): 
        return '🛡️ 커버드콜'
    if '혼합' in name:
        return '⚖️ 혼합형'
    if any(k in name for k in bond) or any(k in symbol for k in bond): 
        return '🏦 채권형'
    if any(k in name for k in ['리츠', 'REITS', '부동산']): 
        return '🏢 리츠형'
    return '📈 주식형'

def get_hedge_status(name, category):
    name_str = str(name).upper()
    if category == '해외': return "💲달러(직투)"
    if "환노출" in name_str or "UNHEDGED" in name_str: return "⚡환노출"
    if any(x in name_str for x in ["(H)", "헤지", "합성"]): return "🛡️환헤지(H)"
    if any(x in name_str for x in ['미국', 'GLOBAL', 'S&P500', '나스닥', '빅테크', '국제금', '골드', 'GOLD']): return "⚡환노출"
    return "-"

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
    except Exception as e:
        st.error(f"API 인증 실패: {e}")
        return pd.DataFrame()

    results = [None] * len(df_raw)
    
    def process_row(idx, row):
        try:
            code = str(row.get('종목코드', '')).strip()
            name = str(row.get('종목명', '')).strip()
            category = str(row.get('분류', '국내')).strip()
            
            price = get_safe_price(broker, code, category)
            
            if not price: return idx, None
            
            raw_div = float(row.get('연배당금', 0))
            months = int(row.get('신규상장개월수', 0))
            
            # [수정 완료] 이제 CSV에 적힌 '연배당금'을 무조건 1년치로 믿고 그대로 씁니다.
            annual_div = raw_div 
            
            yield_val = (annual_div / price) * 100
            
            if not is_admin and (yield_val < 2.0 or yield_val > 25.0): return idx, None
            if is_admin and (yield_val < 2.0 or yield_val > 25.0): name = f"🚫 {name} (필터대상)"

            price_display = f"{int(price):,}원" if category == '국내' else f"${price:.2f}"
            
            return idx, {
                '코드': code, 
                '종목명': f"{name} ⭐" if months > 0 else name,
                '블로그링크': str(row.get('블로그링크', '#')),
                '금융링크': f"https://finance.naver.com/item/main.naver?code={code}" if category == '국내' else f"https://finance.yahoo.com/quote/{code}",
                '현재가': price_display, 
                '연배당률': yield_val,
                '환구분': get_hedge_status(name, category),
                '배당락일': str(row.get('배당락일', '-')), 
                '분류': category,
                '자산유형': classify_asset(row), 
                'pure_name': name.replace("🚫 ", "").replace(" (필터대상)", ""),
                '신규상장개월수': months
            }
        except Exception:
            return idx, None

    with ThreadPoolExecutor(max_workers=5) as executor:
        futures = {executor.submit(process_row, idx, row): idx for idx, row in df_raw.iterrows()}
        for future in as_completed(futures):
            idx, result = future.result()
            results[idx] = result

    final_data = [r for r in results if r is not None]
    if not final_data: return pd.DataFrame()
    return pd.DataFrame(final_data).sort_values('연배당률', ascending=False)

@st.cache_data(ttl=600)
def load_stock_data_from_csv():
    url = "https://raw.githubusercontent.com/broadcast777/my-dividend-app/main/stocks.csv"
    encodings = ['utf-8-sig', 'cp949', 'euc-kr']
    for enc in encodings:
        try:
            df = pd.read_csv(url, dtype={'종목코드': str}, encoding=enc)
            return df
        except Exception:
            continue
    return pd.DataFrame()
