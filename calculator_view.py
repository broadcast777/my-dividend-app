import streamlit as st
import pandas as pd
import altair as alt
import random
import time
import logic
import ui
from streamlit.runtime.scriptrunner import get_script_run_ctx

def render_calculator_ui(df, supabase):
    """사용자 메인 배당금 계산기 및 시뮬레이션 전체 로직"""
    st.warning("⚠️ **투자 유의사항:** 본 대시보드의 연배당률은 과거 분배금 데이터를 기반으로 계산된 참고용 지표입니다.")

    with st.expander("🧮 나만의 배당 포트폴리오 시뮬레이션", expanded=True):
        col1, col2 = st.columns([1, 2])
        
        current_invest_val = int(st.session_state.get("total_invest", 30000000) / 10000)
        invest_input = col1.number_input("💰 총 투자 금액 (만원)", min_value=100, value=current_invest_val, step=100)
        st.session_state.total_invest = invest_input * 10000
        total_invest = st.session_state.total_invest 
        
        selected = col2.multiselect("📊 종목 선택", df['pure_name'].unique(), default=st.session_state.get("selected_stocks", []))
        st.session_state.selected_stocks = selected

        if selected:
            weights = {}
            remaining = 100
            cols_w = st.columns(2)
            all_data = []
            
            for i, stock in enumerate(selected):
                with cols_w[i % 2]:
                    safe_rem = max(0, remaining)
                    if i < len(selected) - 1:
                        val = st.number_input(f"{stock} (%)", min_value=0, max_value=safe_rem, value=min(safe_rem, 100 // len(selected)), step=5, key=f"s_{i}")
                        weights[stock] = val
                        remaining -= val
                    else:
                        st.info(f"{stock}: {safe_rem}% 자동 적용")
                        weights[stock] = safe_rem
                    
                    amt = total_invest * (weights[stock] / 100)
                    st.caption(f"💰 투자금: **{amt/10000:,.0f}만원**")

                    # 캘린더 버튼 및 데이터 수집
                    stock_match = df[df['pure_name'] == stock].iloc[0]
                    cal_link = stock_match.get('캘린더링크')
                    ex_date = stock_match.get('배당락일', '-')
                    
                    if cal_link:
                        if st.session_state.get("is_logged_in", False):
                            st.link_button(f"📅 {ex_date} (D-3 알람)", cal_link, use_container_width=True)
                        else:
                            if st.button(f"📅 {ex_date} (D-3 알람)", key=f"btn_cal_{i}", use_container_width=True):
                                st.toast("🔒 로그인 후 등록 가능합니다.", icon="🔒")
                    
                    all_data.append({
                        '종목': stock, '비중': weights[stock], '자산유형': stock_match['자산유형'], '투자금액_만원': amt / 10000,
                        '종목명': stock, '코드': stock_match.get('코드', ''), '분류': stock_match.get('분류', '국내'),
                        '연배당률': stock_match.get('연배당률', 0), '금융링크': stock_match.get('금융링크', '#'),
                        '환구분': stock_match.get('환구분', '-'), '배당락일': ex_date
                    })

            # 결과 요약 계산
            total_y_div = sum([(total_invest * (weights[n]/100) * (df[df['pure_name']==n].iloc[0]['연배당률']/100)) for n in selected])
            total_m = total_y_div / 12
            avg_y = sum([(df[df['pure_name']==n].iloc[0]['연배당률'] * (weights[n]/100)) for n in selected])

            st.markdown("### 🎯 포트폴리오 결과")
            st.metric("📈 가중 평균 연배당률", f"{avg_y:.2f}%")
            
            # 토스식 결과 리포트 (기존 app.py 로직)
            r1, r2, r3 = st.columns(3)
            r1.metric("월 수령액 (세후)", f"{total_m * 0.846:,.0f}원", delta="-15.4%", delta_color="inverse")
            r2.metric("월 수령액 (ISA/세전)", f"{total_m:,.0f}원", delta="100%", delta_color="normal")
            with r3:
                st.markdown(f"""<div style="background-color: #d4edda; color: #155724; padding: 15px; border-radius: 8px; border: 1px solid #c3e6cb; height: 100%; display: flex; flex-direction: column; justify-content: center;"><div style="font-weight: bold; font-size: 1.05em;">✅ 월 {total_m * 0.154:,.0f}원 이득!</div></div>""", unsafe_allow_html=True)

            # 캘린더 통합 다운로드
            st.divider()
            ics_data = logic.generate_portfolio_ics(all_data)
            if st.session_state.get("is_logged_in", False):
                st.download_button("📥 전체 일정 파일 받기 (.ics)", data=ics_data, file_name="dividend_calendar.ics", use_container_width=True, type="primary")
            else:
                if st.button("📥 전체 일정 파일 받기 (.ics)", use_container_width=True):
                    st.toast("🔒 로그인이 필요합니다.", icon="🔒")

            # 분석 탭 (중략 없이 전체 포함)
            render_analysis_tabs(df, all_data, total_invest, avg_y)

def render_analysis_tabs(df, all_data, total_invest, avg_y):
    """상세 분석 및 시뮬레이션 탭"""
    df_ana = pd.DataFrame(all_data)
    tab1, tab2 = st.tabs(["💎 자산 구성", "💰 미래 자산 예측"])
    
    with tab1:
        # 통화 분류 및 도넛 차트
        df_ana['통화'] = df_ana.apply(lambda r: "🇺🇸 달러" if r['분류'] == "해외" else "🇰🇷 원화", axis=1)
        asset_sum = df_ana.groupby('자산유형').agg({'비중': 'sum', '투자금액_만원': 'sum'}).reset_index()
        
        c1, c2 = st.columns(2)
        with c1:
            donut = alt.Chart(asset_sum).mark_arc(innerRadius=50).encode(
                theta="비중:Q", color="자산유형:N"
            ).properties(height=300)
            st.altair_chart(donut, use_container_width=True)
        with c2:
            st.write("📋 **유형별 요약**")
            st.table(asset_sum)
            
        ui.render_custom_table(df_ana)

    with tab2:
        # 10년 시뮬레이션 로직 (기존 로직 그대로)
        years = st.slider("⏳ 투자 기간", 1, 30, 5)
        monthly_add = st.number_input("➕ 매월 적립(만원)", 0, 1000, 100) * 10000
        
        # 단순 복리 계산 시뮬레이션
        current_bal = total_invest
        sim_data = []
        for m in range(years * 12 + 1):
            div = current_bal * (avg_y / 100 / 12)
            current_bal += (div + monthly_add)
            sim_data.append({"년차": m/12, "자산": current_bal/10000})
            
        chart = alt.Chart(pd.DataFrame(sim_data)).mark_area(opacity=0.3).encode(
            x='년차:Q', y='자산:Q'
        ).properties(height=250)
        st.altair_chart(chart, use_container_width=True)
        
        st.success(f"🚀 {years}년 뒤 예상 자산: **{current_bal/10000:,.0f}만원**")
