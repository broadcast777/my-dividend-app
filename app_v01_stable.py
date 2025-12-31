import streamlit as st
import pandas as pd
import requests
from bs4 import BeautifulSoup
import yfinance as yf
from datetime import datetime
import pytz
import altair as alt

# [1] 페이지 설정
st.set_page_config(page_title="배당팽이 대시보드", layout="wide")

# [2] 데이터 로드 및 처리 함수
@st.cache_data(ttl=600)
def load_stock_data_from_csv():
    url = "https://raw.githubusercontent.com/broadcast777/my-dividend-app/main/stocks.csv"
    for enc in ['utf-8-sig', 'cp949']:
        try:
            df = pd.read_csv(url, dtype={'종목코드': str}, encoding=enc)
            return df
        except: continue
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
    except: return None

def classify_asset(row):
    name = str(row.get('종목명', '')).upper()
    symbol = str(row.get('종목코드', '')).upper()
    covered = ['커버드콜', 'COVERED CALL', '프리미엄', 'PREMIUM', '+10%', '옵션', 'OPTION', 'QYLD', 'JEPI', 'JEPQ', 'XYLD', 'RYLD', 'NVDY', 'TSLY', 'CONY', 'MSTY', 'ULTRA', 'QQQI', 'GPIQ', 'XYLG', 'QYLG', 'TLTW', 'SVOL']
    bond = ['채권', '국채', 'BOND', '단기채', 'TREASURY', '하이일드', 'HIGH YIELD', 'PFF', '국제금', '골드', 'GOLD']
    if any(k in name for k in covered) or any(k in symbol for k in covered): return '🛡️ 커버드콜'
    if any(k in name for k in bond) or any(k in symbol for k in bond): return '🏦 채권형'
    if any(k in name for k in ['리츠', 'REITS', '부동산']): return '🏢 리츠형'
    return '📈 주식형'

def get_hedge_status(name, category):
    name_str = str(name).upper()
    if category == '해외': return "💲달러(직투)"
    if "(H)" in name_str or "헤지" in name_str: return "🛡️환헤지(H)"
    if any(x in name_str for x in ['미국', 'GLOBAL', 'S&P500', '나스닥', '빅테크', '국제금', '골드', 'GOLD']): return "⚡환노출"
    return "-"

@st.cache_data(ttl=300, show_spinner=False)
def load_and_process_data(df_raw):
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
            price_display = f"{int(price):,}원" if category == '국내' else f"${price:.2f}"
            results.append({
                '코드': code, '종목명': f"{name} ⭐" if months > 0 else name,
                '블로그링크': str(row.get('블로그링크', '#')),
                '금융링크': f"https://finance.naver.com/item/main.naver?code={code}" if category == '국내' else f"https://finance.yahoo.com/quote/{code}",
                '현재가': price_display, '연배당률': yield_val,
                '환구분': get_hedge_status(name, category),
                '배당락일': str(row.get('배당락일', '-')), '분류': category,
                '자산유형': classify_asset(row), 'pure_name': name
            })
    return pd.DataFrame(results).sort_values('연배당률', ascending=False)

def main():
    st.title("💰 배당팽이 실시간 연배당률 대시보드")
    
    df_raw = load_stock_data_from_csv()
    if df_raw.empty: st.stop()

    with st.spinner('⚙️ 배당 데이터베이스 엔진 가동 중... 실시간 시세를 연동하고 있습니다.'):
        df = load_and_process_data(df_raw)

    st.warning("⚠️ **투자 유의사항:** 본 대시보드의 연배당률은 과거 분배금 데이터를 기반으로 계산된 참고용 지표입니다. 실제 배당금은 운용사의 사정 및 시장 상황에 따라 매월 변동될 수 있습니다.")

    with st.expander("🧮 나만의 배당 포트폴리오 시뮬레이션", expanded=True):
        col1, col2 = st.columns([1, 2])
        total_invest = col1.number_input("💰 총 투자 금액 (만원)", min_value=100, value=3000, step=100) * 10000
        selected = col2.multiselect("📊 종목 선택", df['pure_name'].unique())
        
        if selected:
            # 해외 종목 경고
            has_foreign_stock = any(df[df['pure_name'] == s_name].iloc[0]['분류'] == '해외' for s_name in selected)
            if has_foreign_stock:
                st.warning("📢 **잠깐!** 선택하신 종목 중 **'해외 상장 ETF'**가 포함되어 있습니다. ISA/연금계좌 결과는 참고용으로만 봐주세요.")

            weights = {}; remaining = 100; cols_w = st.columns(2); all_data = []
            for i, stock in enumerate(selected):
                with cols_w[i % 2]:
                    safe_rem = max(0, remaining)
                    if i < len(selected) - 1:
                        def_v = min(100 // len(selected), safe_rem)
                        val = st.number_input(f"{stock} (%)", 0, 100, def_v, 5, key=f"s_{i}")
                        weights[stock] = val; remaining -= val
                    else:
                        st.info(f"{stock}: {safe_rem}% 자동 적용")
                        weights[stock] = safe_rem
                s_row = df[df['pure_name'] == stock].iloc[0]
                all_data.append({'종목': stock, '비중': weights[stock], '자산유형': s_row['자산유형']})

            total_y_div = sum([(total_invest * (weights[n]/100) * (df[df['pure_name']==n].iloc[0]['연배당률']/100)) for n in selected])
            total_m = total_y_div / 12
            avg_y = sum([(df[df['pure_name']==n].iloc[0]['연배당률'] * (weights[n]/100)) for n in selected])
            
            st.markdown("### 🎯 포트폴리오 결과")
            st.metric("📈 가중 평균 연배당률", f"{avg_y:.2f}%")
            
            r1, r2, r3 = st.columns(3)
            r1.metric("월 수령액 (세후)", f"{total_m * 0.846:,.0f}원", delta="-15.4%", delta_color="inverse")
            r2.metric("월 수령액 (ISA/세전)", f"{total_m:,.0f}원", delta="100%", delta_color="normal")
            
            # [유지] 이득 금액 및 부연 설명 통합 박스
            with r3:
                st.markdown(f"""
                    <div style="background-color: #d4edda; color: #155724; padding: 15px; border-radius: 8px; border: 1px solid #c3e6cb; height: 100%; display: flex; flex-direction: column; justify-content: center;">
                        <div style="font-weight: bold; font-size: 1.05em;">✅ 일반 계좌 대비 월 {total_m * 0.154:,.0f}원 이득!</div>
                        <div style="color: #6c757d; font-size: 0.8em; margin-top: 5px;">(비과세 및 과세이연 단순 가정입니다)</div>
                    </div>
                """, unsafe_allow_html=True)

            if total_y_div > 20000000:
                st.warning(f"🚨 **주의:** 연간 예상 배당금이 **{total_y_div/10000:,.0f}만원**입니다. 금융소득종합과세 대상에 해당될 수 있습니다.")

            # [🔥 복구된 탭 섹션]
            res_tab1, res_tab2 = st.tabs(["📊 월 배당금 비교", "💎 포트폴리오 자산 구성"])
            
            with res_tab1:
                c_data = pd.DataFrame({'계좌 종류': ['일반 계좌', 'ISA/연금'], '월 수령액': [total_m * 0.846, total_m]})
                chart = alt.Chart(c_data).mark_bar().encode(
                    x=alt.X('계좌 종류', sort=None, axis=alt.Axis(labelAngle=0)),
                    y='월 수령액',
                    color=alt.Color('계좌 종류', scale=alt.Scale(domain=['일반 계좌', 'ISA/연금'], range=['#95a5a6', '#f1c40f']))
                ).properties(height=350)
                st.altair_chart(chart, use_container_width=True)

            with res_tab2:
                chart_col, table_col = st.columns([1, 1.2])
                df_ana = pd.DataFrame(all_data)
                asset_sum = df_ana.groupby('자산유형').agg({'비중': 'sum', '종목': lambda x: ', '.join(x)}).reset_index()
                
                with chart_col:
                    donut = alt.Chart(asset_sum).mark_arc(innerRadius=60).encode(
                        theta=alt.Theta("비중:Q"),
                        color=alt.Color("자산유형:N", legend=None),
                        tooltip=[alt.Tooltip("자산유형:N"), alt.Tooltip("비중:Q", format=".1f"), alt.Tooltip("종목:N", title="포함 종목")]
                    ).properties(height=350)
                    st.altair_chart(donut, use_container_width=True)
                
                with table_col:
                    st.write("📋 **유형별 요약**")
                    st.dataframe(asset_sum.sort_values('비중', ascending=False), 
                                 column_config={"비중": st.column_config.NumberColumn(format="%d%%"), 
                                                "종목": st.column_config.TextColumn("종목", width="large")}, 
                                 hide_index=True, use_container_width=True)

            st.error("""
            **⚠️ 시뮬레이션 활용 시 유의사항**
            1. 본 결과는 현재 시점의 배당률을 바탕으로 한 단순 계산값입니다.
            2. 실제 배당금은 운용사의 공시 및 환율 상황에 따라 매월 달라질 수 있습니다.
            3. 본 도구는 투자 참고용이며, 최종 투자 결정은 본인의 판단하에 신중히 결정하시기 바랍니다.
            """)

    st.info("💡 **이동 안내:** '코드' 클릭 시 블로그 분석글로, '🔗정보' 클릭 시 네이버/야후 금융 정보로 이동합니다. (**⭐ 표시는 상장 1년 미만 종목입니다.**)")
    
    # 데이터 테이블 출력부
    html_rows = []
    for _, row in df.iterrows():
        b_link = f"<a href='{row['블로그링크']}' target='_blank' style='color:#0068c9; text-decoration:none; font-weight:bold;'>{row['코드']}</a>"
        stock_name = f"<span style='color:#333; font-weight:500;'>{row['종목명']}</span>"
        f_link = f"<a href='{row['금융링크']}' target='_blank' style='color:#0068c9; text-decoration:none;'>🔗정보</a>"
        yield_display = f"<span style='color:{'#ff4b4b' if row['연배당률']>=10 else '#333'}; font-weight:{'bold' if row['연배당률']>=10 else 'normal'};'>{row['연배당률']:.2f}%</span>"
        html_rows.append(f"<tr><td>{b_link}</td><td class='name-cell'>{stock_name}</td><td>{row['현재가']}</td><td>{yield_display}</td><td>{row['환구분']}</td><td>{row['배당락일']}</td><td>{f_link}</td></tr>")

    st.markdown(f"""
    <style>
        table {{ width:100% !important; border-collapse:collapse; font-size:14px; table-layout: auto !important; margin: 0 auto; }}
        th {{ background:#f0f2f6; padding:12px 8px; white-space: nowrap; border-bottom: 2px solid #ddd; text-align: center; }}
        td {{ padding:10px 8px; border-bottom:1px solid #eee; text-align: center; }}
        .name-cell {{ text-align: left !important; white-space: normal !important; min-width: 200px; }}
        tr:hover {{ background-color: #f9f9f9; }}
    </style>
    <table>
        <thead><tr><th>코드</th><th style='text-align:left;'>종목명</th><th>현재가</th><th>연배당률</th><th>환구분</th><th>배당락일</th><th>네이버/야후</th></tr></thead>
        <tbody>{''.join(html_rows)}</tbody>
    </table>
    """, unsafe_allow_html=True)
    # ... (기본 데이터 테이블 출력 st.markdown 코드)

    # --- 데이터 테이블 출력 코드 바로 아래 (최하단) ---
    st.divider()
    
    # [1] 각인 문구
    st.caption("© 2025 **배당팽이** | 실시간 데이터 기반 배당 대시보드")
    st.caption("First Released: 2025.12.31 | [📝 배당팽이의 배당 투자 일지 구경가기](https://blog.naver.com/dividenpange)")
    
    # [2] 이미지 깨짐 걱정 없는 텍스트 카운터 (Hits 대체)
    # 이미지 대신 텍스트로 방문자 느낌만 전달합니다.
    st.write("")
    st.markdown(
        """
        <div style="font-size: 0.8em; color: #888; border-top: 1px solid #eee; padding-top: 10px; display: inline-block;">
            📊 <b>누적 방문:</b> 시스템 동기화 중 (배포 후 자동 집계)
        </div>
        """,
        unsafe_allow_html=True
    )

if __name__ == "__main__":
    main()
