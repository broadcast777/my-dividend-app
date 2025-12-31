import streamlit as st
import pandas as pd
import requests
from bs4 import BeautifulSoup
import yfinance as yf
from datetime import datetime
import pytz
import altair as alt
import re

# [1] 페이지 설정
st.set_page_config(page_title="배당팽이 대시보드", layout="wide")

# [2] 데이터 로드 함수
def load_stock_data_from_csv():
    url = "https://raw.githubusercontent.com/broadcast777/my-dividend-app/main/stocks.csv"
    try:
        df = pd.read_csv(url, dtype={'종목코드': str}, encoding='utf-8-sig')
        return df
    except:
        try:
            df = pd.read_csv(url, dtype={'종목코드': str}, encoding='cp949')
            return df
        except: return pd.DataFrame()

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
    return None

def classify_asset(row):
    # 종목명과 종목코드를 모두 대문자로 변환하여 검사
    name = str(row['종목명']).upper()
    symbol = str(row['종목코드']).upper()
    
    # 커버드콜 전략 키워드 (QYLD, JEPI 등 포함)
    covered_keywords = [
        '커버드콜', 'COVERED CALL', '프리미엄', 'PREMIUM', '+10%', '옵션', 'OPTION',
        'QYLD', 'JEPI', 'JEPQ', 'XYLD', 'RYLD', 'NVDY', 'TSLY', 'CONY', 'MSTY', 
        'ULTRA', 'QQQI', 'GPIQ', 'XYLG', 'QYLG', 'TLTW', 'SVOL'
    ]
    
    if any(k in name for k in covered_keywords) or any(k in symbol for k in covered_keywords):
        return '🛡️ 커버드콜'
    if any(k in name for k in ['채권', 'T-BILL', '국채', 'BOND', '단기채']):
        return '🏦 채권형'
    if any(k in name for k in ['리츠', 'REITS', '부동산']):
        return '🏢 리츠형'
    return '📈 주식형'

@st.cache_data(ttl=300, show_spinner=False)
def load_and_process_data(df_raw):
    results = []
    for index, row in df_raw.iterrows():
        try:
            code = row['종목코드']; name = row['종목명']; raw_div = float(row['연배당금'])
            category = row['분류']; blog_url = row['블로그링크']
            
            ex_date_raw = str(row['배당락일'])
            if category == '국내':
                if '15' in ex_date_raw: ex_date = "15일"
                elif any(x in ex_date_raw for x in ['말', '마지막', '영업일']): ex_date = "월말"
                else:
                    nums = re.findall(r'\d+', ex_date_raw)
                    ex_date = f"{nums[0]}일" if nums else ex_date_raw
            else:
                ex_date = ex_date_raw.replace("매월", "").strip()

            months = int(row['신규상장개월수']) if pd.notna(row['신규상장개월수']) else 0
            price = get_safe_price(code, category)

            if price:
                annual_div = (raw_div / months * 12) if months > 0 else raw_div
                name_display = f"{name} ⭐(신규)" if months > 0 else name
                
                results.append({
                    '종목명': name_display, '현재가': f"{price:,}원" if category == '국내' else f"${price:.2f}",
                    '연배당률': (annual_div / price) * 100, '배당락일': ex_date,
                    '공식홈': f"https://finance.naver.com/item/main.naver?code={code}" if category == '국내' else f"https://finance.yahoo.com/quote/{code}",
                    '블로그': blog_url, '분류': category, 'raw_price': price,
                    '자산유형': classify_asset(row) 
                })
        except: continue
    return pd.DataFrame(results).sort_values(by='연배당률', ascending=False)

def main():
    # 데이터 로드
    df_raw = load_stock_data_from_csv()
    if df_raw.empty: st.stop()

    korea_tz = pytz.timezone('Asia/Seoul')
    now_kst = datetime.now(korea_tz).strftime('%H:%M')
    
    st.title(f"💰 배당팽이의 실시간 연배당률 대시보드 ({now_kst} 기준)")
    st.warning("""
        ⚠️ **투자 유의사항:** 본 대시보드의 연배당률은 과거 분배금 데이터를 기반으로 계산된 참고용 지표입니다. 
        실제 배당금은 시장 상황에 따라 매월 변동될 수 있습니다.
    """)

    with st.spinner('⚙️ 배당 데이터베이스 엔진 가동 중...'):
        df = load_and_process_data(df_raw)

    # [시뮬레이션 부분]
    with st.expander("🧮 나만의 배당 포트폴리오 시뮬레이션", expanded=True):
        col_in1, col_in2 = st.columns([1, 2])
        with col_in1:
            total_invest = st.number_input("💰 총 투자 금액 (만원)", min_value=100, value=3000, step=100) * 10000
        with col_in2:
            selected_stocks = st.multiselect("📊 종목 선택", df['종목명'].unique())
        
        if selected_stocks:
            has_foreign = any(df[df['종목명'] == s].iloc[0]['분류'] == '해외' for s in selected_stocks)
            if has_foreign:
                st.warning("📢 **잠깐!** 해외 직투 종목은 **ISA 및 연금저축계좌에서 매수가 불가**합니다.")

            weights = {}; remaining = 100
            cols_w = st.columns(2)
            for i, stock in enumerate(selected_stocks):
                with cols_w[i % 2]:
                    if i < len(selected_stocks) - 1:
                        val = st.number_input(f"{stock} (%)", 0, remaining, min(100//len(selected_stocks), remaining), 5, key=f"w_{stock}")
                        weights[stock] = val
                        remaining -= val
                    else:
                        st.info(f"{stock}: {remaining}% 자동 적용")
                        weights[stock] = remaining

            total_monthly = 0; avg_yield = 0
            all_data = []
            for s_name, w in weights.items():
                r = df[df['종목명'] == s_name].iloc[0]
                total_monthly += (total_invest * (w/100) * (r['연배당률']/100) / 12)
                avg_yield += (r['연배당률'] * w)
                all_data.append({'종목': s_name, '비중': w, '자산유형': r['자산유형']})

            st.divider()
            st.metric("📈 가중 평균 연배당률", f"{avg_yield/100:.2f}%")
            r1, r2, r3 = st.columns([1, 1, 1.5])
            with r1: st.metric("월 수령액 (세후)", f"{total_monthly * 0.846:,.0f}원", delta="-15.4%")
            with r2: st.metric("월 수령액 (ISA/세전)", f"{total_monthly:,.0f}원", delta="100%")
            with r3: st.success(f"일반 대비 **월 {total_monthly*0.154:,.0f}원 이득!**")

            res_tab1, res_tab2 = st.tabs(["📊 월 배당금 비교", "💎 포트폴리오 자산 구성"])
            with res_tab1:
                chart_data = pd.DataFrame({'계좌': ['일반', 'ISA/연금'], '금액': [total_monthly * 0.846, total_monthly]})
                st.altair_chart(alt.Chart(chart_data).mark_bar().encode(
                    x=alt.X('계좌', sort=None), y='금액',
                    color=alt.Color('계좌', scale=alt.Scale(domain=['일반', 'ISA/연금'], range=['#95a5a6', '#f1c40f']))
                ).properties(height=300), use_container_width=True)
            
            with res_tab2:
                df_ana = pd.DataFrame(all_data)
                asset_summary = df_ana.groupby('자산유형').agg({'비중': 'sum', '종목': lambda x: ', '.join(x)}).reset_index()
                donut = alt.Chart(asset_summary).mark_arc(innerRadius=60).encode(
                    theta=alt.Theta("비중:Q"),
                    color=alt.Color("자산유형:N", legend=alt.Legend(orient="bottom")),
                    tooltip=[alt.Tooltip("자산유형:N"), alt.Tooltip("비중:Q", format=".1f"), alt.Tooltip("종목:N", title="구성")]
                ).properties(height=400)
                st.altair_chart(donut, use_container_width=True)

            st.divider()
            annual_pretax = total_monthly * 12
            tax_msg = f"🚨 **금융소득종합과세 주의!** 연간 예상 배당액(세전)이 **{annual_pretax/10000:,.0f}만원**으로 2,000만원을 초과합니다.\n\n" if annual_pretax > 20000000 else ""
            st.error(f"{tax_msg}**⚠️ 과거 데이터 기반 안내:** 실제 배당은 변동될 수 있습니다. **🚨 투자 책임:** 본인에게 있습니다.")

    # [메인 테이블]
    column_config = {
        "블로그": st.column_config.LinkColumn("분석글", display_text="📝포스팅 보기", width=100),
        "연배당률": st.column_config.NumberColumn("연배당률", format="%.2f%%", width=80),
        "공식홈": st.column_config.LinkColumn("🔗정보", display_text="🔗정보", width=100)
    }
    show_cols = ['블로그', '종목명', '현재가', '연배당률', '배당락일', '공식홈']
    st.dataframe(df[show_cols], column_config=column_config, width='stretch', hide_index=True)

    st.markdown("---")
    st.caption("© 2025 **배당팽이** | [📝 배당 투자 일지 구경가기](https://blog.naver.com/dividenpange)")

if __name__ == "__main__":
    main()
