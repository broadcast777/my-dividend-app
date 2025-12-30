import streamlit as st
import pandas as pd
import requests
from bs4 import BeautifulSoup
import yfinance as yf
import FinanceDataReader as fdr
from datetime import datetime
import time
import pytz
import altair as alt

# [1] 페이지 설정
st.set_page_config(page_title="배당팽이 대시보드", layout="wide")

# [2] 데이터베이스
STOCKS_DATA = {
    # --- 국내 ETF ---
    '476800': ['KODEX 한국부동산리츠인프라', 422, '국내', 'https://blog.naver.com/dividenpange/224071556339', '매월 15일(영업일 기준)', 0],
    '329200': ['TIGER 부동산리츠인프라', 379, '국내', 'https://blog.naver.com/dividenpange/224081483734', '매월 마지막영업일', 0],
    '0052D0': ['TIGER 코리아배당다우존스', 293, '국내', 'https://blog.naver.com/dividenpange/224074046441', '매월 15일(영업일 기준)', 6],
    '441640': ['KODEX 미국배당커버드콜액티브', 1130, '국내', 'https://blog.naver.com/dividenpange/224072761806', '매월 15일(영업일 기준)', 0],
    '0105E0': ['SOL 코리아고배당', 156, '국내', 'https://blog.naver.com/dividenpange/224081486301', '매월 15일(영업일 기준)', 2],
    '279530': ['KODEX 고배당주', 628, '국내', 'https://blog.naver.com/dividenpange/224109514837', '매월 마지막영업일', 0],
    '498400': ['KODEX 200타겟위클리커버드콜', 1954, '국내', 'https://blog.naver.com/dividenpange/224084682629', '매월 15일(영업일 기준)', 0],
    '468380': ['KODEX iShares 미국하이일드액티브', 750, '국내', 'https://blog.naver.com/dividenpange/224092022168', '매월 마지막영업일', 0],
    '0086B0': ['TIGER 리츠부동산인프라TOP10액티브', 216, '국내', 'https://blog.naver.com/dividenpange/224084731534', '매월 15일(영업일 기준)', 4],
    '161510': ['PLUS 고배당주', 866, '국내', 'https://blog.naver.com/dividenpange/224097267562', '매월 마지막영업일', 0],
    '481060': ['KODEX 미국30년국채타겟커버드콜', 1063, '국내', 'https://blog.naver.com/dividenpange/224116572356', '매월 15일(영업일 기준)', 0],
    '484880': ['SOL 금융지주플러스고배당', 720, '국내', 'https://blog.naver.com/dividenpange/224093074417', '매월 마지막영업일', 0],
    '0046A0': ['TIGER 미국초단기(3개월이하)국채', 121, '국내', 'https://blog.naver.com/dividenpange/224106519426', '매월 마지막영업일', 4],
    '480020': ['ACE 미국빅테크7+데일리타겟커버드콜', 1712, '국내', 'https://blog.naver.com/dividenpange/224101062938', '매월 15일(영업일 기준)', 0],
    '489250': ['KODEX 미국배당다우존스', 355, '국내', 'https://blog.naver.com/dividenpange/224094660299', '매월 15일(영업일 기준)', 0],
    '458730': ['TIGER 미국배당다우존스', 430, '국내', 'https://blog.naver.com/dividenpange/224094660299', '매월 마지막영업일', 0],
    '498410': ['KODEX 금융고배당TOP10타겟위클리', 1774, '국내', 'https://blog.naver.com/dividenpange/224093577682', '매월 마지막영업일', 0],
    '476760': ['ACE 미국30년국채액티브', 368, '국내', 'https://blog.naver.com/dividenpange/224092374735', '매월 마지막영업일', 0],
    '491620': ['RISE 미국테크100데일리고정커버드콜', 2148, '국내', 'https://blog.naver.com/dividenpange/224092460024', '매월 마지막영업일', 0],
    '466940': ['TIGER 은행고배당플러스TOP10', 917, '국내', 'https://blog.naver.com/dividenpange/224093074417', '매월 마지막영업일', 0],
    '482730': ['TIGER 미국S&P500타겟데일리커버드콜', 1115, '국내', 'https://blog.naver.com/dividenpange/224095987359', '매월 마지막영업일', 0],
    '441800': ['TIMEFOLIO Korea플러스배당액티브', 1305, '국내', 'https://blog.naver.com/dividenpange/224112258378', '매월 마지막영업일', 0],
    '475720': ['RISE 200위클리커버드콜', 1676, '국내', 'https://blog.naver.com/dividenpange/224112140265', '매월 마지막영업일', 0],
    '0022T0': ['SOL 국제금커버드콜액티브', 363, '국내', 'https://blog.naver.com/dividenpange/224117827502', '매월 마지막영업일', 9],
    
    # --- 해외 ETF ---
    'PFF': ['iShares Preferred and Income Securities ETF', 1.95, '해외', 'https://blog.naver.com/dividenpange/224091640816', '매월 초(1~3일 전후)', 0],
    'JEPI': ['JPMorgan Equity Premium Income ETF', 4.69, '해외', 'https://blog.naver.com/dividenpange/224095987359', '매월 초(불규칙)', 0],
    'QYLD': ['Global X NASDAQ 100 Covered Call ETF', 2.04, '해외', 'https://blog.naver.com/dividenpange/224109189806', '매월 하순(21~25일)', 0],
    'SGOV': ['iShares 0-3 Month Treasury Bond ETF', 4.12, '해외', 'https://blog.naver.com/dividenpange/224101325285', '매월 초(현지기준)', 0]
}

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
def load_and_process_data():
    results = []
    for code, info in STOCKS_DATA.items():
        name, raw_div, category, blog_url, ex_date, months = info
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
    return pd.DataFrame(results).sort_values(by='연배당률', ascending=False)

def main():
    st.title("💰 배당팽이의 실시간 연배당률 대시보드")
    st.warning("""
        ⚠️ **투자 유의사항:** 본 대시보드의 연배당률은 과거 분배금 데이터를 기반으로 계산된 참고용 지표입니다. 
        실제 배당금은 운용사의 사정 및 시장 상황에 따라 매월 변동될 수 있습니다. 
    """)
    st.info("💡 팁: 표의 맨 윗줄(헤더)을 클릭하면 '오름차순/내림차순' 정렬이 가능합니다!")
    korea_tz = pytz.timezone('Asia/Seoul')
    now_kst = datetime.now(korea_tz).strftime('%H:%M')
    with st.spinner('⏳ 최신 데이터를 분석하고 있습니다... (약 10초 소요)'):
        df = load_and_process_data()

    # --- 비중 조절형 포트폴리오 계산기 (최적화 버전) ---
    with st.expander("🧮 나만의 배당 포트폴리오 만들기 (클릭)", expanded=False):
      
        col_input1, col_input2 = st.columns([1, 2])
        with col_input1:
            total_invest = st.number_input("💰 총 투자 금액 (만원)", min_value=100, value=3000, step=100) * 10000
        with col_input2:
            selected_stocks = st.multiselect(
                "📊 종목 선택 (여러 개 담아보세요)", 
                df['종목명'].unique(),
                placeholder="종목을 선택하거나 검색하세요..."
            )
        
        if selected_stocks:
            has_foreign_stock = any(df[df['종목명'] == s_name].iloc[0]['분류'] == '해외' for s_name in selected_stocks)
            if has_foreign_stock:
                st.warning("📢 **잠깐!** 선택하신 종목 중 **'해외 상장 ETF'**가 포함되어 있습니다. ISA/연금계좌 결과는 참고용으로만 봐주세요.")

            st.markdown("---")
            st.markdown("#### ⚖️ 종목별 비중 조절")
            st.caption("💡 팁: 마지막 종목을 제외한 나머지 비중을 정하면, 마지막은 자동으로 계산됩니다.")

            weights = {}
            remaining = 100
            cols_weight = st.columns(2)
            
            for i, stock in enumerate(selected_stocks):
                with cols_weight[i % 2]:
                    if i < len(selected_stocks) - 1:
                        # 사용자가 조절하는 칸
                        val = st.number_input(
                            f"{stock} (%)", 
                            min_value=0, max_value=remaining, 
                            value=min(int(100/len(selected_stocks)), remaining),
                            step=5,
                            key=f"input_{stock}"
                        )
                        weights[stock] = val
                        remaining -= val
                    else:
                        # 마지막 종목은 자동 계산
                        st.write(f"**{stock} (%)**")
                        st.info(f"남은 비중 {remaining}% 자동 적용")
                        weights[stock] = remaining

            # 결과 계산
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

            st.divider()
            st.markdown(f"### 🎯 포트폴리오 결과")
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
            
            # 🔥 [여기에 배치!] 결과 바로 밑에 빨간색 경고창
            st.error("""
                **⚠️ 시뮬레이션 활용 시 유의사항**
                1. 본 결과는 현재 시점의 배당률을 바탕으로 한 **단순 계산값**입니다.
                2. 실제 배당금은 운용사의 공시 및 환율 상황에 따라 **매월 달라질 수 있습니다.**
                3. 본 도구는 투자 참고용이며, 최종 투자 결정은 **본인의 판단**하에 신중히 결정하시기 바랍니다.
            """)
        else:
            st.info("👆 위에서 종목을 선택하시면 비중 조절 칸이 나타납니다.")
         
    
    # --- [메인] 테이블 출력 ---
    column_config = {
        "종목코드": st.column_config.TextColumn("코드", width=50),
        "종목명": st.column_config.TextColumn("종목명", width=120),
        "현재가": st.column_config.TextColumn("현재가", width=70),
        "연배당률": st.column_config.NumberColumn("연배당률", format="%.2f%%", width=70),
        "환헤지": st.column_config.TextColumn("환헤지", width=50),
        "배당락일": st.column_config.TextColumn("배당락일", width=100),
        "공식홈": st.column_config.LinkColumn("네이버/야후", display_text="🔗정보", width=60),
        "블로그": st.column_config.LinkColumn("포스팅보기", display_text="📝보기", width=60)
    }

    cols_table = ['종목코드', '종목명', '현재가', '연배당률', '환헤지', '배당락일', '공식홈', '블로그']
    tab1, tab2, tab3 = st.tabs(["🌐 전체", "🇰🇷 국내", "🇺🇸 해외"])
    
    with tab1:
        st.write(f"### 🔥 통합 랭킹 ({now_kst} 기준)")
        st.dataframe(df[cols_table], column_config=column_config, width='stretch', hide_index=True)
    with tab2:
        st.dataframe(df[df['분류']=='국내'][cols_table], column_config=column_config, width='stretch', hide_index=True)
    with tab3:
        st.dataframe(df[df['분류']=='해외'][cols_table], column_config=column_config, width='stretch', hide_index=True)

    # 하단 서명
    st.markdown("---")
    st.caption("© 2025 **배당팽이** | 실시간 데이터 기반 배당 대시보드")
    st.caption("First Released: 2025.12.31 | [배당팽이의 배당 투자 일지](https://blog.naver.com/dividenpange)")

if __name__ == "__main__":
    main()






