import streamlit as st
from supabase import create_client
import pandas as pd
import requests
from bs4 import BeautifulSoup
import yfinance as yf
from datetime import datetime
import pytz
import altair as alt

# [1] 페이지 설정
st.set_page_config(page_title="배당팽이 대시보드", layout="wide")

# [2] Supabase 연결 설정 (보안 적용)
URL = st.secrets["SUPABASE_URL"]
KEY = st.secrets["SUPABASE_KEY"]
supabase = create_client(URL, KEY)

# [3] 데이터 로드 및 처리 함수
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
            
    st.error("❌ 데이터를 불러오지 못했습니다. 잠시 후 다시 시도해주세요.")
    return pd.DataFrame()

@st.cache_data(ttl=300)
def get_safe_price(code, category):
    try:
        code_str = str(code).strip()
        if category == '해외':
            ticker = yf.Ticker(code_str)
            price = ticker.fast_info.get('last_price')
            if not price:
                price = ticker.history(period="1d")['Close'].iloc[-1]
            return float(price) if price else None
            
        url = f"https://finance.naver.com/item/main.naver?code={code_str}"
        res = requests.get(url, headers={'User-Agent': 'Mozilla/5.0'}, timeout=3)
        soup = BeautifulSoup(res.text, 'html.parser')
        no_today = soup.select_one(".no_today .blind")
        return int(no_today.text.replace(",", "")) if no_today else None

    except Exception:
        return None

def classify_asset(row):
    name = str(row.get('종목명', '')).upper()
    symbol = str(row.get('종목코드', '')).upper()
    covered = ['커버드콜', 'COVERED CALL', '프리미엄', 'PREMIUM', '+10%', '옵션', 'OPTION', 'QYLD', 'JEPI', 'JEPQ', 'XYLD', 'RYLD', 'NVDY', 'TSLY', 'CONY', 'MSTY', 'ULTRA', 'QQQI', 'GPIQ', 'XYLG', 'QYLG', 'TLTW', 'SVOL']
    bond = ['채권', '국채', 'BOND', '단기채', 'TREASURY', '하이일드', 'HIGH YIELD', 'PFF', '국제금', '골드', 'GOLD', 'BIL', 'SHV', 'T-BILL', 'SGOV', 'TLT']
    
    if any(k in name for k in covered) or any(k in symbol for k in covered): return '🛡️ 커버드콜'
    if '혼합' in name: return '⚖️ 혼합형'
    if any(k in name for k in bond) or any(k in symbol for k in bond): return '🏦 채권형'
    if any(k in name for k in ['리츠', 'REITS', '부동산']): return '🏢 리츠형'
    return '📈 주식형'

def get_hedge_status(name, category):
    name_str = str(name).upper()
    if category == '해외': return "💲달러(직투)"
    if "환노출" in name_str or "UNHEDGED" in name_str: return "⚡환노출"
    if any(x in name_str for x in ["(H)", "헤지", "합성"]): return "🛡️환헤지(H)"
    if any(x in name_str for x in ['미국', 'GLOBAL', 'S&P500', '나스닥', '빅테크', '국제금', '골드', 'GOLD']): return "⚡환노출"
    return "-"

@st.cache_data(ttl=300, show_spinner=False)
def load_and_process_data(df_raw, is_admin=False):
    results = []
    if df_raw.empty: return pd.DataFrame()
    
    for _, row in df_raw.iterrows():
        code = str(row.get('종목코드', '')).strip()
        name = str(row.get('종목명', '')).strip()
        category = str(row.get('분류', '국내')).strip()
        price = get_safe_price(code, category)
        
        if price:
            raw_div = float(row.get('연배당금', 0))
            months = int(row.get('신규상장개월수', 0))
            annual_div = (raw_div / months * 12) if months > 0 else raw_div
            yield_val = (annual_div / price) * 100

            # [🚨 스마트 필터링 로직 통합]
            if not is_admin:
                if yield_val < 2.0 or yield_val > 25.0:
                    continue  # 일반인은 필터링
            else:
                if yield_val < 2.0 or yield_val > 25.0:
                    name = f"🚫 {name} (필터됨)" 

            price_display = f"{int(price):,}원" if category == '국내' else f"${price:.2f}"
            
            results.append({
                '코드': code, '종목명': f"{name} ⭐" if months > 0 else name,
                '블로그링크': str(row.get('블로그링크', '#')),
                '금융링크': f"https://finance.naver.com/item/main.naver?code={code}" if category == '국내' else f"https://finance.yahoo.com/quote/{code}",
                '현재가': price_display, '연배당률': yield_val,
                '환구분': get_hedge_status(name, category),
                '배당락일': str(row.get('배당락일', '-')), '분류': category,
                '자산유형': classify_asset(row), 'pure_name': name.replace("🚫 ", "").replace(" (필터됨)", ""),
                '신규상장개월수': months 
            })
            
    return pd.DataFrame(results).sort_values('연배당률', ascending=False)

def main():
    st.title("💰 배당팽이 실시간 연배당률 대시보드")

    # 1. 데이터 로드 (생 로우 데이터)
    df_raw = load_stock_data_from_csv()
    if df_raw.empty: st.stop()

    with st.spinner('⚙️ 배당 데이터베이스 엔진 가동 중...'):
        # 2. 관리자 여부 확인
        is_admin = st.query_params.get("admin", "false").lower() == "true"
        
        # 3. 데이터 처리 및 필터링 (is_admin을 넘겨서 내부에서 처리하게 함)
        df = load_and_process_data(df_raw, is_admin=is_admin)
        
        if is_admin:
            st.sidebar.success("관리자 모드로 접속 중입니다 (모든 종목 표시)")

    if df.empty:
        st.info("표시할 종목이 없습니다.")
        st.stop()

    st.warning("⚠️ **투자 유의사항:** 본 대시보드의 연배당률은 과거 분배금 데이터를 기반으로 계산된 참고용 지표입니다.")

    # --- [시뮬레이션 및 테이블 출력 로직 시작] ---
    with st.expander("🧮 나만의 배당 포트폴리오 시뮬레이션", expanded=True):
        col1, col2 = st.columns([1, 2])
        total_invest = col1.number_input("💰 총 투자 금액 (만원)", min_value=100, value=3000, step=100) * 10000
        selected = col2.multiselect("📊 종목 선택", df['pure_name'].unique())

        if selected:
            # 시뮬레이션 계산 로직...
            all_data = []; weights = {}; remaining = 100
            cols_w = st.columns(2)
            for i, stock in enumerate(selected):
                with cols_w[i % 2]:
                    if i < len(selected) - 1:
                        val = st.number_input(f"{stock} (%)", min_value=0, max_value=remaining, value=min(remaining, 100 // len(selected)), step=5, key=f"s_{i}")
                        weights[stock] = val
                        remaining -= val
                    else:
                        st.info(f"{stock}: {remaining}% 자동 적용")
                        weights[stock] = remaining
                    
                    amt = total_invest * (weights[stock] / 100)
                    s_row = df[df['pure_name'] == stock].iloc[0]
                    all_data.append({'종목': stock, '비중': weights[stock], '자산유형': s_row['자산유형'], '투자금액_만원': amt / 10000})

            # 결과 리포트
            total_y_div = sum([(total_invest * (weights[n]/100) * (df[df['pure_name']==n].iloc[0]['연배당률']/100)) for n in selected])
            total_m = total_y_div / 12
            avg_y = sum([(df[df['pure_name']==n].iloc[0]['연배당률'] * (weights[n]/100)) for n in selected])

            st.markdown("### 🎯 포트폴리오 결과")
            st.metric("📈 가중 평균 연배당률", f"{avg_y:.2f}%")
            r1, r2, r3 = st.columns(3)
            r1.metric("월 수령액 (세후)", f"{total_m * 0.846:,.0f}원", delta="-15.4%", delta_color="inverse")
            r2.metric("월 수령액 (ISA/세전)", f"{total_m:,.0f}원", delta="100%", delta_color="normal")
            with r3:
                st.markdown(f'<div style="background-color:#d4edda;padding:15px;border-radius:8px;border:1px solid #c3e6cb;"><b>✅ 일반 계좌 대비 월 {total_m*0.154:,.0f}원 이득!</b><br><small>(비과세 가정)</small></div>', unsafe_allow_html=True)

            res_tab1, res_tab2 = st.tabs(["📊 월 배당금 비교", "💎 포트폴리오 자산 구성"])
            with res_tab1:
                c_data = pd.DataFrame({'계좌 종류': ['일반 계좌', 'ISA/연금'], '월 수령액': [total_m * 0.846, total_m]})
                chart = alt.Chart(c_data).mark_bar().encode(x='계좌 종류', y='월 수령액', color='계좌 종류').properties(height=300)
                st.altair_chart(chart, use_container_width=True)
            with res_tab2:
                df_ana = pd.DataFrame(all_data)
                asset_sum = df_ana.groupby('자산유형').agg({'비중':'sum', '투자금액_만원':'sum', '종목': lambda x: ', '.join(x)}).reset_index()
                st.dataframe(asset_sum, hide_index=True, use_container_width=True)

    # 테이블 출력 함수 및 탭
    def render_custom_table(data_frame):
        html_rows = []
        for _, row in data_frame.iterrows():
            blog_link = str(row.get('블로그링크', 'https://blog.naver.com/dividenpange'))
            b_link = f"<a href='{blog_link}' target='_blank' style='color:#0068c9;text-decoration:none;font-weight:bold;'>{row['코드']}</a>"
            yield_display = f"<span style='color:{'#ff4b4b' if row['연배당률']>=10 else '#333'}; font-weight:bold;'>{row['연배당률']:.2f}%</span>"
            f_link = f"<a href='{row['금융링크']}' target='_blank' style='color:#0068c9;text-decoration:none;'>🔗정보</a>"
            html_rows.append(f"<tr><td>{b_link}</td><td style='text-align:left;'>{row['종목명']}</td><td>{row['현재가']}</td><td>{yield_display}</td><td>{row['환구분']}</td><td>{row['배당락일']}</td><td>{f_link}</td></tr>")
        
        st.markdown(f"<table><thead><tr><th>코드</th><th>종목명</th><th>현재가</th><th>연배당률</th><th>환구분</th><th>배당락일</th><th>링크</th></tr></thead><tbody>{''.join(html_rows)}</tbody></table>", unsafe_allow_html=True)

    tab_all, tab_kor, tab_usa = st.tabs(["🌎 전체", "🇰🇷 국내", "🇺🇸 해외"])
    with tab_all: render_custom_table(df)
    with tab_kor: render_custom_table(df[df['분류'] == '국내'])
    with tab_usa: render_custom_table(df[df['분류'] == '해외'])

    # --- 방문자 카운트 및 관리자 로그 ---
    st.divider()
    if 'visited' not in st.session_state: st.session_state.visited = False
    if not st.session_state.visited:
        try:
            if not is_admin:
                supabase.table("visit_logs").insert({"referer": "Direct"}).execute()
                res = supabase.table("visit_counts").select("count").eq("id", 1).execute()
                if res.data:
                    new_count = res.data[0]['count'] + 1
                    supabase.table("visit_counts").update({"count": new_count}).eq("id", 1).execute()
                    st.session_state.display_count = new_count
            else:
                res = supabase.table("visit_counts").select("count").eq("id", 1).execute()
                st.session_state.display_count = res.data[0]['count'] if res.data else "Admin"
            st.session_state.visited = True
        except: st.session_state.display_count = "확인 중"; st.session_state.visited = True

    st.write(f"누적 방문자: {st.session_state.get('display_count', '집계 중')}")

    if is_admin:
        with st.expander("🛠️ 관리자 전용 로그"):
            try:
                logs = supabase.table("visit_logs").select("*").order("created_at", desc=True).limit(5).execute()
                st.table(pd.DataFrame(logs.data))
            except: st.error("로그 로드 실패")

if __name__ == "__main__":
    main()
