"""
프로젝트: 배당 팽이 (Dividend Top) v1.5_Fix
파일명: logic.py
설명: 사장님 v1.5 코드 기반 + ETF/리츠 우선 검색 + 해외 야후 복구 + 차단 방지 적용
"""

import streamlit as st
import pandas as pd
import yfinance as yf
from concurrent.futures import ThreadPoolExecutor, as_completed
import time
import random 
import mojito 
import datetime 
import calendar 
from urllib.parse import quote
import re
import requests
from github import Github

# -----------------------------------------------------------
# [SECTION 1] 캘린더 및 날짜 헬퍼 (v1.5 원본 유지)
# -----------------------------------------------------------
def standardize_date_format(date_str):
    s = str(date_str).strip()
    if re.match(r'^\d{4}-\d{2}-\d{2}$', s): return s
    s = s.replace('.', '-').replace('/', '-')
    match = re.match(r'^(\d{4})-(\d{1,2})-(\d{1,2})$', s)
    if match:
        y, m, d = match.groups()
        return f"{y}-{m.zfill(2)}-{d.zfill(2)}"
    return s

def parse_dividend_date(date_str):
    s = standardize_date_format(str(date_str))
    today = datetime.date.today()
    try: return datetime.datetime.strptime(s, "%Y-%m-%d").date()
    except: pass
    
    is_end_of_month = any(k in s for k in ['말일', '월말', '마지막', '하순', 'END'])
    is_start_of_month = any(k in s for k in ['매월 초', '월초', '1~3일', 'BEGIN'])
    day_match = re.search(r'(\d+)', s)
    
    if is_end_of_month or is_start_of_month or (day_match and ('매월' in s or '일' in s)):
        try:
            if is_end_of_month: day = calendar.monthrange(today.year, today.month)[1]
            elif is_start_of_month: day = 1 
            else: day = int(day_match.group(1))
            try:
                last_day_actual = calendar.monthrange(today.year, today.month)[1]
                safe_day = min(day, last_day_actual)
                target_date = datetime.date(today.year, today.month, safe_day)
            except ValueError: target_date = today
            if target_date < today:
                next_month = today.month + 1 if today.month < 12 else 1
                year = today.year if today.month < 12 else today.year + 1
                last_day_next = calendar.monthrange(year, next_month)[1]
                if is_end_of_month: real_day = last_day_next
                elif is_start_of_month: real_day = 1
                else: real_day = min(day, last_day_next)
                return datetime.date(year, next_month, real_day)
            return target_date
        except Exception: pass
    return None 

def generate_portfolio_ics(portfolio_data):
    ics_content = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//Dividend//KO", "METHOD:PUBLISH"]
    today = datetime.date.today()
    for item in portfolio_data:
        date_info = str(item.get('배당락일', '-')).strip()
        if date_info in ['-', 'nan', 'None', '']: continue
        
        target_date = parse_dividend_date(date_info)
        if not target_date: continue
        
        safe_date = target_date - datetime.timedelta(days=3)
        while safe_date.weekday() >= 5: safe_date -= datetime.timedelta(days=1)
        
        if safe_date < today: continue

        dt_start = safe_date.strftime("%Y%m%d")
        dt_end = (safe_date + datetime.timedelta(days=1)).strftime("%Y%m%d")
        name = item.get('종목', '배당주')
        ics_content.append(f"BEGIN:VEVENT\nSUMMARY:💰 [{name}] 매수 D-3\nDTSTART;VALUE=DATE:{dt_start}\nDTEND;VALUE=DATE:{dt_end}\nDESCRIPTION:예상 배당락일: {target_date}\nEND:VEVENT")
        
    ics_content.append("END:VCALENDAR")
    return "\n".join(ics_content)

def get_google_cal_url(stock_name, date_str):
    try:
        t_date = parse_dividend_date(date_str)
        if not t_date: return None
        s_date = t_date - datetime.timedelta(days=3)
        while s_date.weekday() >= 5: s_date -= datetime.timedelta(days=1)
        
        dates = f"{s_date.strftime('%Y%m%d')}/{(s_date+datetime.timedelta(days=1)).strftime('%Y%m%d')}"
        title = quote(f"💰 [{stock_name}] 매수 D-3")
        return f"https://www.google.com/calendar/render?action=TEMPLATE&text={title}&dates={dates}"
    except: return None

# -----------------------------------------------------------
# [SECTION 2] 시세 및 데이터 로드 (스레드 2개 제한)
# -----------------------------------------------------------

def get_safe_price(broker, code, category):
    try:
        code = str(code).strip()
        # 1. 해외: 야후
        if category == '해외':
            t = yf.Ticker(code)
            return t.fast_info.get('last_price')
        
        # 2. 국내: KIS -> 네이버 API (Basic)
        else:
            try:
                if broker:
                    resp = broker.fetch_price(code)
                    if resp and 'output' in resp: return int(resp['output']['stck_prpr'])
            except: pass
            
            # 네이버 모바일 API (Basic) - 사장님 v1.5 방식
            url = f"https://api.stock.naver.com/stock/{code}/basic"
            headers = {'User-Agent': 'Mozilla/5.0'}
            res = requests.get(url, headers=headers, timeout=3)
            data = res.json()
            if 'closePrice' in data:
                return float(data['closePrice'].replace(',', ''))
    except: pass
    return None

def classify_asset(row):
    name = str(row.get('종목명', '')).upper()
    if '커버드' in name or 'QYLD' in name or 'JEP' in name: return '🛡️ 커버드콜'
    if '채권' in name or 'TLT' in name or 'GOV' in name: return '🏦 채권형'
    if '리츠' in name: return '🏢 리츠형'
    return '📈 주식형'

def get_hedge_status(name, category):
    if category == '해외': return "💲달러"
    if "(H)" in str(name).upper(): return "🛡️환헤지"
    return "⚡환노출"

@st.cache_data(ttl=1800, show_spinner=False)
def load_and_process_data(df_raw, is_admin=False):
    if df_raw.empty: return pd.DataFrame()
    
    cols = ['연배당금', '연배당률', '현재가', '신규상장개월수', '연배당금_크롤링']
    for c in cols:
        if c in df_raw.columns: df_raw[c] = pd.to_numeric(df_raw[c], errors='coerce').fillna(0)

    try:
        broker = mojito.KoreaInvestment(
            api_key=st.secrets["kis"]["app_key"],
            api_secret=st.secrets["kis"]["app_secret"],
            acc_no=st.secrets["kis"]["acc_no"],
            mock=True 
        )
    except: broker = None

    results = [None] * len(df_raw)

    def process_row(idx, row):
        try:
            time.sleep(random.uniform(0.5, 1.0)) # 차단 방지 대기
            
            code = str(row.get('종목코드', '')).strip()
            name = str(row.get('종목명', '')).strip()
            category = str(row.get('분류', '국내')).strip()
            
            price = get_safe_price(broker, code, category) or 0
            
            c_div = float(row.get('연배당금_크롤링', 0))
            m_div = float(row.get('연배당금', 0))
            target_div = c_div if c_div > 0 else m_div
            
            months = int(row.get('신규상장개월수', 0))
            if 0 < months < 12 and m_div > 0:
                target_div = (m_div / months) * 12
                name = f"{name} ⭐"

            yield_val = (target_div / price * 100) if price > 0 else 0
            
            return idx, {
                '코드': code, '종목명': name,
                '블로그링크': str(row.get('블로그링크', '#')),
                '금융링크': f"https://m.stock.naver.com/domestic/stock/{code}/total" if category=='국내' else f"https://finance.yahoo.com/quote/{code}",
                '현재가': f"{int(price):,}" if category=='국내' else f"${price:.2f}",
                '연배당률': yield_val,
                '배당락일': str(row.get('배당락일', '-')),
                '분류': category, '유형': str(row.get('유형', '-')),
                '자산유형': classify_asset(row),
                '환구분': get_hedge_status(name, category),
                'pure_name': name.replace("⭐", "").strip(),
                '신규상장개월수': months,
                '배당기록': str(row.get('배당기록', ''))
            }
        except: return idx, None

    # 안정성을 위해 스레드 2개로 제한
    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = {executor.submit(process_row, idx, row): idx for idx, row in df_raw.iterrows()}
        for future in as_completed(futures):
            idx, result = future.result()
            results[idx] = result
            
    final = [r for r in results if r is not None]
    return pd.DataFrame(final).sort_values('연배당률', ascending=False) if final else pd.DataFrame()

@st.cache_data
def load_stock_data_from_csv():
    try: 
        df = pd.read_csv("stocks.csv", dtype={'종목코드': str})
        df.columns = df.columns.str.strip()
        return df
    except: return pd.DataFrame()

def save_to_github(df):
    try:
        g = Github(st.secrets["github"]["token"])
        repo = g.get_repo(st.secrets["github"]["repo_name"])
        contents = repo.get_contents(st.secrets["github"]["file_path"])
        repo.update_file(contents.path, "Update", df.to_csv(index=False).encode("utf-8"), contents.sha)
        return True, "✅ 저장 완료"
    except Exception as e: return False, str(e)

# -----------------------------------------------------------
# [SECTION 4] ★ 핵심 크롤링 (ETF 우선 + 야후 복구) ★
# -----------------------------------------------------------

def fetch_dividend_yield_hybrid(code, category):
    """
    해외: 야후 dividendYield 사용 (15분 전 잘되던 방식)
    국내: 네이버 ETF API 우선 타격 (사장님 종목 100% ETF 대응)
    """
    code = str(code).strip()
    
    # =======================================================
    # [1] 해외 주식 (야후 15분 전 성공 로직 복원)
    # =======================================================
    if category == '해외':
        try:
            stock = yf.Ticker(code)
            # 1. 야후가 주는 연배당률 바로 사용
            dy = stock.info.get('dividendYield', 0)
            if dy and dy > 0: 
                return round(dy * 100, 2), "✅ 야후(Info)"
            
            # 2. 없으면 배당금 합계로 계산
            divs = stock.dividends
            if not divs.empty:
                recent_total = divs.iloc[-12:].sum() if len(divs) > 12 else divs.sum()
                price = stock.fast_info.get('last_price')
                if price and price > 0:
                    val = (recent_total / price) * 100
                    return round(val, 2), f"✅ 야후(계산)"
            
            return 0.0, "⚠️ 데이터 없음"
        except Exception as e:
            time.sleep(1) # 에러 시 잠시 대기
            return 0.0, f"❌ 해외 에러"

    # =======================================================
    # [2] 국내 주식/ETF (v1.5 헤더 + ETF 주소 우선 적용)
    # =======================================================
    else:
        current_price = 0
        
        # [Step 1] 현재가 (v1.5 Basic API)
        try:
            url = f"https://api.stock.naver.com/stock/{code}/basic"
            # Referer 없이도 Basic은 잘 줍니다
            headers = {'User-Agent': 'Mozilla/5.0'}
            res = requests.get(url, headers=headers, timeout=3)
            data = res.json()
            if 'closePrice' in data:
                current_price = float(data['closePrice'].replace(',', ''))
        except: pass
        
        if current_price == 0: return 0.0, "⚠️ 가격 조회 실패"

        # [Step 2] 배당금 조회 (사장님 CSV는 다 ETF이므로 ETF 주소를 먼저 씀!)
        last_val = 0
        source_type = ""
        
        # v1.5에서 썼던 모바일 헤더 (필수)
        headers_mobile = {
            'User-Agent': 'Mozilla/5.0 (iPhone; CPU iPhone OS 13_2_3 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/13.0.3 Mobile/15E148 Safari/604.1',
            'Referer': f'https://m.stock.naver.com/'
        }

        # (A) ETF 분배금 (distribution) -> 사장님 종목 33개는 여기서 다 걸림
        try:
            url_etf = f"https://api.stock.naver.com/etf/{code}/distribution/list?page=1&pageSize=1"
            res = requests.get(url_etf, headers=headers_mobile, timeout=3)
            if res.status_code == 200:
                data = res.json()
                # result -> distributionInfoList -> amount
                content = data.get('result', {}).get('distributionInfoList')
                if content:
                    last_val = float(content[0].get('amount', 0))
                    source_type = "ETF분배"
        except: pass
        
        # (B) 일반 주식 배당금 (dividend) -> 혹시 몰라 남겨둠
        if last_val == 0:
            try:
                url_stock = f"https://api.stock.naver.com/stock/{code}/dividend/list?page=1&pageSize=1"
                res = requests.get(url_stock, headers=headers_mobile, timeout=3)
                if res.status_code == 200:
                    data = res.json()
                    # content -> dividendPerShare
                    content = data.get('content')
                    if content:
                        last_val = float(content[0].get('dividendPerShare', 0))
                        source_type = "주식배당"
            except: pass
            
        # [Step 3] 최종 계산 (최근금액 * 12 / 현재가)
        if last_val > 0:
            yield_val = (last_val * 12 / current_price) * 100
            return round(yield_val, 2), f"✅ {source_type}({int(last_val)}원)"
            
        return 0.0, "⚠️ 내역 없음"

def update_dividend_rolling(current_history_str, new_dividend_amount):
    """배당금 기록 갱신"""
    if pd.isna(current_history_str) or str(current_history_str).strip() == "":
        history = []
    else:
        try: history = [int(float(x)) for x in str(current_history_str).split('|') if x.strip()]
        except: history = []

    if len(history) >= 12: history.pop(0)
    history.append(int(new_dividend_amount))
    return sum(history), "|".join(map(str, history))
