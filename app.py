import streamlit as st
import pandas as pd
import requests
from bs4 import BeautifulSoup
import yfinance as yf
import FinanceDataReader as fdr
from datetime import datetime
import pytz
import altair as alt
import os

# [1] 페이지 설정
st.set_page_config(page_title="배당팽이 대시보드", layout="wide")

# [2] 데이터 로드 함수
def load_stock_data_from_csv():
    possible_paths = ['stocks.csv', '/content/stocks.csv']
    file_path = None
    for path in possible_paths:
        if os.path.exists(path):
            file_path = path
            break
            
    if file_path:
        try:
            df = pd.read_csv(file_path, dtype={'종목코드': str})
            return df
        except Exception as e:
            st.error(f"⚠️ 파일을 읽는 중 오류가 발생했습니다: {e}")
            return pd.DataFrame()
    else:
        st.error("⚠️ 'stocks.csv' 파일을 찾을 수 없습니다. 깃허브에 파일이 잘 올라갔는지 확인해주세요!")
        return pd.DataFrame()

# [3] 유틸리티 함수
def get_safe_price(code, category):
    if category == '해외':
        try: return yf.Ticker(code).fast_info['last_price']
        except: return None
    try:
        url = f"https://finance.naver.com/item/main.naver?code={code}"
        res = requests.get(url, headers={'User-Agent': 'Mozilla/5.0'}, timeout=2)
        soup = BeautifulSoup(res.text, 'html.parser')
        no_today = soup.select_one(".no_today .blind")
        if no_today: return int(no_today.text.replace(",", ""))
    except: pass
    try:
        df = fdr.DataReader(code)
        if not df.empty: return int(df['Close'].iloc[-1])
    except: pass
    return None

def get_hedge_status(code, name, category):
    if category == '해외': return "💲달러자산"
    if code == '481060': return "🛡️환헤지(H)"
    if any(x in name for x in ['미국', 'Global', '국제', 'S&P', 'NASDAQ', '하이일드']): return "⚡환노출"
    return "-"

@st.cache_data(ttl=300, show_spinner=False)
def load_and_process_data(df_raw):
    results = []
    for index, row in df_raw.iterrows():
        try:
            code = row['종목코드']
            name = row['종목명']
            raw_div = float(row['연배당금'])
            category = row['분류']
            blog_url = row['블로그링크']
            ex_date = row['배당락일']
            months = int(row['신규상장개월수']) if pd.notna(row['신규상장개월수']) else 0

            price = get_safe_price(code, category)
            
            if price:
                if months > 0:
                    annual_div = (raw_div / months) * 12
                    name_display = f"{name} ⭐(신규)"
                else:
                    annual_div = raw_div
                    name_display = name
                
                if category == '국내':
                    if '초단기국채' in name and price < 5000: price = 9970
                    div_yield = (annual_div / price) * 100
                    price_disp = f"{price:,}원"
                    link_url = f"https://finance.naver.com/item/main.naver?code={code}"
                else:
                    div_yield = (annual_div / price) * 100 
                    price_disp = f"${price:.2f}"
                    link_url = f"https://finance.yahoo.com/quote/{code}"
                
                hedge_status = get_hedge_status(code, name, category)
                
                results.append({
                    '종목코드': code, '종목명': name_display, '현재가': price_disp,
                    '연배당률': div_yield, '환헤지': hedge_status, '배당락일': ex_date,
                    '공식홈': link_url, '블로그': blog_url, '분류': category, 'raw_price': price
                })
            else:
                results.append({
                    '종목코드': code, '종목명': f"{name} (점검중)", '현재가': "-", 
                    '연배당률': 0.0, '환헤지': "-", '배당락일': "-", 
                    '공식홈': "", '블로그': "", '분류': category, 'raw_price': 0
                })
        except Exception as e:
            continue
            
    return pd.DataFrame(results).sort_values(by='연배당률', ascending=False)

def main():
    df_raw = load_stock_data_from_csv()
    if df_raw.empty:
        st.stop()

    total_count = len(df_raw)
    st.title(f"💰 배당팽이의 실시간 연배당률 대시보드 (총 {total_count}종 분석 중)")
    
    # [상단 면책 조항]
    st.warning("""
        ⚠️ **투자 유의사항:** 본 대시보드의 연배당률은 과거 분배금 데이터를 기반으로 계산된 참고용 지표입니다. 
        실제 배당금은 운용사의 사정 및 시장 상황에 따라 매월 변동될 수 있습니다.
    """)
    st.info("💡 팁: 표의 맨 윗줄(헤더)을 클릭하면 '오름차순/내림차순' 정렬이 가능합니다!")
    
    korea_tz = pytz.timezone('Asia/Seoul')
    now_kst = datetime.now(korea_tz).strftime('%H:%M')
    
    with st.spinner('⚙️ 배당 데이터베이스 엔진 가동 중... 실시간 시세를 연동하고 있습니다.'):
        df = load_and_process_data(df_raw)

    # --- 포트폴리오 계산기 ---
    with st.expander("🧮 나만의 배당 포트폴리오 만들기 (클릭)", expanded=False):
        col_input1, col_input2 = st.columns([1, 2])
        with col_input1:
            total_invest = st.number_input("💰 총 투자 금액 (만원)", min_value=100, value=3000, step=100) * 10000
        with col_input2:
            selected_stocks = st.multiselect("📊 종목 선택", df['종목명'].unique(), placeholder="종목을 선택하거나 검색하세요...")
        
        if selected_stocks:
            has_foreign_stock = any(df[df['종목명'] == s_name].iloc[0]['분류'] == '해외' for s_name in selected_stocks)
            if has_foreign_stock:
                st.warning("📢 **잠깐!** 선택하신 종목 중 **'해외 상장 ETF'**가 포함되어 있습니다. ISA/연금계좌 결과는 참고용으로만 봐주세요.")

            st.markdown("---")
            st.markdown("#### ⚖️ 종목별 비중 조절")
            
            weights = {}
            remaining = 100
            cols_weight = st.columns(2)
            
            for i, stock in enumerate(selected_stocks):
                with cols_weight[i % 2]:
                    if i < len(selected_stocks) - 1:
                        val = st.number_input(f"{stock} (%)", min_value=0, max_value=remaining, value=min(int(100/len(selected_stocks)), remaining), step=5, key=f"input_{stock}")
                        weights[stock] = val
                        remaining -= val
                    else:
                        st.write(f"**{stock} (%)**")
                        st.info(f"남은 비중 {remaining}% 자동 적용")
                        weights[stock] = remaining

            total_monthly_income = 0
            avg_yield_sum = 0
            
            for stock_name, weight_percent in weights.items():
                row = df[df['종목명'] == stock_name].iloc[0]
                price = row['raw_price']
                yield_rate = row['연배당률']
                
                if price > 0:
                    allocated_money = total_invest * (weight_percent / 100)
                    annual_income = allocated_money * (yield_rate / 100)
                    total_monthly_income += (annual_income / 12)
                    avg_yield_sum += (yield_rate * weight_percent)
            
            final_portfolio_yield = avg_yield_sum / 100
            final_general = total_monthly_income * (1 - 0.154)
            final_isa = total_monthly_income
            
           # --- [통합 경고 및 면책 조항 섹션] ---
            st.divider() # 결과와 경고 사이를 구분하는 선
            
            # 1. 금융소득종합과세 경고 (조건부 노출)
            annual_pretax_income = total_monthly_income * 12
            if annual_pretax_income > 20000000:
                 st.error(f"""
                    🚨 **금융소득종합과세 주의! (연 배당 2천만원 초과)**
                    예상 연 배당금(세전)이 **{annual_pretax_income/10000:,.0f}만원**으로 계산되었습니다. 
                    연간 금융소득이 2,000만원을 초과할 경우, 초과분은 타 소득과 합산되어 누진세율이 적용될 수 있으니 절세 전략(ISA 등)을 반드시 검토하시기 바랍니다.
                """)

            # 2. 투자 면책 조항 (항상 노출 - 2단 구성)
            warn_col1, warn_col2 = st.columns(2)
            with warn_col1:
                st.warning("""
                    **⚠️ 1. 과거 데이터 기반 안내**
                    위 시뮬레이션은 과거 분배금 데이터를 바탕으로 산출되었습니다. 실제 배당금은 운용사의 공시 내용 및 환율 변동에 따라 매월 달라질 수 있습니다.
                """)
            with warn_col2:
                st.error("""
                    **🚨 2. 원금 손실 및 투자 책임**
                    모든 투자는 **원금 손실의 위험**이 수반됩니다. 본 결과는 참고용이며, 최종 투자 결정은 반드시 **본인의 판단과 책임**하에 신중히 진행하시기 바랍니다.
                """)
            # --------------------------------------------

            st.divider()
            st.metric("📈 가중 평균 연배당률", f"{final_portfolio_yield:.2f}%")
            
            col_res1, col_res2, col_res3 = st.columns([1, 1, 1.5])
            with col_res1:
                st.metric("월 수령액 (세후)", f"{final_general:,.0f}원", delta="-15.4%", delta_color="inverse")
            with col_res2:
                st.metric("월 수령액 (ISA/세전)", f"{final_isa:,.0f}원", delta="100%", delta_color="normal")
            with col_res3:
                st.success(f"나만의 맞춤 비중으로\n\n**월 {final_isa:,.0f}원** 완성! 🎉")

            chart_data = pd.DataFrame({'계좌 종류': ['일반 계좌', 'ISA/연금'], '월 수령액': [final_general, final_isa]})
            c = alt.Chart(chart_data).mark_bar().encode(
                x=alt.X('계좌 종류', sort=None), y='월 수령액',
                color=alt.Color('계좌 종류', scale=alt.Scale(domain=['일반 계좌', 'ISA/연금'], range=['#95a5a6', '#f1c40f'])),
                tooltip=['계좌 종류', alt.Tooltip('월 수령액', format=',.0f')]
            ).properties(height=200)
            st.altair_chart(c, width='stretch')
        else:
            st.info("👆 위에서 종목을 선택하시면 비중 조절 칸이 나타납니다.")

    # --- 테이블 출력 ---
    column_config = {
        "블로그": st.column_config.LinkColumn("분석글", display_text="📝포스팅 보기", width=100),
        "종목코드": st.column_config.TextColumn("코드", width=50),
        "종목명": st.column_config.TextColumn("종목명", width=120),
        "현재가": st.column_config.TextColumn("현재가", width=70),
        "연배당률": st.column_config.NumberColumn("연배당률", format="%.2f%%", width=70),
        "공식홈": st.column_config.LinkColumn("네이버/야후", display_text="🔗정보", width=60)
    }
    cols_table = ['블로그', '종목코드', '종목명', '현재가', '연배당률', '환헤지', '배당락일', '공식홈']
    
    tab1, tab2, tab3 = st.tabs(["🌐 전체", "🇰🇷 국내", "🇺🇸 해외"])
    with tab1:
        st.write(f"### 🔥 통합 랭킹 ({now_kst} 기준)")
        st.dataframe(df[cols_table], column_config=column_config, width='stretch', hide_index=True)
    with tab2:
        st.dataframe(df[df['분류']=='국내'][cols_table], column_config=column_config, width='stretch', hide_index=True)
    with tab3:
        st.dataframe(df[df['분류']=='해외'][cols_table], column_config=column_config, width='stretch', hide_index=True)

    # --- 하단 서명 및 방문자 수 ---
    st.markdown("---")
    col_footer1, col_footer2 = st.columns([3, 1])
    with col_footer1:
        st.caption("© 2025 **배당팽이** | 실시간 데이터 기반 배당 대시보드")
        st.caption("First Released: 2025.12.31 | [배당팽이의 배당 투자 일지](https://blog.naver.com/dividenpange)")
    with col_footer2:
        st.markdown(
            f"""
            <div style="text-align: right;">
                <span style="color: grey; font-size: 0.8rem;">오늘의 방문자 : </span>
                <a href="https://hits.seeyoufarm.com">
                    <img src="https://hits.seeyoufarm.com/api/count/incr/badge.svg?url=https%3A%2F%2Fdividend-pange.streamlit.app&count_bg=%23999999&title_bg=%23999999&icon=&icon_color=%23E7E7E7&title=HIT&edge_flat=false" alt="Hits">
                </a>
            </div>
            """,
            unsafe_allow_html=True
        )

if __name__ == "__main__":
    main()

