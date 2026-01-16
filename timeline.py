import streamlit as st

def calculate_real_monthly_schedule(df, weights, total_invest):
    """입금 시점을 분석하여 타이밍 데이터를 추출하는 엔진"""
    total_y_div = 0.0
    timing_data = {"월초(1~10일)": 0.0, "월중(11~20일)": 0.0, "월말(21~말일)": 0.0}
    
    for stock, w in weights.items():
        if w <= 0: continue
        row_match = df[df['pure_name'] == stock]
        if row_match.empty: continue
        row = row_match.iloc[0]
        
        # 연간 예상 배당금 계산
        annual_div = total_invest * (w / 100) * (row['연배당률'] / 100)
        total_y_div += annual_div
        
        # 입금 타이밍 분류 (배당락일/지급일 키워드 기준)
        ex_date = str(row.get('배당락일', '15일'))
        if '초' in ex_date or any(d in ex_date for d in ['1일','2일','3일','4일','5일']):
            timing_data["월초(1~10일)"] += annual_div
        elif '말' in ex_date or '30' in ex_date or '31' in ex_date:
            timing_data["월말(21~말일)"] += annual_div
        else:
            timing_data["월중(11~20일)"] += annual_div
            
    return total_y_div, timing_data

def render_toss_style_heatmap(df, weights, total_invest):
    """세금 로직을 제거하고 '구매력'과 '박자'에 집중한 대시보드"""
    
    total_y_div, timing_data = calculate_real_monthly_schedule(df, weights, total_invest)
    total_m_div = total_y_div / 12
    
    # ---------------------------------------------------------
    # [1] 배당 구매력 분석 (가장 직관적인 투자 성과)
    # ---------------------------------------------------------
    st.markdown("### 🛒 이번 달 배당금의 실질 가치")
    with st.container(border=True):
        target_stock_price = 12000 # 주당 평균가 (선생님 선호 종목 기준)
        can_buy_shares = int(total_m_div // target_stock_price)
        
        c1, c2 = st.columns([1.5, 1])
        with c1:
            st.markdown(f"매달 들어오는 **{total_m_div/10000:,.1f}만원**은")
            st.caption(f"평균 {target_stock_price:,.0f}원대 종목을 재매수한다고 가정 시")
        with c2:
            st.metric("추가 매수 가능", f"{can_buy_shares}주")

    st.write("")

    # ---------------------------------------------------------
    # [2] 입금 타이밍 리듬 (월초/월중/월말 밸런스)
    # ---------------------------------------------------------
    st.markdown("### 🥁 현금흐름 입금 리듬")
    st.caption("배당금이 한 시기에 몰리지 않고 골고루 들어오는지 확인하세요.")
    
    timing_cols = st.columns(3)
    total_timing = sum(timing_data.values()) if sum(timing_data.values()) > 0 else 1
    
    for i, (label, val) in enumerate(timing_data.items()):
        ratio = (val / total_timing) * 100
        timing_cols[i].metric(label, f"{ratio:.0f}%")
    
    st.divider()
    
    # 최종 요약 문구
    st.info(f"💡 월 평균 배당금 **{total_m_div/10000:,.1f}만원**이 매달 끊임없이 입금되는 구조입니다.")

def display_sidebar_roadmap(df, weights, total_invest):
    """사이드바용 요약 지표"""
    st.sidebar.markdown("---")
    total_y = sum([(total_invest * (weights[n]/100) * (df[df['pure_name']==n].iloc[0]['연배당률']/100)) for n in weights if weights[n] > 0])
    st.sidebar.metric("📊 연간 총 배당", f"{total_y/10000:,.0f}만원")
