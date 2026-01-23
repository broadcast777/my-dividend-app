"""
프로젝트: 배당 팽이 (Dividend Top) v3.2
파일명: logic.py
설명: 금융 API 연동, 데이터 크롤링 (Auto/TTM 조회 기능 완전 복구 및 최적화)
업데이트: 2026.01.23
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
import sqlite3
from playwright.sync_api import sync_playwright
import os
import subprocess
import logging
from bs4 import BeautifulSoup

# -----------------------------------------------------------
# 로거 설정
# -----------------------------------------------------------
if not logging.getLogger().handlers:
    logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# -----------------------------------------------------------
# [SECTION 0] TTM 데이터 확보 (API 계산기 + Playwright)
# -----------------------------------------------------------

def _ensure_browser_installed():
    """브라우저가 없으면 자동으로 설치 명령어를 실행합니다."""
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            try:
                p.chromium.launch(headless=True)
            except Exception:
                subprocess.run(["playwright", "install", "chromium"], check=True)
    except Exception:
        pass

def get_ttm_or_calculate(code):
    """
    [TTM 구하기]
    1. 네이버 배당 내역 API를 호출하여 최근 1년치 배당금을 '직접 합산' (가장 정확)
    2. 실패 시, 화면 크롤링(Playwright) 시도
    """
    code = str(code).strip()
    
    # 1. API로 직접 계산 (속도 빠름)
    try:
        # 현재가 조회
        price_url = f"https://api.stock.naver.com/etf/{code}/basic"
        price_res = requests.get(price_url, timeout=3, headers={"User-Agent": "Mozilla/5.0"})
        current_price = 0
        if price_res.status_code == 200:
            p_data = price_res.json()
            if 'result' in p_data and 'closePrice' in p_data['result']:
                current_price = float(p_data['result']['closePrice'])

        # 배당 내역 조회
        hist_url = f"https://m.stock.naver.com/api/etf/{code}/dividend/history?pageSize=20"
        res = requests.get(hist_url, timeout=5, headers={"User-Agent": "Mozilla/5.0"})
        
        if res.status_code == 200 and current_price > 0:
            data = res.json()
            items = []
            if isinstance(data, list): items = data
            elif isinstance(data, dict):
                items = data.get('result', []) or data.get('items', [])
            
            if items:
                ttm_sum = 0
                cutoff_date = (datetime.date.today() - datetime.timedelta(days=365)).strftime("%Y%m%d")
                
                for item in items:
                    d_date = str(item.get('paymentDate') or item.get('dividendDate') or "").replace(".", "")
                    amt = item.get('dividendAmount') or item.get('amount') or 0
                    if d_date >= cutoff_date:
                        ttm_sum += float(amt)
                
                if ttm_sum > 0:
                    final_yield = round((ttm_sum / current_price) * 100, 2)
                    return final_yield, f"✅ API계산({int(ttm_sum)}원/{final_yield}%)"
    except Exception:
        pass

    # 2. 실패하면 크롤링 (Playwright)
    try:
        yield_val, msg = _run_crawling(code)
        if yield_val > 0: return yield_val, msg
    except Exception as e:
        if "Executable" in str(e) or "browser" in str(e):
            _ensure_browser_installed()
            try:
                return _run_crawling(code)
            except: pass
        pass
    return 0.0, ""

def _run_crawling(code):
    """Playwright 크롤링 로직"""
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--no-sandbox"])
        context = browser.new_context(user_agent="Mozilla/5.0 (iPhone; CPU iPhone OS 15_0 like Mac OS X)")
        page = context.new_page()
        url = f"https://m.stock.naver.com/item/main.nhn#/stocks/{code}"
        page.goto(url, timeout=30000)
        page.wait_for_timeout(2000)
        page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        page.wait_for_timeout(1000)
        body_text = page.inner_text("body")
        pattern = re.compile(r'(?:배당수익률|분배금수익률).*?([\d\.]+)\s*%', re.DOTALL)
        match = pattern.search(body_text)
        browser.close()
        if match:
            val = float(match.group(1))
            return val, f"✅ 웹크롤링({val}%)"
    return 0.0, ""

# -----------------------------------------------------------
# [SECTION 1] 날짜 및 스케줄링 헬퍼
# -----------------------------------------------------------
def standardize_date_format(date_str):
    s = str(date_str).strip()
    if re.match(r'^\d{4}-\d{2}-\d{2}$', s): return s
    s = s.replace('.', '-').replace('/', '-')
    match = re.match(r'^(\d{4})-(\d{1,2})-(\d{1,2})$', s)
    if match: return f"{match.group(1)}-{match.group(2).zfill(2)}-{match.group(3).zfill(2)}"
    return s

def parse_dividend_date(date_str):
    s = standardize_date_format(str(date_str))
    today = datetime.date.today()
    try: return datetime.datetime.strptime(s, "%Y-%m-%d").date()
    except ValueError: pass
    
    is_end = any(k in s for k in ['말일', '월말', '마지막', 'END'])
    is_start = any(k in s for k in ['매월 초', '월초', 'BEGIN'])
    day_match = re.search(r'(\d+)', s)
    
    if is_end or is_start or (day_match and ('매월' in s or '일' in s)):
        try:
            if is_end: day = calendar.monthrange(today.year, today.month)[1]
            elif is_start: day = 1
            else: day = int(day_match.group(1))
            
            try:
                last_day = calendar.monthrange(today.year, today.month)[1]
                safe_day = min(day, last_day)
                target = datetime.date(today.year, today.month, safe_day)
            except: target = today
            
            if target < today:
                nm = today.month + 1 if today.month < 12 else 1
                ny = today.year if today.month < 12 else today.year + 1
                nd = calendar.monthrange(ny, nm)[1]
                if is_end: r_day = nd
                elif is_start: r_day = 1
                else: r_day = min(day, nd)
                return datetime.date(ny, nm, r_day)
            return target
        except: pass
    return None 

def generate_portfolio_ics(data):
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//DividendPange//KO", "CALSCALE:GREGORIAN"]
    today = datetime.date.today()
    for item in data:
        name = item.get('종목', '배당주')
        d_info = str(item.get('배당락일', '-')).strip()
        if d_info in ['-', 'nan', '']: continue
        
        target = parse_dividend_date(d_info) # 단순화: 다음 1회 일정만
        if target:
            buy_date = target - datetime.timedelta(days=4)
            while buy_date.weekday()>=5: buy_date-=datetime.timedelta(days=1)
            if buy_date < today: continue
            
            dt_s = buy_date.strftime("%Y%m%d")
            dt_e = (buy_date+datetime.timedelta(days=1)).strftime("%Y%m%d")
            desc = f"예상 배당락: {target}\\n💰 [{name}] 매수 권장"
            lines.extend(["BEGIN:VEVENT", f"DTSTART;VALUE=DATE:{dt_s}", f"DTEND;VALUE=DATE:{dt_e}", 
                          f"SUMMARY:🔔 [{name}] D-4", f"DESCRIPTION:{desc}", "END:VEVENT"])
    lines.append("END:VCALENDAR")
    return "\n".join(lines)

def get_google_cal_url(name, d_str):
    try:
        t = parse_dividend_date(d_str)
        if not t: return None
        b = t - datetime.timedelta(days=4)
        while b.weekday()>=5: b-=datetime.timedelta(days=1)
        base = "https://www.google.com/calendar/render?action=TEMPLATE"
        tit = quote(f"🔔 [{name}] D-4")
        det = quote(f"예상 배당락: {d_str}\n💰 매수 권장")
        d = f"{b.strftime('%Y%m%d')}/{(b+datetime.timedelta(days=1)).strftime('%Y%m%d')}"
        return f"{base}&text={tit}&dates={d}&details={det}"
    except: return None

# -----------------------------------------------------------
# [SECTION 2] 시세 및 기초 데이터
# -----------------------------------------------------------
def _fetch_naver_price(code):
    try:
        url = f"https://api.stock.naver.com/etf/{code}/basic"
        r = requests.get(url, timeout=2, headers={"User-Agent":"Mozilla/5.0"})
        if r.status_code==200:
            d = r.json()
            if 'result' in d and 'closePrice' in d['result']: return int(d['result']['closePrice'])
    except: pass
    return 0

def get_safe_price(broker, code, category):
    try:
        if category=='국내':
            try: 
                res = broker.fetch_price(code)
                if res and 'output' in res: return int(res['output']['stck_prpr'])
            except: pass
            p = _fetch_naver_price(code)
            if p > 0: return p
        
        # 해외/국내 백업
        t_code = f"{code}.KS" if category=='국내' else code
        tk = yf.Ticker(t_code)
        p = tk.fast_info.get('last_price')
        if not p: 
            h = tk.history(period='1d')
            if not h.empty: p = h['Close'].iloc[-1]
        return float(p) if p else 0
    except: return 0

def classify_asset(row):
    n, c = str(row.get('종목명','')).upper(), str(row.get('종목코드','')).upper()
    if any(k in n or k in c for k in ['커버드콜','COVERED','QYLD','JEPI']): return '🛡️ 커버드콜'
    if any(k in n or k in c for k in ['채권','국채','BOND','TLT']): return '🏦 채권형'
    if '리츠' in n or 'REITS' in n: return '🏢 리츠형'
    return '📈 주식형'

def get_hedge_status(n, c):
    if c=='해외': return "💲달러"
    if "(H)" in n or "헤지" in n: return "🛡️환헤지"
    return "⚡환노출"

# -----------------------------------------------------------
# [SECTION 3] 메인 데이터 로딩 (Fast)
# -----------------------------------------------------------
@st.cache_data(ttl=1800, show_spinner=False)
def load_and_process_data(df_raw, is_admin=False):
    if df_raw.empty: return pd.DataFrame()
    
    # 숫자 변환
    cols = ['연배당금','연배당률','현재가','신규상장개월수','연배당금_크롤링','연배당금_크롤링_auto','TTM_연배당률(크롤링)']
    for c in cols: 
        if c in df_raw.columns: df_raw[c] = pd.to_numeric(df_raw[c], errors='coerce').fillna(0)
    
    # 코드 정리
    if '종목코드' in df_raw.columns:
        df_raw['종목코드'] = df_raw['종목코드'].apply(lambda x: str(x).split('.')[0].strip().zfill(6) if str(x).isdigit() else str(x).upper())

    # 브로커
    try: broker = mojito.KoreaInvestment(
        api_key=st.secrets["kis"]["app_key"], api_secret=st.secrets["kis"]["app_secret"],
        acc_no=st.secrets["kis"]["acc_no"], mock=True)
    except: broker = None

    results = [None]*len(df_raw)

    def worker(idx, row):
        try:
            code = str(row.get('종목코드','')).strip()
            cat = str(row.get('분류','국내')).strip()
            name = str(row.get('종목명','')).strip()
            
            # 가격
            price = get_safe_price(broker, code, cat)
            
            # 값 읽기
            auto = float(row.get('연배당금_크롤링_auto',0))
            man = float(row.get('연배당금',0))
            old = float(row.get('연배당금_크롤링',0))
            ttm_saved = float(row.get('TTM_연배당률(크롤링)',0))
            
            final_div, final_yield, msg = 0, 0, ""
            
            # 1순위: Auto (최신 크롤링값)
            if auto > 0:
                final_div = auto
                if price>0: final_yield = (auto/price)*100
                msg = "⚡ Auto"
            # 2순위: TTM (API 계산값)
            elif ttm_saved > 0:
                final_yield = ttm_saved
                if price>0: final_div = int(price*(ttm_saved/100))
                msg = f"✅ API계산({ttm_saved}%)"
            # 3순위: 수동
            elif man > 0:
                final_div = man
                if price>0: final_yield = (man/price)*100
                msg = "🔧 수동"
            # 4순위: Old
            elif old > 0:
                final_div = old
                if price>0: final_yield = (old/price)*100
                msg = "⚠️ Old"
            else:
                msg = "❌ 갱신필요"
            
            # 신규상장 보정
            months = int(row.get('신규상장개월수', 0))
            if 0 < months < 12 and "수동" in msg:
                final_div = (man/months)*12
                if price>0: final_yield = (final_div/price)*100
                name += " ⭐"

            p_str = f"{int(price):,}원" if cat=='국내' else f"${price:.2f}"
            
            return idx, {
                '코드': code, '종목명': name, '현재가': p_str, '연배당률': round(final_yield,2),
                '배당락일': str(row.get('배당락일','-')), '분류': cat, '유형': str(row.get('유형','-')),
                '자산유형': classify_asset(row), '환구분': get_hedge_status(name, cat),
                '비고': msg, '블로그링크': str(row.get('블로그링크','#')), 
                '배당기록': str(row.get('배당기록','')), '검색라벨': str(row.get('검색라벨','')),
                '신규상장개월수': months, '캘린더링크': None, '금융링크': '#', 'pure_name': name,
                # 보존용
                '연배당금_크롤링_auto': auto, '연배당금': man, '연배당금_크롤링': old, 'TTM_연배당률(크롤링)': ttm_saved
            }
        except: return idx, None

    with ThreadPoolExecutor(max_workers=10) as exe:
        futures = {exe.submit(worker, i, r): i for i,r in df_raw.iterrows()}
        for f in as_completed(futures):
            i, res = f.result()
            results[i] = res
            
    final = [r for r in results if r]
    if final:
        return pd.DataFrame(final).sort_values('연배당률', ascending=False)
    return pd.DataFrame()

# -----------------------------------------------------------
# [SECTION 4] 파일/DB 관리
# -----------------------------------------------------------
@st.cache_data(ttl=1800)
def load_stock_data_from_csv():
    path = "stocks.csv"
    for _ in range(3):
        try:
            if not os.path.exists(path): return pd.DataFrame()
            df = pd.read_csv(path, dtype=str, encoding='utf-8-sig')
            df.columns = [c.replace('\ufeff','').strip() for c in df.columns]
            # 필수컬럼 보장
            for c in ['연배당금_크롤링','연배당금_크롤링_auto','연배당률_크롤링','TTM_연배당률(크롤링)']:
                if c not in df.columns: df[c] = 0.0
            if '종목코드' not in df.columns: df['종목코드'] = df.index.astype(str)
            df['종목코드'] = df['종목코드'].apply(lambda x: str(x).split('.')[0].strip().zfill(6) if str(x).isdigit() else str(x).upper())
            return df
        except: time.sleep(0.5)
    return pd.DataFrame()

def save_to_github(df):
    try:
        g = Github(st.secrets["github"]["token"])
        repo = g.get_repo(st.secrets["github"]["repo_name"])
        contents = repo.get_contents(st.secrets["github"]["file_path"])
        repo.update_file(contents.path, "Update", df.to_csv(index=False).encode("utf-8"), contents.sha)
        return True, "저장 완료"
    except: return False, "저장 실패"

def reset_auto_data(code):
    try:
        df = load_stock_data_from_csv()
        idx = df[df['종목코드']==code].index
        if not idx.empty:
            df.at[idx[0], '연배당금_크롤링_auto'] = 0.0
            df.to_csv("stocks.csv", index=False, encoding='utf-8-sig')
            return True, "초기화 완료"
        return False, "없음"
    except Exception as e: return False, str(e)

# -----------------------------------------------------------
# [SECTION 6] 핵심 갱신 로직 (국내/해외/TTM 통합)
# -----------------------------------------------------------

def fetch_dividend_yield_hybrid(code, category):
    """
    [복구됨] 국내 종목의 '최신 배당금(Auto)' 조회 기능을 복구했습니다.
    """
    code = str(code).strip()
    
    if category == '국내':
        # 1. API로 최신 배당금 조회 (requests 사용)
        try:
            url = f"https://m.stock.naver.com/api/etf/{code}/dividend/history?pageSize=1"
            res = requests.get(url, timeout=3, headers={"User-Agent":"Mozilla/5.0"})
            if res.status_code == 200:
                data = res.json()
                items = data.get('result', {}).get('items', [])
                if items:
                    amt = items[0].get('dividendAmount') or items[0].get('amount') or 0
                    amt = float(str(amt).replace(',', ''))
                    
                    if amt > 0:
                        # 현재가 조회
                        price = _fetch_naver_price(code)
                        if price > 0:
                            yield_val = (amt * 12) / price * 100
                            return round(yield_val, 2), f"✅ 실시간({int(amt)}원)"
        except:
            pass
        return 0.0, "⚠️ 조회 실패"

    else:
        # 해외 (기존 유지)
        try:
            tk = yf.Ticker(code)
            divs = tk.dividends
            if not divs.empty:
                cut = pd.Timestamp.now(tz=divs.index.tz) - pd.Timedelta(days=365)
                usd = float(divs[divs.index >= cut].sum())
                p = tk.fast_info.get('last_price')
                if not p:
                    h = tk.history(period='1d')
                    if not h.empty: p = h['Close'].iloc[-1]
                if p and p > 0:
                    y = (usd/p)*100
                    return round(y, 2), f"✅ 야후(${usd:.2f})"
        except: pass
        return 0.0, "⚠️ 데이터 없음"

def smart_update_and_save():
    """
    [스마트 갱신] Auto(1순위)와 TTM(2순위) 모두 챙기는 완벽한 로직
    """
    try:
        df = load_stock_data_from_csv()
        if df.empty: return False, "파일 없음"
        
        cnt = 0
        skip = 0
        pbar = st.progress(0)
        stext = st.empty()
        total = len(df)
        
        # 브라우저 설치 시도 (백그라운드)
        try: _ensure_browser_installed()
        except: pass

        for i, row in df.iterrows():
            code = str(row['종목코드']).strip()
            name = str(row['종목명']).strip()
            cat = str(row.get('분류', '국내')).strip()
            
            pbar.progress((i+1)/total)
            stext.text(f"갱신 중: {name} ({i+1}/{total})")
            
            try: mon = int(row.get('신규상장개월수',0))
            except: mon = 0
            if 0 < mon < 12: 
                skip+=1
                continue

            def tf(v): 
                try: return float(v)
                except: return 0.0
            
            curr_auto = tf(row.get('연배당금_크롤링_auto', 0))
            curr_man = tf(row.get('연배당금', 0))
            is_locked = (curr_man > 0) and (curr_auto == 0) # 수동O, AutoX = 잠금
            
            # [1] Auto 갱신 (잠금 아니면 실행)
            if not is_locked:
                try:
                    # 복구된 함수 호출!
                    y_val, msg = fetch_dividend_yield_hybrid(code, cat)
                    if y_val > 0:
                        df.at[i, '연배당률_크롤링'] = y_val
                        # 금액 파싱
                        if cat == '국내':
                            import re
                            m = re.search(r'\(([\d,\.]+)원\)', msg)
                            if m: 
                                val = int(m.group(1).replace(',', ''))
                                df.at[i, '연배당금_크롤링_auto'] = float(val) * 12
                        else:
                            import re
                            m = re.search(r'\$([\d\.]+)', msg)
                            if m: df.at[i, '연배당금_크롤링_auto'] = float(m.group(1))
                        
                        cnt += 1
                except: pass
            
            # [2] TTM 갱신 (Auto가 0이거나 실패했으면 무조건 실행)
            # 수동 잠금 상태라도 TTM 정보는 업데이트해 둠 (참고용)
            check_auto = tf(df.at[i, '연배당금_크롤링_auto'])
            
            if check_auto == 0 or is_locked:
                if cat == '국내':
                    try:
                        # API 계산기 호출 (필살기)
                        ttm, _ = get_ttm_or_calculate(code)
                        if ttm > 0:
                            df.at[i, 'TTM_연배당률(크롤링)'] = float(ttm)
                            # 잠금 상태에서도 TTM 갱신 성공하면 카운트 인정
                            if is_locked: cnt += 1
                    except: pass

        df.to_csv("stocks.csv", index=False, encoding='utf-8-sig')
        if "github" in st.secrets: save_to_github(df)
        
        stext.empty()
        pbar.empty()
        return True, f"✅ 완료! (갱신: {cnt}, 스킵: {skip})"
        
    except Exception as e: return False, f"에러: {e}"

def update_dividend_rolling(h_str, val):
    try: h = [int(float(x)) for x in str(h_str).split('|') if x.strip()]
    except: h = []
    if len(h)>=12: h.pop(0)
    h.append(int(val))
    return sum(h), "|".join(map(str, h))
