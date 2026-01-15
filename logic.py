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

# ==========================================
# [1] 시세 조회 및 유틸리티 (Global Scope)
# ==========================================

def _fetch_price_raw(broker, code, category):
    try:
        code_str = str(code).strip().zfill(6) if category == '국내' else str(code).strip()
        if category == '국내':
            try:
                resp = broker.fetch_price(code_str)
                if resp and isinstance(resp, dict) and 'output' in resp:
                    if resp['output'] and resp['output'].get('stck_prpr'):
                        return int(resp['output']['stck_prpr'])
            except: pass
        
        ticker_code = f"{code_str}.KS" if category == '국내' else code_str
        ticker = yf.Ticker(ticker_code)
        price = ticker.fast_info.get('last_price')
        if not price:
            hist = ticker.history(period="1d")
            if not hist.empty: price = hist['Close'].iloc[-1]
        return float(price) if price else None
    except: return None

def get_safe_price(broker, code, category):
    """시세를 2번 시도해서 안전하게 가져오는 함수"""
    for _ in range(2):
        price = _fetch_price_raw(broker, code, category)
        if price is not None: return price
        time.sleep(0.5)
    return None

def classify_asset(row):
    name, symbol = str(row.get('종목명', '')).upper(), str(row.get('종목코드', '')).upper()
    if any(k in name or k in symbol for k in ['커버드콜', 'COVERED', 'QYLD', 'JEPI', 'JEPQ', 'NVDY', 'TSLY', 'QQQI']): return '🛡️ 커버드콜'
    if '혼합' in name: return '⚖️ 혼합형'
    if any(k in name or k in symbol for k in ['채권', '국채', 'BOND', 'TLT', '하이일드','SPHY', 'BIL', 'SHV', 'T-Bill']): return '🏦 채권형'
    if '리츠' in name or 'REITS' in name: return '🏢 리츠형'
    return '📈 주식형'

def get_hedge_status(name, category):
    name_str = str(name).upper()
    if category == '해외': return "💲달러(직투)"
    if "환노출" in name_str or "UNHEDGED" in name_str: return "⚡환노출"
    if any(x in name_str for x in ["(H)", "헤지", "합성"]): return "🛡️환헤지(H)"
    return "⚡환노출" if any(x in name_str for x in ['미국', 'GLOBAL', 'S&P500', '나스닥']) else "-"

# ==========================================
# [2] 배당률 정밀 조회 엔진 (야후 우선 + 직접 계산)
# ==========================================

def fetch_dividend_yield_hybrid(code, category):
    """
    1순위 야후, 2순위 네이버 백업.
    배당률(%)이 없으면 배당금(원)을 가져와서 직접 계산하는 방식.
    """
    code_str = str(code).strip().zfill(6) if category == '국내' else str(code).strip()
    
    # [A] 현재 시세 확보 (연산의 분모)
    try:
        broker = mojito.KoreaInvestment(api_key=st.secrets["kis"]["app_key"], api_secret=st.secrets["kis"]["app_secret"], acc_no=st.secrets["kis"]["acc_no"], mock=True)
        curr_price = get_safe_price(broker, code_str, category)
    except: curr_price = 0

    # [B] 1순위: 야후 파이낸스 시도
    try:
        ticker_code = f"{code_str}.KS" if (category == '국내' and code_str.isdigit()) else code_str
        stock = yf.Ticker(ticker_code)
        info = stock.info
        
        # 1. 야후의 배당률(%) 데이터 확인
        y_val = info.get('dividendYield') or info.get('trailingAnnualDividendYield')
        if y_val:
            return round(float(y_val) * 100, 2), "야후(%)"
            
        # 2. 야후의 배당금(Amount) 데이터로 직접 계산
        div_rate = info.get('dividendRate')
        if div_rate and curr_price > 0:
            return round((float(div_rate) / curr_price) * 100, 2), "야후(금액계산)"
    except: pass

    # [C] 2순위: 네이버 모바일 API 백업 (국내 종목 전용)
    if category == '국내':
        try:
            url = f"https://m.stock.naver.com/api/stock/{code_str}/integration"
            headers = {'User-Agent': 'Mozilla/5.0 (iPhone; CPU iPhone OS 15_0 like Mac OS X)'}
            res = requests.get(url, headers=headers, timeout=5)
            if res.status_code == 200:
                data = res.json()
                # 배당금(원) 추출 후 계산
                div_amt = data.get('totalInfo', {}).get('dividend')
                if div_amt and curr_price > 0:
                    div_amt_f = float(str(div_amt).replace(',', ''))
                    return round((div_amt_f / curr_price) * 100, 2), "네이버(M-계산)"
                
                # 배당률(%) 추출
                yld = data.get('totalInfo', {}).get('dividendYield')
                if yld: return float(yld), "네이버(M-비율)"
        except: pass

    return 0.0, "조회실패"

# ==========================================
# [3] 데이터 로드 및 캘린더 로직
# ==========================================

def load_stock_data_from_csv():
    url = "https://raw.githubusercontent.com/broadcast777/my-dividend-app/main/stocks.csv"
    try: return pd.read_csv(url, dtype={'종목코드': str})
    except: return pd.DataFrame()

def calculate_google_calendar_url(ticker_name, pay_date_str):
    try:
        today = datetime.date.today()
        target_date = None
        clean_str = str(pay_date_str).replace(" ", "").strip()
        if "매월" in clean_str:
            if "마지막" in clean_str or "말일" in clean_str:
                last_day = calendar.monthrange(today.year, today.month)[1]
                target_date = datetime.date(today.year, today.month, last_day)
            else:
                nums = re.findall(r'\d+', clean_str)
                if nums:
                    day = int(nums[0])
                    try: target_date = datetime.date(today.year, today.month, day)
                    except: target_date = datetime.date(today.year, today.month, 1)
            if target_date and target_date < today:
                next_m = today.month + 1 if today.month < 12 else 1
                next_y = today.year if today.month < 12 else today.year + 1
                target_date = datetime.date(next_y, next_m, target_date.day)
        elif "-" in clean_str or "." in clean_str:
            clean_str = clean_str.split("(")[0].replace(".", "-")
            target_date = datetime.datetime.strptime(clean_str, "%Y-%m-%d").date()
        if not target_date: return None
        safe_buy_date = target_date - datetime.timedelta(days=3)
        while safe_buy_date.weekday() >= 5: safe_buy_date -= datetime.timedelta(days=1)
        title = quote(f"💰 [{ticker_name}] 매수 준비 (D-3)")
        details = quote(f"배당 기준일(예상): {target_date}\n✅ 안전 매수 추천일: {safe_buy_date}")
        return f"https://www.google.com/calendar/render?action=TEMPLATE&text={title}&dates={safe_buy_date.strftime('%Y%m%d')}/{(safe_buy_date + datetime.timedelta(days=1)).strftime('%Y%m%d')}&details={details}"
    except: return None

def generate_portfolio_ics(selected_stocks_data):
    cal_content = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//DividendPange//Portfolio//KO", "METHOD:PUBLISH"]
    for item in selected_stocks_data:
        name = item.get('종목', '종목명')
        event = ["BEGIN:VEVENT", f"SUMMARY:💰 [{name}] 매수 준비 (D-3)", "END:VEVENT"]
        cal_content.extend(event)
    cal_content.append("END:VCALENDAR")
    return "\n".join(cal_content)

@st.cache_data(ttl=600, show_spinner=False)
def load_and_process_data(df_raw, is_admin=False):
    if df_raw.empty: return pd.DataFrame()
    try:
        broker = mojito.KoreaInvestment(api_key=st.secrets["kis"]["app_key"], api_secret=st.secrets["kis"]["app_secret"], acc_no=st.secrets["kis"]["acc_no"], mock=True)
    except: return pd.DataFrame()

    results = [None] * len(df_raw)
    def process_row(idx, row):
        code, name, category = str(row.get('종목코드', '')).strip(), str(row.get('종목명', '')).strip(), str(row.get('분류', '국내')).strip()
        price = get_safe_price(broker, code, category)
        if not price: return idx, None
        try: months = int(row.get('신규상장개월수', 0))
        except: months = 0
        
        if 0 < months < 12:
            yield_val = ((float(row.get('연배당금', 0)) / months) * 12 / price) * 100
            display_name = f"{name} ⭐"
        elif '연배당률' in row and pd.notnull(row['연배당률']) and str(row['연배당률']).strip() != "":
            yield_val = float(row['연배당률'])
            display_name = name
        else:
            yield_val = (float(row.get('연배당금', 0)) / price) * 100
            display_name = name
            
        return idx, {
            '코드': code, '종목명': display_name, '현재가': f"{int(price):,}원" if category == '국내' else f"${price:.2f}",
            '연배당률': yield_val, '환구분': get_hedge_status(name, category), '배당락일': str(row.get('배당락일', '-')),
            '분류': category, '자산유형': classify_asset(row), 'pure_name': name,
            '캘린더링크': calculate_google_calendar_url(display_name, str(row.get('배당락일', '-'))),
            '신규상장개월수': months
        }
        
    with ThreadPoolExecutor(max_workers=5) as executor:
        futures = {executor.submit(process_row, idx, row): idx for idx, row in df_raw.iterrows()}
        for f in as_completed(futures):
            idx, res = f.result()
            results[idx] = res
            
    final = [r for r in results if r is not None]
    return pd.DataFrame(final).sort_values('연배당률', ascending=False)

def update_dividend_rolling(current_history_str, new_dividend_amount):
    if pd.isna(current_history_str) or str(current_history_str).strip() == "": history = []
    else: history = [int(float(x)) for x in str(current_history_str).split('|')]
    if len(history) >= 12: history.pop(0)
    history.append(int(new_dividend_amount))
    return sum(history), "|".join(map(str, history))

# ==========================================
# [4] 시뮬레이션 및 데이터 저장
# ==========================================

def run_asset_simulation(start_money, monthly_add, avg_y, years_sim, is_isa_mode, reinvest_ratio, isa_exempt):
    months_sim = years_sim * 12
    monthly_yld = avg_y / 100 / 12
    current_bal, total_principal = start_money, start_money
    sim_data = [{"년차": 0, "자산총액": current_bal/10000, "총원금": total_principal/10000, "실제월배당": 0}]
    total_tax = 0
    for m in range(1, months_sim + 1):
        current_bal += monthly_add
        total_principal += monthly_add
        div = current_bal * monthly_yld
        if is_isa_mode: reinvest = div
        else:
            tax = div * 0.154
            total_tax += tax
            reinvest = (div - tax) * (reinvest_ratio / 100)
        current_bal += reinvest
        sim_data.append({"년차": m/12, "자산총액": current_bal/10000, "총원금": total_principal/10000, "실제월배당": div})
    return sim_data, total_tax

def calculate_goal_duration(target_monthly_goal, start_bal_goal, monthly_add_goal, avg_y, tax_factor):
    required_asset_goal = (target_monthly_goal / tax_factor) / (avg_y / 100) * 12
    current_bal_goal, months_passed = start_bal_goal, 0
    while current_bal_goal < required_asset_goal and months_passed < 600:
        div_reinvest = current_bal_goal * (avg_y / 100 / 12) * tax_factor
        current_bal_goal += monthly_add_goal + div_reinvest
        months_passed += 1
    return required_asset_goal, months_passed

def save_to_github(df):
    try:
        g = Github(st.secrets["github"]["token"])
        repo = g.get_repo(st.secrets["github"]["repo_name"])
        contents = repo.get_contents(st.secrets["github"]["file_path"])
        repo.update_file(contents.path, "🤖 데이터 자동 갱신", df.to_csv(index=False).encode("utf-8"), contents.sha)
        return True, "✅ 저장 성공!"
    except Exception as e: return False, f"❌ 실패: {e}"
