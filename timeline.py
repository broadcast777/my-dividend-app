import streamlit as st
import pandas as pd

def calculate_real_monthly_schedule(df, weights, total_invest):
    """배당 주기와 입금 시점을 반영한 정밀 계산 엔진"""
    monthly_payouts = [0.0] * 12
    timing_data = {"월초(1~10일)": 0.0, "월중(11~20일)": 0.0, "월말(21~말일)": 0.0}
    
    for stock, w in weights.items():
        if w <= 0: continue
        row_match = df[df['pure_name'] == stock]
        if row_match.empty: continue
        row = row_match.iloc[0]
        
        annual_div = total_invest * (w / 100) * (row['연배당률'] / 100)
        cycle = str(row.get('배당주기', '월'))
        ex_date = str(row.get('배당락일', '15일')) # 날짜 정보 추출용
        
        # 1. 월별 금액 배분
        payout_months = []
        if '월' in cycle: payout_months = list(range(12))
        elif '1' in cycle: payout_months = [0, 3, 6, 9]
        elif '2' in cycle: payout_months = [1, 4, 7, 10]
        elif '3' in cycle: payout_months = [2, 5, 8, 11]
        
        div_per_payout = annual_div / len(payout_months) if payout_months else 0
        for m in payout_months:
            monthly_payouts[m] += div_per_payout
            
        # 2. 입금 타이밍 분류 (단순 예시 로직)
        if '초' in ex_date or any(d in ex_date for d in ['1일','2일','3일','4일','5일']):
            timing_data["월초(1~10일)"] += annual_div
        elif '말' in ex_date or '30' in ex_date or '31' in ex_date:
            timing_data["월말(21~말일)"] += annual_div
        else:
            timing_data["월중(11~20일)"] += annual_div
            
    return monthly_payouts, timing_data

def render_toss_style_heatmap(df, weights, total_invest):
    """월배당 투자자를 위한 토스식 정밀 진단 로드맵"""
    
    monthly_data, timing_data = calculate_real_monthly_schedule(df, weights, total_invest)
    total_y_div = sum(monthly_data)
    total_m_div = total_y_div / 12
    
    # ---------------------------------------------------------
    # [1] 세금 방어선 모니터링 (월배당 투자자의 핵심 지표)
    # ---------------------------------------------------------
    st.markdown("### 🛡️ 금융소득 종합과세 방어선")
    tax_limit = 20000000 # 2,000만원 한도
    safety_ratio = min(total_y_div / tax_limit, 1.0)
    
    col_t1, col_t2 = st.columns([3, 1])
    with col_t1:
        color = "blue" if safety_ratio < 0.8 else "orange" if safety_ratio < 0.95 else "red"
        st.progress(safety_ratio)
        st.caption(f"현재 연간 배당액: **{total_y_div/10000:,.0f}만원** / 한도 {tax_limit/10000:,.0f}만원")
    with col_t2:
        if safety_ratio < 0.95: st.success("✅ 안전")
        else: st.warning("⚠️ 주의")

    st.write("")

    # ---------------------------------------------------------
    # [2] 배당 히트맵 (시각적 리듬 확인)
    # ---------------------------------------------------------
    st.markdown("### 📅 월별 배당 리듬")
    max_amt = max(monthly_data) if max(monthly_data) > 0 else 1
    months_labels = [f"{i}월" for i in range(1, 13)]
    
    cols = st.columns(4)
    for i in range(12):
        amt = monthly_data[i]
        alpha = 0.05 + (amt / max_amt) * 0.90 if amt > 0 else 0.02
        bg_color = f"rgba(0, 104, 201, {alpha})"
        text_color = "#FFFFFF" if alpha > 0.4 else "#333333"
        
        with cols[i % 4]:
            st.markdown(f"""
                <div style="background-color: {bg_color}; color: {text_color}; padding: 15px; 
                            border-radius: 12px; text-align: center; margin-bottom: 10px; border: 1px solid #f0f2f6;">
                    <div style="font-size: 0.8rem; opacity: 0.8;">{months_labels[i]}</div>
                    <div style="font-weight: bold; font-size: 1.1rem;">{amt/10000:,.1f}만</div>
                </div>
            """, unsafe_allow_html=True)

    # ---------------------------------------------------------
    # [3] 배당 구매력 분석 (맛보기 수육의 포인트)
    # ---------------------------------------------------------
    st.divider()
    st.markdown("### 🛒 배당금의 실질 구매력")
    
    # 예시: 주당 12,000원짜리 종목을 몇 주 더 살 수 있는지 계산
    target_stock_price = 12000 
    can_buy_shares = int(total_m_div // target_stock_price)
    
    c1, c2 = st.columns(2)
    with c1:
        st.info(f"매달 받는 **{total_m_div/10000:,.1f}만원**으로")
    with c2:
        st.success(f"**약 {can_buy_shares}주**를 재투자 가능!")
    st.caption(f"💡 (주당 {target_stock_price:,.0f}원 종목 기준 / 복리의 마법이 시작됩니다)")

    # ---------------------------------------------------------
    # [4] 입금 타이밍 리듬 (월초/월말 밸런스)
    # ---------------------------------------------------------
    st.divider()
    st.markdown("### 🥁 현금흐름 입금 리듬")
    st.caption("배당금이 한 시기에 몰리지 않고 골고루 들어오는지 확인하세요.")
    
    timing_cols = st.columns(3)
    total_timing = sum(timing_data.values()) if sum(timing_data.values()) > 0 else 1
    
    for i, (label, val) in enumerate(timing_data.items()):
        ratio = (val / total_timing) * 100
        timing_cols[i].metric(label, f"{ratio:.0f}%")

def display_sidebar_roadmap(df, weights, total_invest):
    """사이드바용 요약"""
    st.sidebar.markdown("---")
    total_y = sum([(total_invest * (weights[n]/100) * (df[df['pure_name']==n].iloc[0]['연배당률']/100)) for n in weights if weights[n] > 0])
    st.sidebar.metric("📊 연간 총 배당", f"{total_y/10000:,.0f}만원")
