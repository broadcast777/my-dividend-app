import streamlit as st
from supabase import create_client
import pandas as pd
import requests
from bs4 import BeautifulSoup
import yfinance as yf
from datetime import datetime
import pytz
import altair as alt

# ==========================================
# [1] 페이지 및 기본 설정
# ==========================================
st.set_page_config(page_title="배당팽이 대시보드", layout="wide")

# Supabase 연결 설정 (Secrets 활용)
URL = st.secrets["SUPABASE_URL"]
KEY = st.secrets["SUPABASE_KEY"]
supabase = create_client(URL, KEY)

# ==========================================
# [2] 데이터 로드 및 전처리 함수 정의
# ==========================================
@st.cache_data(ttl=600)
def load_stock_data_from_csv():
    """Github에서 주식 데이터 CSV 로드 (인코딩 자동 감지)"""
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
    """현재가 조회 (해외: yfinance / 국내: Naver Crawling)"""
    try:
        code_str = str(code).strip()
        
        # 1. 해외 주식 처리
        if category == '해외':
            ticker = yf.Ticker(code_str)
            price = ticker.fast_info.get('last_price')
            if not price:
                price = ticker.history(period="1d")['Close'].iloc[-1]
            return float(price) if price else None
            
        # 2. 국내 주식 처리
        url = f"https://finance.naver.com/item/main.naver?code={code_str}"
        res = requests.get(url, headers={'User-Agent': 'Mozilla/5.0'}, timeout=3)
        soup = BeautifulSoup(res.text, 'html.parser')
        no_today = soup.select_one(".no_today .blind")
        return int(no_today.text.replace(",", "")) if no_today else None

    except requests.exceptions.Timeout:
        st.warning(f"⏱️ {code} 응답 시간 초과 (서버 지연)")
        return None
    except Exception as e:
        st.error(f"❌ {code} 조회 실패: {str(e)}")
        return None

def classify_asset(row):
    """종목명/코드를 기반으로 자산 유형 분류"""
    name = str(row.get('종목명', '')).upper()
    symbol = str(row.get('종목코드', '')).upper()
    
    # 키워드 리스트
    covered = ['커버드콜', 'COVERED CALL', '프리미엄', 'PREMIUM', '+10%', '옵션', 'OPTION', 'QYLD', 'JEPI', 'JEPQ', 'XYLD', 'RYLD', 'NVDY', 'TSLY', 'CONY', 'MSTY', 'ULTRA', 'QQQI', 'GPIQ', 'XYLG', 'QYLG', 'TLTW', 'SVOL']
    bond = ['채권', '국채', 'BOND', '단기채', 'TREASURY', '하이일드', 'HIGH YIELD', 'PFF', '국제금', '골드', 'GOLD', 'BIL', 'SHV', 'SGOV', 'T-BILL', 'TLT']
    
    if any(k in name for k in covered) or any(k in symbol for k in covered): 
        return '🛡️ 커버드콜'
    if '혼합' in name:
        return '⚖️ 혼합형'
    if any(k in name for k in bond) or any(k in symbol for k in bond): 
        return '🏦 채권형'
    if any(k in name for k in ['리츠', 'REITS', '부동산']): 
        return '🏢 리츠형'
        
    return '📈 주식형'

def get_hedge_status(name, category):
    """환헤지/환노출 여부 판단"""
    name_str = str(name).upper()
    
    if category == '해외': 
        return "💲달러(직투)"
    if "환노출" in name_str or "UNHEDGED" in name_str:
        return "⚡환노출"
    if any(x in name_str for x in ["(H)", "헤지", "합성"]): 
        return "🛡️환헤지(H)"
    if any(x in name_str for x in ['미국', 'GLOBAL', 'S&P500', '나스닥', '빅테크', '국제금', '골드', 'GOLD']): 
        return "⚡환노출"
        
    return "-"

@st.cache_data(ttl=300, show_spinner=False)
def load_and_process_data(df_raw, is_admin=False):
    """데이터 가공 및 필터링 메인 로직"""
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
            
            # 관리자 여부에 따른 필터링 (2% ~ 25%)
            if not is_admin:
                if yield_val < 2.0 or yield_val > 25.0:
                    continue 
            else:
                if yield_val < 2.0 or yield_val > 25.0:
                    name = f"🚫 {name} (필터대상)"

            price_display = f"{int(price):,}원" if category == '국내' else f"${price:.2f}"
            
            results.append({
                '코드': code, 
                '종목명': f"{name} ⭐" if months > 0 else name,
                '블로그링크': str(row.get('블로그링크', '#')),
                '금융링크': f"https://finance.naver.com/item/main.naver?code={code}" if category == '국내' else f"https://finance.yahoo.com/quote/{code}",
                '현재가': price_display, 
                '연배당률': yield_val,
                '환구분': get_hedge_status(name, category),
                '배당락일': str(row.get('배당락일', '-')), 
                '분류': category,
                '자산유형': classify_asset(row), 
                'pure_name': name.replace("🚫 ", "").replace(" (필터대상)", ""),
                '신규상장개월수': months
            })
            
    return pd.DataFrame(results).sort_values('연배당률', ascending=False)

# ==========================================
# [3] 메인 애플리케이션 (UI)
# ==========================================
def main():
    st.title("💰 배당팽이 실시간 연배당률 대시보드")

    # 데이터 로드
    df_raw = load_stock_data_from_csv()
    if df_raw.empty: st.stop()
    
    is_admin = st.query_params.get("admin", "false").lower() == "true"

    with st.spinner('⚙️ 배당 데이터베이스 엔진 가동 중... 실시간 시세를 연동하고 있습니다.'):
        df = load_and_process_data(df_raw, is_admin=is_admin)

    if is_admin:
        st.sidebar.success("✅ 관리자 모드: 필터링 없이 모든 종목을 표시합니다.")
    
    st.warning("⚠️ **투자 유의사항:** 본 대시보드의 연배당률은 과거 분배금 데이터를 기반으로 계산된 참고용 지표입니다. 실제 배당금은 운용사의 사정 및 시장 상황에 따라 매월 변동될 수 있습니다.")

    # ------------------------------------------
    # 섹션 1: 포트폴리오 시뮬레이션 & 입력
    # ------------------------------------------
    with st.expander("🧮 나만의 배당 포트폴리오 시뮬레이션", expanded=True):
        col1, col2 = st.columns([1, 2])
        total_invest = col1.number_input("💰 총 투자 금액 (만원)", min_value=100, value=3000, step=100) * 10000
        selected = col2.multiselect("📊 종목 선택", df['pure_name'].unique())

        if selected:
            # 해외 ETF 경고 로직
            has_foreign_stock = any(df[df['pure_name'] == s_name].iloc[0]['분류'] == '해외' for s_name in selected)
            if has_foreign_stock:
                st.warning("📢 **잠깐!** 선택하신 종목 중 '해외 상장 ETF'가 포함되어 있습니다. ISA/연금계좌 결과는 참고용으로만 봐주세요.")

            weights = {}
            remaining = 100
            cols_w = st.columns(2)
            all_data = []
            
            # 종목별 비중 입력 루프
            for i, stock in enumerate(selected):
                with cols_w[i % 2]:
                    safe_rem = max(0, remaining)
                    
                    if i < len(selected) - 1:
                        val = st.number_input(
                            f"{stock} (%)", 
                            min_value=0, 
                            max_value=safe_rem, 
                            value=min(safe_rem, 100 // len(selected)), 
                            step=5, 
                            key=f"s_{i}"
                        )
                        weights[stock] = val
                        remaining -= val
                        amt = total_invest * (val / 100)
                    else:
                        # 마지막 종목은 남은 비중 자동 할당
                        st.info(f"{stock}: {safe_rem}% 자동 적용")
                        weights[stock] = safe_rem
                        amt = total_invest * (safe_rem / 100)
                    
                    st.caption(f"💰 투자금: **{amt/10000:,.0f}만원**")
                
                # 안전한 데이터 조회 (에러 방지)
                stock_match = df[df['pure_name'] == stock]
                if not stock_match.empty:
                    s_row = stock_match.iloc[0]
                    all_data.append({
                        '종목': stock, 
                        '비중': weights[stock], 
                        '자산유형': s_row['자산유형'],
                        '투자금액_만원': amt / 10000 
                    })
                else:
                    st.error(f"⚠️ '{stock}' 종목의 상세 정보를 불러올 수 없습니다.")

            # 결과 계산
            total_y_div = sum([(total_invest * (weights[n]/100) * (df[df['pure_name']==n].iloc[0]['연배당률']/100)) for n in selected])
            total_m = total_y_div / 12
            avg_y = sum([(df[df['pure_name']==n].iloc[0]['연배당률'] * (weights[n]/100)) for n in selected])

            # ------------------------------------------
            # 섹션 2: 포트폴리오 결과 (메트릭 + 막대그래프)
            # ------------------------------------------
            st.markdown("### 🎯 포트폴리오 결과")
            st.metric("📈 가중 평균 연배당률", f"{avg_y:.2f}%")

            r1, r2, r3 = st.columns(3)
            r1.metric("월 수령액 (세후)", f"{total_m * 0.846:,.0f}원", delta="-15.4%", delta_color="inverse")
            r2.metric("월 수령액 (ISA/세전)", f"{total_m:,.0f}원", delta="100%", delta_color="normal")

            with r3:
                st.markdown(f"""
                    <div style="background-color: #d4edda; color: #155724; padding: 15px; border-radius: 8px; border: 1px solid #c3e6cb; height: 100%; display: flex; flex-direction: column; justify-content: center;">
                        <div style="font-weight: bold; font-size: 1.05em;">✅ 일반 계좌 대비 월 {total_m * 0.154:,.0f}원 이득!</div>
                        <div style="color: #6c757d; font-size: 0.8em; margin-top: 5px;">(비과세 및 과세이연 단순 가정입니다)</div>
                    </div>
                """, unsafe_allow_html=True)

            # 계좌별 비교 차트 (바로보기)
            st.write("") 
            c_data = pd.DataFrame({
                '계좌 종류': ['일반 계좌', 'ISA/연금계좌'], 
                '월 수령액': [total_m * 0.846, total_m]
            })
            
            chart_compare = alt.Chart(c_data).mark_bar(cornerRadiusTopLeft=10, cornerRadiusTopRight=10).encode(
                x=alt.X('계좌 종류', sort=None, axis=alt.Axis(labelAngle=0, title=None)),
                y=alt.Y('월 수령액', title=None),
                color=alt.Color('계좌 종류', scale=alt.Scale(domain=['일반 계좌', 'ISA/연금계좌'], range=['#95a5a6', '#f1c40f']), legend=None),
                tooltip=[alt.Tooltip('계좌 종류'), alt.Tooltip('월 수령액', format=',.0f')]
            ).properties(height=220)
            st.altair_chart(chart_compare, use_container_width=True)

            if total_y_div > 20000000:
                st.warning(f"🚨 **주의:** 연간 예상 배당금이 **{total_y_div/10000:,.0f}만원**입니다. 금융소득종합과세 대상에 해당될 수 있습니다.")

            # ------------------------------------------
            # 섹션 3: 상세 분석 (탭 구분)
            # ------------------------------------------
            df_ana = pd.DataFrame(all_data)
            if not df_ana.empty:
                st.write("")
                tab_analysis, tab_simulation = st.tabs(["💎 자산 구성 분석", "💰 10년 뒤 자산 미리보기"])

                # [탭 1] 자산 구성 및 달러 비중
                with tab_analysis:
                    chart_col, table_col = st.columns([1.2, 1]) 
                    
                    # 통화 분류 로직
                    def classify_currency(row):
                        try:
                            target = df[df['pure_name'] == row['종목']].iloc[0]
                            hwan = str(target.get('환구분', ''))
                            bunryu = str(target.get('분류', ''))
                            if any(k in hwan for k in ["환노출", "달러", "직투"]) or bunryu == "해외":
                                return "🇺🇸 달러 자산"
                        except:
                            pass
                        if "(해외)" in row['종목']: return "🇺🇸 달러 자산"
                        return "🇰🇷 원화 자산"

                    df_ana['통화'] = df_ana.apply(classify_currency, axis=1)
                    usd_ratio = df_ana[df_ana['통화'] == "🇺🇸 달러 자산"]['비중'].sum()
                    
                    asset_sum = df_ana.groupby('자산유형').agg({
                        '비중': 'sum', 
                        '투자금액_만원': 'sum', 
                        '종목': lambda x: ', '.join(x)
                    }).reset_index()

                    # [좌측] 도넛 차트
                    with chart_col:
                        st.write("💎 **자산 유형 비중**")
                        donut = alt.Chart(asset_sum).mark_arc(innerRadius=60).encode(
                            theta=alt.Theta("비중:Q"),
                            color=alt.Color("자산유형:N", legend=alt.Legend(orient='bottom', title=None)), 
                            tooltip=[
                                alt.Tooltip("자산유형", title="유형"),
                                alt.Tooltip("비중", format=".1f", title="비중(%)"), 
                                alt.Tooltip("투자금액_만원", format=",d", title="금액(만원)"),
                                alt.Tooltip("종목", title="포함종목")
                            ]
                        ).properties(height=320)
                        st.altair_chart(donut, use_container_width=True)

                    # [우측] 테이블 & 달러 노출도
                    with table_col:
                        st.write("📋 **유형별 요약**")
                        st.dataframe(asset_sum.sort_values('비중', ascending=False),
                                     column_config={
                                         "비중": st.column_config.NumberColumn(format="%d%%"),
                                         "투자금액_만원": st.column_config.NumberColumn("투자금(만원)", format="%d"),
                                         "종목": st.column_config.TextColumn("포함 종목", width="large")
                                     },
                                     hide_index=True, use_container_width=True)
                        
                        st.divider()
                        st.markdown(f"**🌐 달러 자산 노출도: `{usd_ratio:.1f}%`**")
                        st.progress(usd_ratio / 100)
                        
                        if usd_ratio >= 50:
                            st.caption("💡 포트폴리오의 절반 이상이 환율 변동에 영향을 받습니다.")
                        else:
                            st.caption("💡 원화 자산 중심의 구성입니다.")

                # [탭 2] 복리 재투자 시뮬레이션
                with tab_simulation:
                    st.info("📊 투자 기간과 추가 적립금을 설정하여 미래 자산을 그려보세요.")
                    
                    s_col1, s_col2 = st.columns(2)
                    with s_col1:
                        is_tax_free_sim = st.toggle("🛡️ 절세 계좌 모드", value=False)
                    with s_col2:
                        years_sim = st.select_slider("⏳ 투자 기간 (년)", options=[1, 3, 5, 10, 15, 20, 30], value=10)

                    if not is_tax_free_sim:
                        reinvest_ratio = st.slider("💰 배당금 재투자 비중 (%)", 0, 100, 80, step=10)
                        st.caption(f"💡 배당금의 {reinvest_ratio}%는 재투자하고, 나머지는 생활비로 씁니다.")
                    else:
                        reinvest_ratio = 100
                        st.caption("💡 절세 계좌는 배당금 100% 재투자를 가정합니다.")
                    
                    st.markdown("---")
                    st.markdown("**💵 매월 추가 투자금 (선택사항)**")
                    monthly_add_sim = st.number_input(
                        "매월 배당금 외에 추가로 더 투자할 금액 (만원)", 
                        min_value=0, max_value=2000, 
                        value=0, 
                        step=5, 
                        help="이 금액은 매월 원금에 추가되어 복리로 함께 굴러갑니다."
                    ) * 10000
       
                    # 2. 복리 계산 로직 (개선됨: 월초 적립 -> 당월 배당 반영)
                    months_sim = years_sim * 12
                    current_bal = total_invest
                    monthly_yld = avg_y / 100 / 12 # 월 수익률
                    
                    # [중요] 0개월차(시작점) 데이터 미리 기록
                    sim_data = [{
                        "년차": 0,
                        "자산총액": current_bal / 10000,
                        "실제월배당": 0 # 시작 시점엔 배당 없음
                    }]

                    for m in range(1, months_sim + 1):
                        # [순서 변경 1] 월 적립금 먼저 투입 (스노우볼 가속)
                        current_bal += monthly_add_sim
                        
                        # [순서 변경 2] 늘어난 자산 총액 기준으로 이번 달 배당금 계산
                        div_earned = current_bal * monthly_yld
                        
                        # [순서 변경 3] 재투자 실행
                        actual_reinvest = div_earned * (reinvest_ratio / 100)
                        current_bal += actual_reinvest
                        
                        sim_data.append({
                            "년차": m / 12, 
                            "자산총액": current_bal / 10000,
                            "실제월배당": div_earned
                        })
                        current_bal += (actual_reinvest + monthly_add_sim)

                    df_sim_chart = pd.DataFrame(sim_data)

                    # Area Chart 시각화
                    chart_sim = alt.Chart(df_sim_chart).mark_area(
                        line={'color':'#0068c9'},
                        color=alt.Gradient(
                            gradient='linear',
                            stops=[alt.GradientStop(color='white', offset=0), alt.GradientStop(color='#0068c9', offset=1)],
                            x1=1, x2=1, y1=1, y2=0
                        )
                    ).encode(
                        x=alt.X('년차:Q', title='투자 기간'),
                        y=alt.Y('자산총액:Q', title='자산 가치 (만원)', stack=None),
                        tooltip=[alt.Tooltip('년차', format='.1f'), alt.Tooltip('자산총액', format=',.0f')]
                    ).properties(height=250)
                    st.altair_chart(chart_sim, use_container_width=True)

                    # 결과 카드 및 랜덤 비유
                    final_row = df_sim_chart.iloc[-1]
                    import random
                    analogy_items = [
                        {"name": "☕ 스타벅스", "price": 4500, "unit": "잔"},
                        {"name": "🍔 빅맥 세트", "price": 7200, "unit": "개"},
                        {"name": "🍗 치킨", "price": 23000, "unit": "마리"}
                    ]
                    selected_item = random.choice(analogy_items)
                    item_count = int((final_row['실제월배당'] * 0.846) // selected_item['price'])

                    st.markdown(f"""
                        <div style="background-color: #f8f9fa; padding: 20px; border-radius: 15px; text-align: center; border: 1px solid #eee;">
                            <p style="margin:0; color:#666; font-size:0.9em;">{years_sim}년 뒤 예상 자산</p>
                            <h2 style="margin:5px 0; color:#0068c9;">약 {final_row['자산총액']/10000:,.1f} 억원</h2>
                            <div style="margin-top:15px; background-color:#e7f3ff; display:inline-block; padding:5px 15px; border-radius:10px;">
                                <span style="color:#0068c9; font-weight:bold; font-size:0.95em;">
                                    📅 월 예상 배당금: {final_row['실제월배당']/10000:,.1f} 만원 (세전)
                                </span>
                            </div>
                            <p style="margin-top:15px; font-size:0.9em; color:#444; line-height:1.4;">
                                그 돈이면 매달...<br>
                                <b>{selected_item['name']} {item_count:,}{selected_item['unit']}</b> 마음껏 즐기기 가능! 😋
                            </p>
                        </div>
                    """, unsafe_allow_html=True)
            
            # 시뮬레이션 유의사항
            st.error("""
            **⚠️ 시뮬레이션 활용 시 유의사항**
            1. 본 결과는 주가·환율 변동과 수수료 등을 제외하고, 현재 배당률로만 계산한 결과입니다.
            2. 실제 배당금은 운용사의 공시 및 환율 상황에 따라 매월 달라질 수 있습니다.
            3. 본 도구는 투자 참고용이며, 미래 수익을 보장하지 않습니다.
            """)

    # ------------------------------------------
    # 섹션 4: 전체 데이터 테이블 출력
    # ------------------------------------------
    st.info("💡 **이동 안내:** '코드' 클릭 시 블로그 분석글로, '🔗정보' 클릭 시 네이버/야후 금융 정보로 이동합니다. (**⭐ 표시는 상장 1년 미만 종목입니다.**)")
  
    def render_custom_table(data_frame):
        """데이터프레임을 HTML 테이블로 예쁘게 렌더링"""
        html_rows = []
        for _, row in data_frame.iterrows():
            blog_link = str(row.get('블로그링크', '')).strip()
            if not blog_link or blog_link == '#':
                blog_link = "https://blog.naver.com/dividenpange"
            
            b_link = f"<a href='{blog_link}' target='_blank' style='color:#0068c9; text-decoration:none; font-weight:bold;'>{row['코드']}</a>"
            stock_name = f"<span style='color:#333; font-weight:500;'>{row['종목명']}</span>"
            f_link = f"<a href='{row['금융링크']}' target='_blank' style='color:#0068c9; text-decoration:none;'>🔗정보</a>"
            
            is_new = row.get('신규상장개월수', 0)
            suffix = " (추정)" if (0 < is_new < 12) else ""
            yield_display = f"<span style='color:{'#ff4b4b' if row['연배당률']>=10 else '#333'}; font-weight:{'bold' if row['연배당률']>=10 else 'normal'};'>{row['연배당률']:.2f}%{suffix}</span>"
            
            html_rows.append(f"<tr><td>{b_link}</td><td class='name-cell'>{stock_name}</td><td>{row['현재가']}</td><td>{yield_display}</td><td>{row['환구분']}</td><td>{row['배당락일']}</td><td>{f_link}</td></tr>")

        st.markdown(f"""
        <style>
            table {{ width:100% !important; border-collapse:collapse; font-size:14px; margin: 0 auto; }}
            th {{ background:#f0f2f6; padding:12px 8px; border-bottom: 2px solid #ddd; text-align: center; }}
            td {{ padding:10px 8px; border-bottom:1px solid #eee; text-align: center; }}
            .name-cell {{ text-align: left !important; white-space: normal !important; min-width: 150px; }}
        </style>
        <table>
            <thead><tr><th>코드</th><th style='text-align:left;'>종목명</th><th>현재가</th><th>연배당률</th><th>환구분</th><th>배당락일</th><th>네이버/야후</th></tr></thead>
            <tbody>{''.join(html_rows)}</tbody>
        </table>
        """, unsafe_allow_html=True)

    tab_all, tab_kor, tab_usa = st.tabs(["🌎 전체", "🇰🇷 국내", "🇺🇸 해외"])

    with tab_all:
        render_custom_table(df)
    with tab_kor:
        render_custom_table(df[df['분류'] == '국내'])
    with tab_usa:
        render_custom_table(df[df['분류'] == '해외'])

    # ------------------------------------------
    # 하단 푸터 및 방문자 추적 (독립 실행)
    # ------------------------------------------
    st.divider()
    st.caption("© 2025 **배당팽이** | 실시간 데이터 기반 배당 대시보드")
    st.caption("First Released: 2025.12.31 | [📝 배당팽이의 배당 투자 일지 구경가기](https://blog.naver.com/dividenpange)")

    @st.fragment
    def track_visitors():
        """방문자 카운트 및 로그 로직 (부분 렌더링 적용)"""
        # 세션 초기화
        if 'visited' not in st.session_state:
            st.session_state.visited = False
            
        # DB 기록 (세션당 1회)
        if not st.session_state.visited:
            try:
                query_params = st.query_params
                is_admin = query_params.get("admin", "false").lower() == "true"
                
                if not is_admin:
                    # 유입 경로 로깅
                    source_tag = query_params.get("source", None)
                    from streamlit.web.server.websocket_headers import _get_websocket_headers
                    headers = _get_websocket_headers()
                    referer = headers.get("Referer", "Direct")
                    log_entry = source_tag if source_tag else referer
                    
                    supabase.table("visit_logs").insert({"referer": log_entry}).execute()

                    # 카운트 증가
                    response = supabase.table("visit_counts").select("count").eq("id", 1).execute()
                    if response.data:
                        new_count = response.data[0]['count'] + 1
                        supabase.table("visit_counts").update({"count": new_count}).eq("id", 1).execute()
                        st.session_state.display_count = new_count
                else:
                    response = supabase.table("visit_counts").select("count").eq("id", 1).execute()
                    st.session_state.display_count = response.data[0]['count'] if response.data else "Admin"

                st.session_state.visited = True
            except Exception:
                st.session_state.display_count = "확인 중"
                st.session_state.visited = True

        # 화면 표시 (위젯)
        display_num = st.session_state.get('display_count', '집계 중')
        
        st.write("") 
        st.markdown(f"""
            <div style="display: flex; justify-content: center; align-items: center; gap: 20px; padding: 25px; background: #f8f9fa; border-radius: 15px; border: 1px solid #eee; box-shadow: 0 2px 4px rgba(0,0,0,0.05); margin-bottom: 10px;">
                <div style="text-align: center;">
                    <p style="margin: 0; font-size: 0.9em; color: #666; font-weight: 500;">누적 방문자</p>
                    <p style="margin: 0; font-size: 2.2em; font-weight: 800; color: #0068c9;">{display_num}</p>
                </div>
                <div style="width: 1px; height: 50px; background: #ddd;"></div>
                <div style="text-align: left;">
                    <p style="margin: 2px 0; font-size: 0.85em; color: #555;">🚀 <b>실시간 데이터</b> 연동 중</p>
                    <p style="margin: 2px 0; font-size: 0.85em; color: #555;">🛡️ <b>보안 비밀번호</b> 적용 완료</p>
                </div>
            </div>
        """, unsafe_allow_html=True)

    track_visitors()
    
    # 관리자 전용 로그 모니터링
    if st.query_params.get("admin", "false").lower() == "true":
        with st.expander("🛠️ 관리자 전용: 최근 유입 로그 (최근 5건)", expanded=False):
            try:
                recent_logs = supabase.table("visit_logs")\
                    .select("referer, created_at")\
                    .order("created_at", desc=True)\
                    .limit(5)\
                    .execute()
                
                if recent_logs.data:
                    log_df = pd.DataFrame(recent_logs.data)
                    log_df['created_at'] = pd.to_datetime(log_df['created_at']).dt.tz_convert('Asia/Seoul').dt.strftime('%Y-%m-%d %H:%M:%S')
                    log_df.columns = ['유입 경로', '접속 시간(KST)']
                    st.table(log_df)
                else:
                    st.write("아직 기록된 유입이 없습니다.")
            except Exception as e:
                st.error(f"로그 로드 실패: {e}")

# 프로그램 실행
if __name__ == "__main__":
    main()

