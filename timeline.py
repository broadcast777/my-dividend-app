import streamlit as st
import re  # 정규식 모듈 추가 (날짜 파싱용)

def _parse_day_from_string(date_str):
    """문자열에서 날짜 숫자만 추출 (예: '매월 15일' -> 15)"""
    if not isinstance(date_str, str): return 15
    match = re.search(r'(\d+)', date_str)
    if match:
        day = int(match.group(1))
        return min(day, 30)
    if '말' in date_str or '마지막' in date_str:
        return 30
    return 15 

def calculate_real_monthly_schedule(df, weights, total_invest):
    """입금 시점을 분석하고 연간 총액을 계산하는 엔진 (세후 기준)"""
    total_y_div = 0.0
    timing_data = {"월초(1~10일)": 0.0, "월중(11~20일)": 0.0, "월말(21~말일)": 0.0}
    
    for stock, w in weights.items():
        if w <= 0: continue
        row_match = df[df['pure_name'] == stock]
        if row_match.empty: continue
        row = row_match.iloc[0]
        
        raw_annual = total_invest * (w / 100) * (row['연배당률'] / 100)
        net_annual = raw_annual * 0.846 
        total_y_div += net_annual
        
        ex_date_str = str(row.get('배당락일', '15일'))
        day_num = _parse_day_from_string(ex_date_str)
        
        if day_num <= 10:
            timing_data["월초(1~10일)"] += net_annual
        elif day_num >= 21:
            timing_data["월말(21~말일)"] += net_annual
        else:
            timing_data["월중(11~20일)"] += net_annual
            
    return total_y_div, timing_data

def render_toss_style_heatmap(df, weights, total_invest):
    """생활비 방어 시뮬레이션 중심의 로드맵 대시보드"""
    
    if total_invest <= 0:
        st.info("👈 왼쪽 사이드바에서 먼저 종목을 담고 투자 금액을 설정해주세요.")
        return

    total_y_div, timing_data = calculate_real_monthly_schedule(df, weights, total_invest)
    total_m_div = total_y_div / 12
    avg_yield = (total_y_div / total_invest * 100) if total_invest > 0 else 0
    
    # ---------------------------------------------------------
    # [1] 생활비 방어 시뮬레이션 (동기화 완료)
    # ---------------------------------------------------------
    st.markdown("### 🛡️ 생활비 방어 시뮬레이션 (세후 기준)")
    
    # --- 💡 [수정 포인트] 중복 입력창 제거 및 사이드바 값과 동기화 ---
    # 이제 여기서 숫자를 따로 입력받지 않고, 사이드바에 입력된 값을 실시간으로 가져옵니다.
    current_expense = st.session_state.get('monthly_expense', 200)
    user_expense_real = current_expense * 10000 
    
    st.write(f"📢 현재 설정된 월 지출액: **{current_expense}만원** (사이드바에서 변경 가능)")

    if user_expense_real > 0:
        coverage = total_m_div / user_expense_real
        
        col_res1, col_res2 = st.columns([2, 1])
        with col_res1:
            st.write(f"**현재 생활비 방어율: {coverage*100:.1f}%**")
            st.progress(min(coverage, 1.0))
        with col_res2:
            st.metric("월 실수령액", f"{total_m_div/10000:,.1f}만")

        with st.container(border=True):
            if coverage >= 1.0:
                st.success(f"🎉 **축하합니다! 경제적 자유 달성!**\n\n지출을 다 막고 매달 **{(total_m_div - user_expense_real)/10000:,.1f}만원**이 남습니다.")
            else:
                gap = user_expense_real - total_m_div
                if avg_yield > 0:
                    needed_capital = (gap * 12) / (avg_yield / 100)
                    st.markdown(f"🚩 생활비 100% 상쇄까지 월 **{gap/10000:,.1f}만원**이 더 필요합니다.")
                    st.caption(f"💡 현재 포트폴리오 기준, **약 {needed_capital/10000:,.0f}만원**을 추가 투자하면 지출 0원 시대가 열립니다!")

    # 로그인 유도 메시지
    if not st.session_state.get('is_logged_in', False):
        st.write("")
        st.warning("🔒 **이 방어율 수치를 저장하고 싶으신가요?**\n\n로그인하시면 지출 데이터가 저장되어 나만의 로드맵을 바로 확인하실 수 있습니다.")

    st.divider()

    # [2] 입금 타이밍 리듬
    st.markdown("### 🥁 현금흐름 입금 리듬")
    timing_cols = st.columns(3)
    total_timing = sum(timing_data.values())
    if total_timing == 0: total_timing = 1 
    
    for i, (label, val) in enumerate(timing_data.items()):
        ratio = (val / total_timing) * 100
        timing_cols[i].metric(label, f"{ratio:.0f}%")

def display_sidebar_roadmap(df, weights, total_invest):
    """사이드바 요약 (방어율 실시간 연동)"""
    st.sidebar.markdown("---")
    
    total_y_net = 0
    for stock, w in weights.items():
        if w > 0:
            row_match = df[df['pure_name'] == stock]
            if not row_match.empty:
                raw_annual = total_invest * (w / 100) * (row_match.iloc[0]['연배당률'] / 100)
                total_y_net += raw_annual * 0.846

    # --- 💡 [추가] 사이드바에서도 실시간 방어율을 보여주면 더 완벽합니다! ---
    current_exp = st.session_state.get('monthly_expense', 200)
    monthly_net = (total_y_net / 12)
    defense_rate = (monthly_net / (current_exp * 10000) * 100) if current_exp > 0 else 0

    st.sidebar.metric("📊 연간 실수령액", f"{total_y_net/10000:,.0f}만원")
    st.sidebar.metric("🛡️ 현재 방어율", f"{defense_rate:.1f}%")
    st.sidebar.caption(f"(지출 {current_exp}만원 기준)")
