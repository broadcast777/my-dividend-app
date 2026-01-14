# pages.py
import streamlit as st
import pandas as pd
import altair as alt
import random
import time
from streamlit.runtime.scriptrunner import get_script_run_ctx
import logic
import ui
import db
from db import init_supabase

supabase = init_supabase()


def render_calculator_page(df, is_authenticated):
   # """포트폴리오 계산기 페이지"""
    
    st.warning("⚠️ **투자 유의사항:** 본 대시보드의 연배당률은 과거 분배금 데이터를 기반으로 계산된 참고용 지표입니다.")
    
    with st.expander("🧮 나만의 배당 포트폴리오 시뮬레이션", expanded=True):
        col1, col2 = st.columns([1, 2])
        current_invest_val = int(st.session_state.total_invest / 10000)
        invest_input = col1.number_input("💰 총 투자 금액 (만원)", min_value=100, value=current_invest_val, step=100)
        st.session_state.total_invest = invest_input * 10000
        total_invest = st.session_state.total_invest 
        
        selected = col2.multiselect("📊 종목 선택", df['pure_name'].unique(), default=st.session_state.selected_stocks)
        st.session_state.selected_stocks = selected

        if selected:
            has_foreign_stock = any(df[df['pure_name'] == s_name].iloc['분류'] == '해외' for s_name in selected)
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

                    # 캘린더 버튼
                    stock_match = df[df['pure_name'] == stock]
                    if not stock_match.empty:
                        s_row = stock_match.iloc
                        cal_link = s_row.get('캘린더링크') 
                        ex_date_view = s_row.get('배당락일', '-')
                        
                        if cal_link:
                            btn_label = f"📅 {ex_date_view} (D-3 알림)" 
                        else:
                            btn_label = f"🗓️ {ex_date_view}"

                        if cal_link:
                            if st.session_state.get("is_logged_in", False):
                                st.link_button(btn_label, cal_link, use_container_width=True)
                            else:
                                if st.button(btn_label, key=f"btn_cal_{i}", use_container_width=True):
                                    st.toast("🔒 로그인 후 캘린더에 등록할 수 있습니다!", icon="🔒")
                        else:
                            st.caption(f"📅 날짜 미정 ({ex_date_view})")
                        
                        # 데이터 수집
                        if not stock_match.empty:
                            all_data.append({
                                '종목': stock, '비중': weights[stock], '자산유형': s_row['자산유형'], '투자금액_만원': amt / 10000,
                                '종목명': stock, '코드': s_row.get('코드', ''), '분류': s_row.get('분류', '국내'),
                                '연배당률': s_row.get('연배당률', 0), '금융링크': s_row.get('금융링크', '#'),
                                '신규상장개월수': s_row.get('신규상장개월수', 0), '현재가': s_row.get('현재가', 0),
                                '환구분': s_row.get('환구분', '-'), '배당락일': s_row.get('배당락일', '-')
                            })

            total_y_div = sum([(total_invest * (weights[n]/100) * (df[df['pure_name']==n].iloc['연배당률']/100)) for n in selected])
            total_m = total_y_div / 12
            avg_y = sum([(df[df['pure_name']==n].iloc['연배당률'] * (weights[n]/100)) for n in selected])

            st.markdown("### 🎯 포트폴리오 결과")
            st.metric("📈 가중 평균 연배당률", f"{avg_y:.2f}%")
            r1, r2, r3 = st.columns(3)
            r1.metric("월 수령액 (세후)", f"{total_m * 0.846:,.0f}원", delta="-15.4%", delta_color="inverse")
            r2.metric("월 수령액 (ISA/세전)", f"{total_m:,.0f}원", delta="100%", delta_color="normal")
            with r3:
                st.markdown(f"""<div style="background-color: #d4edda; color: #155724; padding: 15px; border-radius: 8px; border: 1px solid #c3e6cb; height: 100%; display: flex; flex-direction: column; justify-content: center;"><div style="font-weight: bold; font-size: 1.05em;">✅ 일반 계좌 대비 월 {total_m * 0.154:,.0f}원 이득!</div><div style="color: #6c757d; font-size: 0.8em; margin-top: 5px;">(비과세 및 과세이연 단순 가정입니다)</div></div>""", unsafe_allow_html=True)

            st.write("")
            c_data = pd.DataFrame({'계좌 종류': ['일반 계좌', 'ISA/연금계좌'], '월 수령액': [total_m * 0.846, total_m]})
            chart_compare = alt.Chart(c_data).mark_bar(cornerRadiusTopLeft=10, cornerRadiusTopRight=10).encode(x=alt.X('계좌 종류', sort=None, axis=alt.Axis(labelAngle=0, title=None)), y=alt.Y('월 수령액', title=None), color=alt.Color('계좌 종류', scale=alt.Scale(domain=['일반 계좌', 'ISA/연금계좌'], range=['#95a5a6', '#f1c40f']), legend=None), tooltip=[alt.Tooltip('계좌 종류'), alt.Tooltip('월 수령액', format=',.0f')]).properties(height=220)
            st.altair_chart(chart_compare, use_container_width=True)

            # =========================================================
            # [통합 캘린더 다운로드]
            # =========================================================
            st.divider()
            ics_data = logic.generate_portfolio_ics(all_data)

            st.subheader("📅 캘린더 일괄 등록")
            
            col_d1, col_d2 = st.columns([1.5, 1])
            with col_d1:
                st.caption("매번 버튼을 누르기 귀찮으신가요?")
                st.caption("아래 버튼으로 **모든 종목의 알림**을 한 번에 내 폰/PC 캘린더에 넣으세요.")
            
            with col_d2:
                if st.session_state.get("is_logged_in", False):
                    st.download_button(
                        label="📥 전체 일정 파일 받기 (.ics)",
                        data=ics_data,
                        file_name="dividend_calendar.ics",
                        mime="text/calendar",
                        use_container_width=True,
                        type="primary"
                    )
                else:
                    if st.button("📥 전체 일정 파일 받기 (.ics)", key="ics_lock_btn", use_container_width=True):
                        st.toast("🔒 로그인 회원만 '전체 다운로드'를 할 수 있습니다!", icon="🔒")

            # [가이드]
            with st.expander("❓ 다운로드 받은 파일은 어떻게 쓰나요? (사용법 보기)"):
                st.markdown("""
                **아주 간단합니다! 따라해 보세요.** 👇
                
                1. 위 **[전체 일정 파일 받기]** 버튼을 누르세요. (로그인 필요)
                2. 다운로드된 파일(`dividend_calendar.ics`)을 클릭(터치)해서 여세요.
                3. 스마트폰이나 PC에서 **"일정을 추가하시겠습니까?"** 라고 물어봅니다.
                4. **[추가]** 또는 **[저장]** 버튼만 누르면 끝!
                
                ---
                💡 **팁:** - **아이폰/갤럭시:** 파일이 열리면서 자동으로 캘린더 앱이 켜집니다.
                - **PC(컴퓨터):** 파일이 다운로드 폴더에 저장됩니다. 더블 클릭하면 아웃룩이나 기본 캘린더가 열립니다.
                """)
            
            # =========================================================
            # [저장 로직]
            # =========================================================
            st.write("") 
            with st.container(border=True):
                st.write("💾 **포트폴리오 저장 / 수정**")
                
                if not st.session_state.get('is_logged_in', False):
                    if "code" in st.query_params:
                         st.info("🔄 로그인 확인 중입니다... 잠시만 기다려주세요.")
                    else:
                        st.info("🔒 로그인이 필요합니다.")
                        st.caption("✅ **카카오 로그인을 추천합니다!** (네이버/카카오 앱에서도 바로 됩니다)")
                        
                        try:
                            ctx = get_script_run_ctx()
                            current_session_id = ctx.session_id
                        except:
                            current_session_id = "unknown"

                        # 카카오 로그인
                        try:
                            res_kakao = supabase.auth.sign_in_with_oauth({
                                "provider": "kakao",
                                "options": {
                                    "redirect_to": f"https://dividend-pange.streamlit.app?old_id={current_session_id}",
                                    "skip_browser_redirect": True
                                }
                            })
                            if res_kakao.url:
                                btn_kakao = f'''
                                <a href="{res_kakao.url}" target="_blank" style="
                                    display: inline-flex; justify-content: center; align-items: center; width: 100%;
                                    background-color: #FEE500; color: #000000; border: 1px solid rgba(0,0,0,0.05);
                                    padding: 0.8rem; border-radius: 0.5rem; text-decoration: none; font-weight: bold; font-size: 1.1em;
                                    box-shadow: 0 1px 2px rgba(0,0,0,0.1); margin-bottom: 10px;">
                                    💬 Kakao로 3초 만에 시작하기
                                </a>
                                '''
                                st.markdown(btn_kakao, unsafe_allow_html=True)
                        except Exception as e:
                            st.error(f"Kakao 오류: {e}")

                        # 구글 로그인
                        st.write("") 
                        st.markdown("---")
                        st.caption("🚨 **구글 로그인 안 되시나요?** (네이버/카카오 앱 보안 정책 때문입니다)")
                        st.caption("👉 화면 구석의 **[ ··· ]** 버튼 → **'다른 브라우저로 열기'**를 이용하시거나, 위쪽 **카카오 로그인**을 이용해 주세요.")
                        
                        if st.button("🔵 Google 로그인 (PC/크롬 추천)", key="save_google", use_container_width=True):
                            try:
                                res = supabase.auth.sign_in_with_oauth({
                                    "provider": "google",
                                    "options": {
                                        "redirect_to": f"https://dividend-pange.streamlit.app?old_id={current_session_id}",
                                        "queryParams": {"access_type": "offline", "prompt": "consent"},
                                        "skip_browser_redirect": False
                                    }
                                })
                                if res.url:
                                    st.markdown(f'<meta http-equiv="refresh" content="0;url={res.url}">', unsafe_allow_html=True)
                                    st.stop()
                            except Exception as e:
                                st.error(f"Google 오류: {e}")

                else:
                    # 로그인 성공
                    try:
                        user = st.session_state.user_info
                        save_mode = st.radio("방식 선택", ["✨ 새로 만들기", "🔄 기존 파일 수정"], horizontal=True, label_visibility="collapsed")
                        
                        save_data = {
                            "total_money": st.session_state.total_invest,
                            "composition": weights,
                            "summary": {"monthly": total_m, "yield": avg_y}
                        }

                        if save_mode == "✨ 새로 만들기":
                            c_new1, c_new2 = st.columns([2, 1])
                            p_name = c_new1.text_input("새 이름 입력", placeholder="비워두면 자동 이름", label_visibility="collapsed")
                            
                            if c_new2.button("새로 저장", type="primary", use_container_width=True):
                                final_name = p_name.strip()
                                if not final_name:
                                    cnt_res = supabase.table("portfolios").select("id", count="exact").eq("user_id", user.id).execute()
                                    next_num = (cnt_res.count or 0) + 1
                                    final_name = f"포트폴리오 {next_num}"
                                
                                supabase.table("portfolios").insert({
                                    "user_id": user.id, "user_email": user.email, "name": final_name, "ticker_data": save_data
                                }).execute()
                                
                                st.success(f"[{final_name}] 저장 완료!")
                                st.balloons()
                                time.sleep(1.0)
                                st.rerun()

                        else: 
                            exist_res = supabase.table("portfolios").select("id, name, created_at").eq("user_id", user.id).order("created_at", desc=True).execute()
                            if not exist_res.data:
                                st.warning("수정할 포트폴리오가 없습니다. 새로 만들어주세요.")
                            else:
                                exist_opts = {f"{p.get('name') or '이름없음'} ({p['created_at'][5:10]})": p['id'] for p in exist_res.data}
                                c_up1, c_up2 = st.columns([2, 1])
                                selected_label = c_up1.selectbox("수정할 파일 선택", list(exist_opts.keys()), label_visibility="collapsed")
                                target_id = exist_opts[selected_label]
                                
                                if c_up2.button("덮어쓰기", type="primary", use_container_width=True):
                                    supabase.table("portfolios").update({
                                        "ticker_data": save_data,
                                        "created_at": "now()"
                                    }).eq("id", target_id).execute()
                                    st.success("수정 완료! 내용이 업데이트되었습니다.")
                                    st.balloons()
                                    time.sleep(1.0)
                                    st.rerun()

                    except Exception as e:
                        st.error(f"오류 발생: {e}")
                        
            st.write("")
            st.info("""
            📢 **찾으시는 종목이 안 보이나요?**
        
            왼쪽 상단(모바일은 ↖ 메뉴 버튼)의 '📂 메뉴'를 누르고 
            '📃 전체 종목 리스트'를 선택하시면 전체 배당주를 확인하실 수 있습니다.
            """)

            if total_y_div > 20000000:
                st.warning(f"🚨 **주의:** 연간 예상 배당금이 **{total_y_div/10000:,.0f}만원**입니다. 금융소득종합과세 대상에 해당될 수 있습니다.")

            # 섹션 3: 상세 분석
            df_ana = pd.DataFrame(all_data)
            if not df_ana.empty:
                st.write("")
                tab_analysis, tab_simulation, tab_goal = st.tabs(["💎 자산 구성 분석", "💰 10년 뒤 자산 미리보기", "🎯 목표 배당 달성"])
                
                with tab_analysis:
                    chart_col, table_col = st.columns([1.2, 1])
                    def classify_currency(row):
                        try:
                            bunryu = str(row.get('분류', ''))
                            exch = str(row.get('환구분', ''))
                            name = str(row.get('종목', ''))
                            if bunryu == "해외" or "(해외)" in name or "환노출" in exch: return "🇺🇸 달러 자산"
                            return "🇰🇷 원화 자산"
                        except: return "🇰🇷 원화 자산"
                    
                    df_ana['통화'] = df_ana.apply(classify_currency, axis=1)
                    usd_ratio = df_ana[df_ana['통화'] == "🇺🇸 달러 자산"]['비중'].sum()
                    asset_sum = df_ana.groupby('자산유형').agg({'비중': 'sum', '투자금액_만원': 'sum', '종목': lambda x: ', '.join(x)}).reset_index()

                    with chart_col:
                        st.write("💎 **자산 유형 비중**")
                        donut = alt.Chart(asset_sum).mark_arc(innerRadius=60).encode(theta=alt.Theta("비중:Q"), color=alt.Color("자산유형:N", legend=alt.Legend(orient='bottom', title=None)), tooltip=[alt.Tooltip("자산유형"), alt.Tooltip("비중", format=".1f"), alt.Tooltip("투자금액_만원", format=",d"), alt.Tooltip("종목")]).properties(height=320)
                        st.altair_chart(donut, use_container_width=True)
                    
                    with table_col:
                        st.write("📋 **유형별 요약**")
                        st.dataframe(asset_sum.sort_values('비중', ascending=False), column_config={"비중": st.column_config.NumberColumn(format="%d%%"), "투자금액_만원": st.column_config.NumberColumn("투자금(만원)", format="%d"), "종목": st.column_config.TextColumn("포함 종목", width="large")}, hide_index=True, use_container_width=True)
                        st.divider()
                        st.markdown(f"**🌐 달러 자산 노출도: `{usd_ratio:.1f}%`**")
                        st.progress(usd_ratio / 100)
                        if usd_ratio >= 50: st.caption("💡 포트폴리오의 절반 이상이 환율 변동에 영향을 받습니다.")
                        else: st.caption("💡 원화 자산 중심의 구성입니다.")
                    
                    st.write("📋 **상세 포트폴리오**")
                    ui.render_custom_table(df_ana)
                    st.error("""**⚠️ 포트폴리오 분석 시 유의사항**
1. 과거의 데이터를 기반으로 한 단순 결과값이며, 실제 투자 수익을 보장하지 않습니다.
2. '달러 자산' 비율 실제 환노출 여부와 다를 수 있습니다 투자 전 확인이 필요합니다.
3. 실제 배당금 지급일과 금액은 운용사의 사정에 따라 변경될 수 있습니다.""")

                with tab_simulation:
                    # 나머지 시뮬레이션 코드는 매우 길어서 간략화
                    # 당신의 코드를 그대로 여기 붙여넣으면 됨
                    # (들여쓰기 4칸 유지)
                    pass


def render_stocklist_page(df):
#    """전체 종목 리스트 페이지"""
    
    st.info("💡 **이동 안내:** '코드' 클릭 시 블로그 분석글로, '🔗정보' 클릭 시 네이버/야후 금융 정보로 이동합니다. (**⭐ 표시는 상장 1년 미만 종목입니다.**)")
    tab_all, tab_kor, tab_usa = st.tabs(["🌎 전체", "🇰🇷 국내", "🇺🇸 해외"])
    with tab_all: 
        ui.render_custom_table(df)
    with tab_kor: 
        ui.render_custom_table(df[df['분류'] == '국내'])
    with tab_usa: 
        ui.render_custom_table(df[df['분류'] == '해외'])


def render_admin_panel(df_raw):
#    """관리자 패널"""
    pass
