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
import os
from github import Github

# [추가] 패치된 네트워크 유틸리티 연결
try:
    from utils_net import requests_session_with_retries
except ImportError:
    # utils_net.py가 없을 경우를 대비한 기본 세션 정의
    def requests_session_with_retries():
        return requests.Session()

# --- [1] 시세 조회 및 유틸 함수 ---
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
    try:
        today = datetime.date.today()
        target_date = None
        if not isinstance(pay_date_str, str): pay_date_str = str(pay_date_str)
        clean_str = pay_date_str.replace(" ", "").strip()
        
        if "매월" in clean_str:
            if "마지막" in clean_str or "말일" in clean_str:
                last_day_current = calendar.monthrange(today.year, today.month)[1]
                candidate_date = datetime.date(today.year, today.month, last_day_current)
                if candidate_date < today:
                    next_month = today.month + 1 if today.month < 12 else 1
                    next_year = today.year if today.month < 12 else today.year + 1
                    last_day_next = calendar.monthrange(next_year, next_month)[1]
                    target_date = datetime.date(next_year, next_month, last_day_next)
                else: target_date = candidate_date
            else:
                numbers = re.findall(r'\d+', clean_str)
                if numbers:
                    day = int(numbers[0])
                    try: candidate_date = datetime.date(today.year, today.month, day)
                    except ValueError: candidate_date = datetime.date(today.year, today.month, calendar.monthrange(today.year, today.month)[1])
                    if candidate_date < today:
                        next_month = today.month + 1 if today.month < 12 else 1
                        next_year = today.year if today.month < 12 else today.year + 1
                        try: target_date = datetime.date(next_year, next_month, day)
                        except ValueError: target_date = datetime.date(next_year, next_month, calendar.monthrange(next_year, next_month)[1])
                    else: target_date = candidate_date
                elif "초" in clean_str:
                    candidate_date = datetime.date(today.year, today.month, 1)
                    if candidate_date < today:
                        next_month = today.month + 1 if today.month < 12 else 1
                        next_year = today.year if today.month < 12 else today.year + 1
                        target_date = datetime.date(next_year, next_month, 1)
                    else: target_date = candidate_date
        elif "-" in clean_str or "." in clean_str:
            clean_str = clean_str.split("(")[0].replace(".", "-")
            try: target_date = datetime.datetime.strptime(clean_str, "%Y-%m-%d").date()
            except: return None
        if target_date is None: return None

        safe_buy_date = target_date - datetime.timedelta(days=3)
        while safe_buy_date.weekday() >= 5:
            safe_buy_date -= datetime.timedelta(days=1)
        start_str = safe_buy_date.strftime("%Y%m%d")
        end_str = (safe_buy_date + datetime.timedelta(days=1)).strftime("%Y%m%d")
        title = quote(f"💰 [{ticker_name}] 매수 준비 (D-3)")
        details = quote(f"배당 기준일(예상): {target_date}\n✅ 안전 매수 추천일: {safe_buy_date} (오늘)\n\n⚠️ 주의: 본 일정은 과거 데이터 기반의 추정일입니다.\n매수 전 반드시 확정 일자를 재확인해주세요!")
        return f"https://www.google.com/calendar/render?action=TEMPLATE&text={title}&dates={start_str}/{end_str}&details={details}"
    except Exception as e:
        print(f"Calendar Error: {e}")
        return None

# --- [2] 메인 데이터 로직 ---
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
    except: return pd.DataFrame()
    
    results = [None] * len(df_raw)
    def process_row(idx, row):
        try:
            code = str(row.get('종목코드', '')).strip()
            name = str(row.get('종목명', '')).strip()
            category = str(row.get('분류', '국내')).strip()
            price = get_safe_price(broker, code, category)
            if not price: return idx, None

            crawled_div = float(row.get('연배당률', 0)) # 기존 명칭 유지
            manual_div = float(row.get('연배당금', 0))
            try: months = int(row.get('신규상장개월수', 0))
            except: months = 0

            if 0 < months < 12:
                if manual_div > 0: target_div = (manual_div / months) * 12
                else: target_div = crawled_div if crawled_div > 0 else 0
                display_name = f"{name} ⭐"
            else:
                target_div = crawled_div if crawled_div > 0 else manual_div
                display_name = name

            yield_val = (target_div / price) * 100
            if not is_admin and (yield_val < 2.0 or yield_val > 25.0): return idx, None
            price_fmt = f"{int(price):,}원" if category == '국내' else f"${price:.2f}"

            return idx, {
                '코드': code, '종목명': display_name,
                '블로그링크': str(row.get('블로그링크', '#')),
                '금융링크': f"https://finance.naver.com/item/main.naver?code={code}" if category == '국내' else f"https://finance.yahoo.com/quote/{code}",
                '현재가': price_fmt, '연배당률': yield_val,
                '환구분': get_hedge_status(name, category),
                '배당락일': str(row.get('배당락일', '-')), '분류': category,
                '자산유형': classify_asset(row),
                '캘린더링크': calculate_google_calendar_url(display_name, str(row.get('배당락일', '-'))),
                'pure_name': name.replace("🚫 ", ""), '신규상장개월수': months,
                '배당기록': str(row.get('배당기록', ''))
            }
        except: return idx, None

    with ThreadPoolExecutor(max_workers=5) as executor:
        futures = {executor.submit(process_row, idx, row): idx for idx, row in df_raw.iterrows()}
        for future in as_completed(futures):
            idx, result = future.result()
            results[idx] = result
    final_data = [r for r in results if r is not None]
    return pd.DataFrame(final_data).sort_values('연배당률', ascending=False) if final_data else pd.DataFrame()

@st.cache_data(ttl=600)
def load_stock_data_from_csv():
    url = "https://raw.githubusercontent.com/broadcast777/my-dividend-app/main/stocks.csv"
    try:
        df = pd.read_csv(url, dtype={'종목코드': str})
        if '연배당금_크롤링' not in df.columns: df['연배당금_크롤링'] = 0.0
        for col in ['종목명', '분류', '블로그링크', '배당기록']:
            if col not in df.columns: df[col] = ""
            else: df[col] = df[col].fillna("").astype(str)
        return df
    except Exception as e:
        print(f"❌ [CSV 로드 실패] Error: {e}")
        return pd.DataFrame()

# --- [3] 크롤링 핵심 로직 (네이버 모바일 분석 페이지 패치) ---
def fetch_dividend_amount_hybrid(code, category):
    import json
    code = str(code).strip().zfill(6)
    session = requests_session_with_retries()
    headers = {
        'User-Agent': 'Mozilla/5.0 (iPhone; CPU iPhone OS 16_6 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.6 Mobile/15E148 Safari/604.1',
        'Referer': f'https://m.stock.naver.com/domestic/stock/{code}/analysis'
    }

    if category == '국내':
        try:
            # 1순위: API 직접 호출 (재시도 세션 사용)
            api_url = f"https://api.stock.naver.com/etf/{code}/distribution"
            api_res = session.get(api_url, headers=headers, timeout=5)
            if api_res.status_code == 200:
                data = api_res.json()
                dist_list = data.get('result', {}).get('distributionInfoList', [])
                if dist_list:
                    val = float(str(dist_list[0].get('amount', 0)).replace(',', ''))
                    if val > 0: return val * 12, "✅ 네이버(ETF)"
            
            # 2순위: 주식 배당 API
            url_stock = f"https://api.stock.naver.com/stock/{code}/dividend"
            res = session.get(url_stock, headers=headers, timeout=5)
            if res.status_code == 200:
                data = res.json()
                items = data.get('dividendHistory', []) or data.get('items', [])
                if items:
                    val = float(str(items[0].get('dividendPerShare') or items[0].get('dividend') or 0).replace(',', ''))
                    if val > 0: return val * 12, "✅ 네이버(주식)"
        except: pass

    # 3순위: 야후 파이낸스 백업
    try:
        ticker_symbol = f"{code}.KS" if category == '국내' else code
        stock = yf.Ticker(ticker_symbol)
        divs = stock.dividends
        if not divs.empty:
            one_year_ago = pd.Timestamp.now() - pd.Timedelta(days=365)
            total = divs[divs.index >= one_year_ago].sum()
            if total > 0: return float(total), "✅ 야후(합계)"
        rate = stock.info.get('dividendRate')
        if rate and rate > 0: return float(rate), "✅ 야후(Rate)"
    except: pass
    return 0.0, "⚠️ 데이터없음"

# --- [4] 기타 데이터 관리 함수 ---
def update_dividend_rolling(current_history_str, new_dividend_amount):
    if pd.isna(current_history_str) or str(current_history_str).strip() == "": history = []
    else: history = [int(float(x)) for x in str(current_history_str).split('|')]
    if len(history) >= 12: history.pop(0)
    history.append(int(new_dividend_amount))
    return sum(history), "|".join(map(str, history))

def save_to_github(df, create_local_backup_on_fail=True):
    try:
        token = st.secrets["github"]["token"]
        repo_name = st.secrets["github"]["repo_name"]
        file_path = st.secrets["github"]["file_path"]
        g = Github(token)
        repo = g.get_repo(repo_name)
        contents = repo.get_contents(file_path)
        csv_text = df.to_csv(index=False)
        repo.update_file(path=contents.path, message="🤖 데이터 자동 갱신", content=csv_text, sha=contents.sha)
        return True, "✅ 깃허브 저장 성공!"
    except Exception as e:
        err_msg = f"❌ 저장 실패: {str(e)}"
        if create_local_backup_on_fail:
            backup_name = f"stocks_backup_failed_{int(time.time())}.csv"
            df.to_csv(backup_name, index=False)
            err_msg += f" | 💾 로컬 백업됨"
        return False, err_msg

def generate_portfolio_ics(selected_stocks_data):
    cal_content = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//DividendPange//KO", "METHOD:PUBLISH"]
    today = datetime.date.today()
    for item in selected_stocks_data:
        name = item.get('종목', '종목명')
        pay_date_str = item.get('배당락일', '-')
        target_date = None
        clean_str = str(pay_date_str).replace(" ", "").strip()
        numbers = re.findall(r'\d+', clean_str)
        if "마지막" in clean_str or "말일" in clean_str:
            target_date = datetime.date(today.year, today.month, calendar.monthrange(today.year, today.month)[1])
        elif numbers:
            day = int(numbers[0])
            try: target_date = datetime.date(today.year, today.month, day)
            except: target_date = datetime.date(today.year, today.month, 1)
        
        if target_date:
            if target_date < today:
                next_m = today.month + 1 if today.month < 12 else 1
                next_y = today.year if today.month < 12 else today.year + 1
                target_date = datetime.date(next_y, next_m, min(target_date.day, 28))
            safe_buy = target_date - datetime.timedelta(days=3)
            while safe_buy.weekday() >= 5: safe_buy -= datetime.timedelta(days=1)
            dt_s = safe_buy.strftime("%Y%m%d")
            dt_e = (safe_buy + datetime.timedelta(days=1)).strftime("%Y%m%d")
            cal_content.extend(["BEGIN:VEVENT", f"DTSTART;VALUE=DATE:{dt_s}", f"DTEND;VALUE=DATE:{dt_e}", f"SUMMARY:💰 [{name}] 매수 준비 (D-3)", f"DESCRIPTION:예상일: {target_date}\\n✅ 안전 매수 추천!", "END:VEVENT"])
    cal_content.append("END:VCALENDAR")
    return "\n".join(cal_content)
