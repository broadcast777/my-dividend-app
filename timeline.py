import streamlit as st

def calculate_real_monthly_schedule(df, weights, total_invest):
    """입금 시점을 분석하고 연간 총액을 계산하는 엔진"""
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
        
        # 입금 타이밍 분류
        ex_date = str(row.get('배당락일', '15일'))
        if '초' in ex_date or any(d in ex_date for d in ['1일','2일','3일','4일','5일']):
            timing_data["월초(1~10일)"] += annual_div
        elif '말' in ex_date or '30' in ex_date or '31' in ex_date:
            timing_data["월말(21~말일)"] += annual_div
        else:
            timing_data["월중(11~20일)"] += annual_div
            
    return total_y_div, timing_data

def render_toss_style_heatmap(df, weights, total_invest):
    """생활비 방어 시뮬레이션 중심의 로드맵 대시보드"""
    
    total_y_div, timing_data = calculate_real_monthly_schedule(df, weights, total_invest)
    total_m_div = total_y_div / 12
    avg_yield = (total_y_div / total_invest * 100) if total_invest > 0 else 0
    
    # ---------------------------------------------------------
    # [1] 생활비 방어 시뮬레이션 (로그인 프리 맛보기)
    # ---------------------------------------------------------
    st.markdown("### 🛡️ 생활비 방어 시뮬레이션")
    st.info("💡 한 달 카드값이나 지출액을 입력해 보세요. 배당금이 얼마나 방어해주는지 계산합니다.")

    # 사용자 지출 입력 (세션에만 임시 저장되므로 로그인 없이 가능)
    user_expense = st.number_input("💸 나의 월 평균 지출액 (만원)", min_value=0, value=200, step=10) * 10000

    if user_expense > 0:
        coverage = total_m_div / user_expense
        
        col_res1, col_res2 = st.columns([2, 1])
        with col_res1:
            st.write(f"**현재 생활비 방어율: {coverage*100:.1f}%**")
            st.progress(min(coverage, 1.0))
        with col_res2:
            st.metric("월 방어액", f"{total_m_div/10000:,.1f}만")

        # 분석 결과 메시지
        with st.container(border=True):
            if coverage >= 1.0:
                st.success(f"🎉 **축하합니다! 경제적 자유 달성!**\n\n배당금이 지출을 상쇄하고도 매달 **{(total_m_div - user_expense)/10000:,.1f}만원**이 남습니다.")
            else:
                gap = user_expense - total_m_div
                # 필요한 추가 투자금 계산
                needed_capital = (gap * 12) / (avg_yield / 100) if avg_yield > 0 else 0
                st.markdown(f"🚩 생활비 100% 상쇄까지 월 **{gap/10000:,.1f}만원**이 더 필요합니다.")
                st.caption(f"💡 현재 포트폴리오 수익률({avg_yield:.2f}%) 기준, **약 {needed_capital/10000:,.0f}만원**을 추가 투자하면 지출 0원 시대가 열립니다!")

    # 로그인 유도 (데이터 보존용)
    if not st.session_state.get('is_logged_in', False):
        st.write("")
        st.warning("🔒 **이 방어율 수치를 저장하고 싶으신가요?**\n\n로그인하시면 입력하신 지출 데이터가 저장되어, 다음 방문 시에도 나만의 '방어 로드맵'을 바로 확인하실 수 있습니다.")

    st.divider()



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

def display_sidebar_roadmap(df, weights, total_invest):
    """사이드바 요약"""
    st.sidebar.markdown("---")
    total_y = sum([(total_invest * (weights[n]/100) * (df[df['pure_name']==n].iloc[0]['연배당률']/100)) for n in weights if weights[n] > 0])
    st.sidebar.metric("📊 연간 총 배당", f"{total_y/10000:,.0f}만원")
