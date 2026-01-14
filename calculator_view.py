import streamlit as st
import pandas as pd
import altair as alt
import random
import time
import logic
import ui
from streamlit.runtime.scriptrunner import get_script_run_ctx

def render_calculator_ui(df, supabase):
    """사용자 메인 계산기 및 상세 시뮬레이션 (랜덤 인카운터 포함 완벽 복구)"""
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
            # 해외 주식 포함 시 경고
            has_foreign_stock = any(df[df['pure_name'] == s_name].iloc[0]['분류'] == '해외' for s_name in selected)
            if has_foreign_stock:
                st.warning("📢 **잠깐!** 선택하신 종목 중 '해외 상장 ETF'가 포함되어 있습니다. ISA/연금계좌 결과는 참고용으로만 봐주세요.")

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
                        '현재가': stock_match.get('현재가', '-'), '연배당률': stock_match.get('연배당률', 0),
                        '금융링크': stock_match.get('금융링크', '#'), '환구분': stock_match.get('환구분', '-'),
                        '배당락일': ex_date, '블로그링크': stock_match.get('블로그링크', '#'),
                        '신규상장개월수': stock_match.get('신규상장개월수', 0)
                    })

            # 포트폴리오 결과 요약
            total_y_div = sum([(total_invest * (weights[n]/100) * (df[df['pure_name']==n].iloc[0]['연배당률']/100)) for n in selected])
            total_m = total_y_div / 12
            avg_y = sum([(df[df['pure_name']==n].iloc[0]['연배당률'] * (weights[n]/100)) for n in selected])

            st.markdown("### 🎯 포트폴리오 결과")
            st.metric("📈 가중 평균 연배당률", f"{avg_y:.2f}%")
            r1, r2, r3 = st.columns(3)
            r1.metric("월 수령액 (세후)", f"{total_m * 0.846:,.0f}원", delta="-15.4%", delta_color="inverse")
            r2.metric("월 수령액 (ISA/세전)", f"{total_m:,.0f}원", delta="100%", delta_color="normal")
            with r3:
                st.markdown(f"""<div style="background-color: #d4edda; color: #155724; padding: 15px; border-radius: 8px; border: 1px solid #c3e6cb; height: 100%; display: flex; flex-direction: column; justify-content: center;"><div style="font-weight: bold; font-size: 1.05em;">✅ 일반 계좌 대비 월 {total_m * 0.154:,.0f}원 이득!</div><div style="color: #6c757d; font-size: 0.8em; margin-top: 5px;">(비과세 및 과세이연 단순 가정)</div></div>""", unsafe_allow_html=True)

            # 상세 분석 탭 호출
            render_tabs(all_data, total_m, avg_y, total_invest)

def render_tabs(all_data, total_m, avg_y, total_invest):
    df_ana = pd.DataFrame(all_data)
    tab_analysis, tab_simulation, tab_goal = st.tabs(["💎 자산 구성 분석", "💰 10년 뒤 자산 미리보기", "🎯 목표 배당 달성"])
    
    with tab_analysis:
        st.info("💡 **자산 구성 분석:** 종목별 비중과 유형에 따른 분산도를 확인합니다.")
        chart_col, table_col = st.columns([1.2, 1])
        asset_sum = df_ana.groupby('자산유형').agg({'비중': 'sum', '투자금액_만원': 'sum'}).reset_index()
        with chart_col:
            donut = alt.Chart(asset_sum).mark_arc(innerRadius=60).encode(theta="비중:Q", color="자산유형:N").properties(height=320)
            st.altair_chart(donut, use_container_width=True)
        with table_col:
            st.write("📋 **유형별 요약**")
            st.dataframe(asset_sum, hide_index=True)
        ui.render_custom_table(df_ana)
        st.error("""**⚠️ 포트폴리오 분석 시 유의사항**
1. 과거의 데이터를 기반으로 한 단순 결과값이며, 실제 투자 수익을 보장하지 않습니다.
2. '달러 자산' 비율은 실제 환노출 여부와 다를 수 있으므로 투자 전 확인이 필요합니다.
3. 실제 배당금 지급일과 금액은 운용사의 사정에 따라 변경될 수 있습니다.""")

    with tab_simulation:
        st.info("💡 **미래 자산 예측:** 매월 배당금을 재투자하고 추가 적립금을 더했을 때의 복리 효과를 계산합니다.")
        years_sim = st.select_slider("⏳ 투자 기간", options=[3, 5, 10, 15, 20, 30], value=5)
        apply_inflation = st.toggle("📉 물가상승률(2.5%) 반영", value=False)
        monthly_add = st.number_input("➕ 매월 추가 적립 (만원)", value=150) * 10000
        
        # 시뮬레이션 계산
        current_bal = total_invest
        sim_list = []
        for m in range(years_sim * 12 + 1):
            div_m = current_bal * (avg_y / 100 / 12)
            current_bal += (div_m + monthly_add)
            disp_bal = current_bal / ((1.025)**(m/12)) if apply_inflation else current_bal
            sim_list.append({"년차": round(m/12, 1), "예상자산": disp_bal / 10000})
        
        st.altair_chart(alt.Chart(pd.DataFrame(sim_list)).mark_area(opacity=0.3).encode(x='년차:Q', y='예상자산:Q').properties(height=250), use_container_width=True)
        
        # [완벽 복구] 랜덤 인카운터 로직
        final_val = sim_list[-1]['예상자산'] * 10000
        monthly_pocket = final_val * (avg_y / 100 / 12)
        
        analogy_items = [
            {"name": "스타벅스", "unit": "잔", "price": 4500, "emoji": "☕"},
            {"name": "뜨끈한 국밥", "unit": "그릇", "price": 10000, "emoji": "🍲"},
            {"name": "넷플릭스 구독", "unit": "개월", "price": 17000, "emoji": "📺"},
            {"name": "치킨", "unit": "마리", "price": 23000, "emoji": "🍗"},
            {"name": "제주도 항공권", "unit": "장", "price": 60000, "emoji": "✈️"},
            {"name": "특급호텔 숙박", "unit": "박", "price": 200000, "emoji": "🏨"},
            {"name": "최신 아이폰", "unit": "대", "price": 1500000, "emoji": "📱"}
        ]
        
        affordable_items = [item for item in analogy_items if (monthly_pocket * 0.846) >= item['price']]
        selected_item = random.choice(affordable_items) if affordable_items else analogy_items[0]
        msg_count = f"{int((monthly_pocket * 0.846) // selected_item['price']):,}"

        st.markdown(f"""
            <div style="background-color: #e7f3ff; border: 1.5px solid #d0e8ff; border-radius: 16px; padding: 25px; text-align: center; box-shadow: 0 4px 10px rgba(0,104,201,0.05);">
                <p style="color: #666; font-size: 0.95em; margin: 0 0 8px 0;">{years_sim}년 뒤 모이는 돈 (세후)</p>
                <h2 style="color: #0068c9; font-size: 2.2em; margin: 0; font-weight: 800; line-height: 1.2;">약 {final_val/10000:,.0f}만원</h2>
                <div style="height: 1px; background-color: #d0e8ff; margin: 25px auto; width: 85%;"></div>
                <p style="color: #0068c9; font-weight: bold; font-size: 1.1em; margin: 0 0 12px 0;">📅 월 예상 배당금: {monthly_pocket*0.846/10000:,.1f}만원</p>
                <div style="background-color: rgba(255,255,255,0.5); padding: 15px; border-radius: 12px; display: inline-block; min-width: 80%;">
                    <p style="color: #333; font-size: 1.1em; margin: 0; line-height: 1.6;">
                        매달 <b>{selected_item['emoji']} {selected_item['name']} {msg_count}{selected_item['unit']}</b><br>
                        마음껏 즐기기 가능! 😋
                    </p>
                </div>
            </div>
        """, unsafe_allow_html=True)
        
        st.error("""**⚠️ 시뮬레이션 활용 시 유의사항**
1. 본 결과는 주가·환율 변동과 수수료 등을 제외하고, 현재 배당률로만 계산한 결과입니다.
2. ISA 계좌의 비과세 한도 및 세율은 세법 개정에 따라 달라질 수 있습니다.
3. 과거의 데이터를 기반으로 한 단순 시뮬레이션이며, 실제 투자 수익을 보장하지 않습니다.""")

    with tab_goal:
        st.info("💡 **목표 배당 달성:** 내가 꿈꾸는 월 배당금을 받기 위해 필요한 추가 투자금액을 계산합니다.")
        goal_m = st.number_input("🎯 목표 월 배당금 (만원)", value=100) * 10000
        needed_total = (goal_m * 12) / (avg_y / 100)
        additional = max(0, needed_total - total_invest)
        st.write(f"현재 수익률 기준으로 월 {goal_m/10000:,.0f}만원을 받으려면 총 **{needed_total/10000:,.0f}만원**이 필요합니다.")
        st.metric("추가 필요 금액", f"{additional/10000:,.0f} 만원")
        st.error("""**⚠️ 목표 달성 계산 시 유의사항**
1. 위 계산은 주가 변동이 없다는 가정하에 연배당률을 역산한 수치입니다.
2. 세금(15.4%) 및 ISA 혜택은 고려되지 않은 세전 금액 기준입니다.
3. 투자 종목의 배당 삭감이나 주가 하락 시 필요한 원금은 더 늘어날 수 있습니다.""")
