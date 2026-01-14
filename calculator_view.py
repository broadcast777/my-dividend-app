import streamlit as st
import pandas as pd
import altair as alt
import random
import time
import logic
import ui
import hashlib
from streamlit.runtime.scriptrunner import get_script_run_ctx

def render_calculator_ui(df, supabase):
    """원본 app.py의 모든 멘트와 계산 로직을 100% 유지한 무삭제 버전"""
    
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
                        amt = total_invest * (val / 100)
                    else:
                        st.info(f"{stock}: {safe_rem}% 자동 적용")
                        weights[stock] = safe_rem
                        amt = total_invest * (safe_rem / 100)
                    st.caption(f"💰 투자금: **{amt/10000:,.0f}만원**")

                    stock_match = df[df['pure_name'] == stock].iloc[0]
                    cal_link = stock_match.get('캘린더링크') 
                    ex_date_view = stock_match.get('배당락일', '-')
                    btn_label = f"📅 {ex_date_view} (D-3 알림)" if cal_link else f"🗓️ {ex_date_view}"

                    if cal_link:
                        if st.session_state.get("is_logged_in", False):
                            st.link_button(btn_label, cal_link, use_container_width=True)
                        else:
                            if st.button(btn_label, key=f"btn_cal_{i}", use_container_width=True):
                                st.toast("🔒 로그인 후 캘린더에 등록할 수 있습니다!", icon="🔒")
                    else:
                        st.caption(f"📅 날짜 미정 ({ex_date_view})")
                    
                    all_data.append({
                        '종목': stock, '비중': weights[stock], '자산유형': stock_match['자산유형'], '투자금액_만원': amt / 10000,
                        '종목명': stock, '코드': stock_match.get('코드', ''), '분류': stock_match.get('분류', '국내'),
                        '연배당률': stock_match.get('연배당률', 0), '금융링크': stock_match.get('금융링크', '#'),
                        '신규상장개월수': stock_match.get('신규상장개월수', 0), '현재가': stock_match.get('현재가', 0),
                        '환구분': stock_match.get('환구분', '-'), '배당락일': ex_date_view, '블로그링크': stock_match.get('블로그링크', '#')
                    })

            total_y_div = sum([(total_invest * (weights[n]/100) * (df[df['pure_name']==n].iloc[0]['연배당률']/100)) for n in selected])
            total_m = total_y_div / 12
            avg_y = sum([(df[df['pure_name']==n].iloc[0]['연배당률'] * (weights[n]/100)) for n in selected])

            st.markdown("### 🎯 포트폴리오 결과")
            st.metric("📈 가중 평균 연배당률", f"{avg_y:.2f}%")
            r1, r2, r3 = st.columns(3)
            r1.metric("월 수령액 (세후)", f"{total_m * 0.846:,.0f}원", delta="-15.4%", delta_color="inverse")
            r2.metric("월 수령액 (ISA/세전)", f"{total_m:,.0f}원", delta="100%", delta_color="normal")
            with r3:
                st.markdown(f"""<div style="background-color: #d4edda; color: #155724; padding: 15px; border-radius: 8px; border: 1px solid #c3e6cb; height: 100%; display: flex; flex-direction: column; justify-content: center;"><div style="font-weight: bold; font-size: 1.05em;">✅ 일반 계좌 대비 월 {total_m * 0.154:,.0f}원 이득!</div><div style="color: #6c757d; font-size: 0.8em; margin-top: 5px;">(비과세 및 과세이연 단순 가정입니다)</div></div>""", unsafe_allow_html=True)

            st.write("")
            c_data = pd.DataFrame({'계좌 종류': ['일반 계좌', 'ISA/연금계좌'], '월 수령액': [total_m * 0.846, total_m]})
            chart_compare = alt.Chart(c_data).mark_bar(cornerRadiusTopLeft=10, cornerRadiusTopRight=10).encode(
                x=alt.X('계좌 종류', sort=None, axis=alt.Axis(labelAngle=0, title=None)), 
                y=alt.Y('월 수령액', title=None), 
                color=alt.Color('계좌 종류', scale=alt.Scale(domain=['일반 계좌', 'ISA/연금계좌'], range=['#95a5a6', '#f1c40f']), legend=None), 
                tooltip=[alt.Tooltip('계좌 종류'), alt.Tooltip('월 수령액', format=',.0f')]
            ).properties(height=220)
            st.altair_chart(chart_compare, use_container_width=True)

            # 캘린더 및 저장 로직 통합
            render_full_features(all_data, weights, total_m, avg_y, total_invest, supabase)

def render_full_features(all_data, weights, total_m, avg_y, total_invest, supabase):
    st.divider()
    ics_data = logic.generate_portfolio_ics(all_data)
    st.subheader("📅 캘린더 일괄 등록")
    col_d1, col_d2 = st.columns([1.5, 1])
    with col_d1:
        st.caption("매번 버튼을 누르기 귀찮으신가요? 모든 일정을 한 번에 내 폰 캘린더에 넣으세요.")
    with col_d2:
        if st.session_state.get("is_logged_in", False):
            st.download_button("📥 전체 일정 파일 받기 (.ics)", data=ics_data, file_name="dividend_calendar.ics", mime="text/calendar", use_container_width=True, type="primary")
        else:
            if st.button("📥 전체 일정 파일 받기 (.ics)", key="ics_lock_btn", use_container_width=True):
                st.toast("🔒 로그인 회원만 '전체 다운로드'를 할 수 있습니다!", icon="🔒")

    st.write("") 
    with st.container(border=True):
        st.write("💾 **포트폴리오 저장 / 수정**")
        if not st.session_state.get('is_logged_in', False):
            st.info("🔒 로그인이 필요합니다. 카카오 로그인을 추천합니다!")
            try:
                ctx = get_script_run_ctx()
                current_session_id = ctx.session_id
            except: current_session_id = "unknown"
            
            # 카카오 로그인 버튼 HTML
            try:
                res_kakao = supabase.auth.sign_in_with_oauth({
                    "provider": "kakao",
                    "options": {"redirect_to": f"https://dividend-pange.streamlit.app?old_id={current_session_id}", "skip_browser_redirect": True}
                })
                if res_kakao.url:
                    st.markdown(f'<a href="{res_kakao.url}" target="_blank" style="display:block; background-color:#FEE500; color:#000; padding:10px; border-radius:8px; text-decoration:none; text-align:center; font-weight:bold;">💬 Kakao로 3초 만에 시작하기</a>', unsafe_allow_html=True)
            except: pass
        else:
            # 원본 저장/수정 로직 복구
            save_mode = st.radio("방식 선택", ["✨ 새로 만들기", "🔄 기존 파일 수정"], horizontal=True, label_visibility="collapsed")
            save_data = {"total_money": total_invest, "composition": weights, "summary": {"monthly": total_m, "yield": avg_y}}
            if save_mode == "✨ 새로 만들기":
                c1, c2 = st.columns([2, 1])
                p_name = c1.text_input("새 이름", placeholder="포트폴리오 이름", label_visibility="collapsed")
                if c2.button("새로 저장", type="primary", use_container_width=True):
                    supabase.table("portfolios").insert({"user_id": st.session_state.user_info.id, "user_email": st.session_state.user_info.email, "name": p_name or "내 포트폴리오", "ticker_data": save_data}).execute()
                    st.success("저장 완료!")
                    st.rerun()
            else:
                exist_res = supabase.table("portfolios").select("id, name, created_at").eq("user_id", st.session_state.user_info.id).order("created_at", desc=True).execute()
                if exist_res.data:
                    exist_opts = {f"{p.get('name') or '이름없음'} ({p['created_at'][5:10]})": p['id'] for p in exist_res.data}
                    c_up1, c_up2 = st.columns([2, 1])
                    selected_label = c_up1.selectbox("수정할 파일 선택", list(exist_opts.keys()), label_visibility="collapsed")
                    if c_up2.button("덮어쓰기", type="primary", use_container_width=True):
                        supabase.table("portfolios").update({"ticker_data": save_data, "created_at": "now()"}).eq("id", exist_opts[selected_label]).execute()
                        st.success("수정 완료!")
                        st.rerun()

    df_ana = pd.DataFrame(all_data)
    tab_analysis, tab_simulation, tab_goal = st.tabs(["💎 자산 구성 분석", "💰 10년 뒤 자산 미리보기", "🎯 목표 배당 달성"])
    
    with tab_analysis:
        chart_col, table_col = st.columns([1.2, 1])
        def classify_currency(row):
            bunryu, exch, name = str(row.get('분류', '')), str(row.get('환구분', '')), str(row.get('종목', ''))
            return "🇺🇸 달러 자산" if bunryu == "해외" or "(해외)" in name or "환노출" in exch else "🇰🇷 원화 자산"
        df_ana['통화'] = df_ana.apply(classify_currency, axis=1)
        asset_sum = df_ana.groupby('자산유형').agg({'비중': 'sum', '투자금액_만원': 'sum', '종목': lambda x: ', '.join(x)}).reset_index()
        with chart_col:
            donut = alt.Chart(asset_sum).mark_arc(innerRadius=60).encode(theta="비중:Q", color="자산유형:N").properties(height=320)
            st.altair_chart(donut, use_container_width=True)
        with table_col:
            st.dataframe(asset_sum.sort_values('비중', ascending=False), hide_index=True)
        ui.render_custom_table(df_ana)
        st.error("**⚠️ 포트폴리오 분석 시 유의사항**\n1. 과거 데이터를 기반으로 한 참고용 지표입니다.\n2. 실제 배당금 및 지급일은 운용사 사정에 따라 달라질 수 있습니다.")

    with tab_simulation:
        # [무삭제] 시뮬레이션 전체 복리 반복문 로직
        years_sim = st.select_slider("⏳ 투자 기간", options=[3, 5, 10, 15, 20, 30], value=5)
        apply_inflation = st.toggle("📉 물가상승률(2.5%) 반영", value=False)
        is_isa_mode = st.toggle("🛡️ ISA (절세) 계좌로 모으기", value=True)
        monthly_add = st.number_input("➕ 매월 추가 적립 (만원)", value=150) * 10000
        
        months_sim = years_sim * 12
        monthly_yld = avg_y / 100 / 12
        current_bal = total_invest
        total_principal = total_invest
        sim_data = []
        
        for m in range(months_sim + 1):
            div_earned = current_bal * monthly_yld
            current_bal += div_earned + (monthly_add if m > 0 else 0)
            total_principal += (monthly_add if m > 0 else 0)
            disp_bal = current_bal / ((1.025)**(m/12)) if apply_inflation else current_bal
            sim_data.append({"년차": round(m/12, 1), "자산": disp_bal / 10000, "원금": total_principal / 10000})

        st.altair_chart(alt.Chart(pd.DataFrame(sim_data)).mark_area(opacity=0.3).encode(x='년차:Q', y='자산:Q').properties(height=250), use_container_width=True)
        
        # [무삭제] 랜덤 인카운터 비유 로직 원본 전체
        monthly_pocket = (sim_data[-1]['자산'] * 10000) * monthly_yld * (1 if is_isa_mode else 0.846)
        analogy_items = [
            {"name": "스타벅스", "unit": "잔", "price": 4500, "emoji": "☕"},
            {"name": "치킨", "unit": "마리", "price": 23000, "emoji": "🍗"},
            {"name": "최신 아이폰", "unit": "대", "price": 1500000, "emoji": "📱"}
        ]
        affordable = [i for i in analogy_items if monthly_pocket >= i['price']]
        it = random.choice(affordable) if affordable else analogy_items[0]
        st.success(f"매달 {it['emoji']} {it['name']} {int(monthly_pocket//it['price']):,}번 즐기기 가능!")
        st.error("**⚠️ 시뮬레이션 활용 시 유의사항**\n1. 본 결과는 현재 배당률로만 계산한 결과입니다.\n2. 수익을 보장하지 않습니다.")

    with tab_goal:
        goal_m = st.number_input("🎯 목표 월 배당금 (만원)", value=100) * 10000
        needed_total = (goal_m * 12) / (avg_y / 100)
        st.metric("추가 필요 투자금", f"{(needed_total - total_invest)/10000:,.0f} 만원")
        st.error("**⚠️ 목표 달성 계산 시 유의사항**\n1. 세전 금액 기준 계산 결과입니다.\n2. 투자 원금 하락 위험이 존재합니다.")
