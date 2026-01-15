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
# [1] 시세 조회 유틸리티 (Global)
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
    for _ in range(2):
        price = _fetch_price_raw(broker, code, category)
        if price is not None: return price
        time.sleep(0.5)
    return None

def fetch_dividend_yield_hybrid(code, category):
    """
    [정밀 수리 버전]
    1. 해외: 야후 파이낸스 사용 + 소수점 단위 오류(1149% 등) 자동 보정
    2. 국내: 네이버 모바일 배당 히스토리 API 호출 -> 최근 1년치 합산(TTM) 후 직접 계산
    """
    import requests
    import yfinance as yf
    from datetime import datetime, timedelta

    code_str = str(code).strip().zfill(6) if category == '국내' else str(code).strip()
    
    # [1] 분모(현재가) 확보
    try:
        broker = mojito.KoreaInvestment(
            api_key=st.secrets["kis"]["app_key"], 
            api_secret=st.secrets["kis"]["app_secret"], 
            acc_no=st.secrets["kis"]["acc_no"], 
            mock=True
        )
        curr_price = get_safe_price(broker, code_str, category)
    except: curr_price = 0

    # ==========================================
    # [A] 국내 종목: 네이버 배당 히스토리 정밀 합산
    # ==========================================
    if category == '국내':
        try:
            # 선생님이 말씀하신 '배당 분석' 데이터의 원천 API
            url = f"https://m.stock.naver.com/api/stock/{code_str}/dividend"
            headers = {'User-Agent': 'Mozilla/5.0 (iPhone; CPU iPhone OS 15_0 like Mac OS X)'}
            res = requests.get(url, headers=headers, timeout=5)
            
            if res.status_code == 200:
                data = res.json()
                items = data.get('items', [])
                
                if items and curr_price > 0:
                    today = datetime.now()
                    one_year_ago = today - timedelta(days=365)
                    
                    annual_div_sum = 0
                    valid_items_count = 0
                    
                    for item in items:
                        # 배당기준일(recordDate) 확인
                        rec_date_str = item.get('recordDate') # "2024.12.31"
                        div_val = float(str(item.get('dividend', 0)).replace(',', ''))
                        
                        if rec_date_str:
                            rec_date = datetime.strptime(rec_date_str, "%Y.%m.%d")
                            # 최근 1년 이내의 배당 내역만 합산
                            if rec_date >= one_year_ago:
                                annual_div_sum += div_val
                                valid_items_count += 1
                    
                    # [특수 보정] 476800 같은 신규 상장 월배당 ETF 대응
                    # 내역이 12개가 안 되는데 '프리미엄'이나 '월배당' 성격인 경우 최신값 * 12
                    if 0 < valid_items_count < 12:
                        recent_val = float(str(items[0].get('dividend', 0)).replace(',', ''))
                        # 연간 예상치로 환산
                        annual_div_sum = recent_val * 12
                    
                    if annual_div_sum > 0:
                        calc_yield = (annual_div_sum / curr_price) * 100
                        return round(calc_yield, 2), "네이버(히스토리)"
        except: pass

    # ==========================================
    # [B] 해외 종목: 야후 파이낸스 + 소수점 단위 보정
    # ==========================================
    else:
        try:
            stock = yf.Ticker(code_str)
            info = stock.info
            
            # 야후는 0.08(8%) 또는 8.0(8%)를 혼용해서 줌
            raw_yield = info.get('dividendYield') or info.get('trailingAnnualDividendYield')
            
            if raw_yield:
                val = float(raw_yield)
                # 1.0보다 작으면(예: 0.1149) 100을 곱해서 11.49로 만듦
                if val < 1.0: val *= 100 
                # 100보다 크면(예: 1149.0) 100으로 나눠서 11.49로 만듦 (1149% 오류 방어)
                elif val > 100: val /= 100
                
                return round(val, 2), "야후"
            
            # 배당률이 비어있으면 배당금액(dividendRate)으로 직접 계산
            div_rate = info.get('dividendRate')
            if div_rate and curr_price > 0:
                calc_val = (float(div_rate) / curr_price) * 100
                if calc_val > 100: calc_val /= 100
                return round(calc_val, 2), "야후(계산)"
        except: pass

    return 0.0, "조회실패"

# ==========================================
# [3] 기타 유틸리티 함수 (중략 없이 포함)
# ==========================================

def load_stock_data_from_csv():
    url = "https://raw.githubusercontent.com/broadcast777/my-dividend-app/main/stocks.csv"
    try: return pd.read_csv(url, dtype={'종목코드': str})
    except: return pd.DataFrame()

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
