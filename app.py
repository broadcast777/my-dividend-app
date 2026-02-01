"""
프로젝트: 배당 팽이 (Dividend Top) - 메인 애플리케이션
파일명: app.py
설명: 사용자 인터페이스(UI), 페이지 라우팅, 세션 관리
최종 정리: 2026.02.01 (대규모 리팩토링 - 1000줄 미만 달성)
"""

import streamlit as st
import pandas as pd
import altair as alt
import hashlib
import time
import random
from logger import logger
from analytics import inject_ga
import streamlit.components.v1 as components
import re

# 커스텀 모듈 로드
import logic
import ui
import db
import recommendation
import timeline
import analysis 
import constants as C
import simulation
import admin_ui      # 👈 [NEW] 관리자 기능 분리
import auth_manager  # 👈 [NEW] 로그인 기능 분리

# =============================================================================
# [SECTION 1] 기본 설정 및 초기화
# =============================================================================

st.set_page_config(page_title="배당팽이 포트폴리오", page_icon="🐌", layout="wide")

def init_session_state():
    """세션 상태 초기화"""
    defaults = {
        "is_logged_in": False, "user_info": None, "code_processed": False,
        "ai_modal_open": False, "age_verified": False,
        "total_invest": C.DEFAULT_INVEST_AMOUNT, "selected_stocks": [],
        "monthly_expense": C.DEFAULT_MONTHLY_EXPENSE, "ai_result_cache": None,
        "show_ai_login": False, "portfolio_map": {}
    }
    for key, value in defaults.items():
        if key not in st.session_state: st.session_state[key] = value

supabase = db.init_supabase()

# 인증 상태 체크 (auth_manager 위임)
auth_manager.check_auth_status(supabase)


# =============================================================================
# [SECTION 2] 공통 UI 컴포넌트
# =============================================================================

def render_install_guide():
    """앱 설치 안내 가이드"""
    with st.expander("📱 배당팽이를 앱(App)처럼 설치하는 법 (클릭)", expanded=False):
        st.markdown("""
        **매번 검색해서 들어오기 귀찮으셨죠?**<br>
        스마트폰 홈 화면에 아이콘을 추가하면 **1초 만에 접속**하실 수 있습니다.
        **⚠️ (필독) 네이버 앱으로 보고 계신가요?**
        네이버 앱에서는 구글 로그인이 차단될 수 있습니다. **'다른 브라우저'**로 여신 후 설치해 주세요!
        **1️⃣ 갤럭시 (안드로이드)**
        1. 네이버 앱 하단 **[새로고침 옆 네모(ㅁ)]** 클릭 → **[기본 브라우저로 열기]** 클릭
        2. 새 창이 뜨면 우측 상단/하단 메뉴에서 **[홈 화면에 추가]** 클릭!
        **2️⃣ 아이폰 (iOS)**
        1. 네이버 앱 우측 하단 **[더보기(≡) 또는 점 3개(⋮)]** 클릭 → **[Safari로 열기]** 클릭
        2. 사파리 하단 **[공유 버튼(네모 위 화살표)]** 누르고 **[홈 화면에 추가]** 클릭!
        """, unsafe_allow_html=True)
        
def render_sidebar_footer():
    """사이드바 하단: 후원 버튼"""
    bmc_url = "https://www.buymeacoffee.com/dividenpange"
    st.sidebar.markdown("---") 
    st.sidebar.markdown(f"""
        <div class="bmc-container">
            <a class="bmc-button" href="{bmc_url}" target="_blank">
                <img src="https://cdn.buymeacoffee.com/buttons/bmc-new-btn-logo.svg" alt="BMC logo" class="bmc-logo">
                <span>배당팽이에게 커피 한 잔</span>
            </a>
        </div>
    """, unsafe_allow_html=True)


# =============================================================================
# [SECTION 3] 메인 페이지 (계산기 / 로드맵 / 리스트)
# =============================================================================

@st.dialog("⚠️ 정말 삭제하시겠습니까?")
def confirm_delete_dialog(target_names, opts, supabase):
    """포트폴리오 삭제 확인 팝업"""
    st.write(f"선택하신 **{len(target_names)}개**의 포트폴리오가 영구적으로 삭제됩니다.")
    st.warning("이 작업은 되돌릴 수 없습니다.")
    col_del1, col_del2 = st.columns(2)
    if col_del1.button("✅ 네, 삭제합니다", type="primary", use_container_width=True):
        try:
            target_ids = [opts[name]['id'] for name in target_names]
            supabase.table("portfolios").delete().in_("id", target_ids).execute()
            logger.info(f"🗑️ 포트폴리오 일괄 삭제: {len(target_ids)}건")
            st.rerun()
        except Exception as e: st.error(f"삭제 중 오류 발생: {e}")
    if col_del2.button("취소", use_container_width=True): st.rerun()

@st.dialog("💾 기존 파일 덮어쓰기")
def confirm_overwrite_dialog(final_name, user_id, user_email, save_data, existing_id, supabase):
    """중복 이름 저장 시 덮어쓰기 확인 팝업"""
    st.write(f"이미 **'{final_name}'**이라는 이름의 포트폴리오가 존재합니다.")
    st.info("새로운 데이터로 덮어쓰시겠습니까?")
    col_ov1, col_ov2 = st.columns(2)
    if col_ov1.button("🎮 네, 덮어씁니다", type="primary", use_container_width=True):
        try:
            supabase.table("portfolios").update({"ticker_data": save_data, "created_at": "now()"}).eq("id", existing_id).execute()
            logger.info(f"🔄 기존 포트폴리오 덮어쓰기 완료: {final_name}")
            st.toast(f"'{final_name}' 파일을 성공적으로 갱신했습니다!", icon="✅")
            st.balloons()
            time.sleep(1.0)
            st.rerun()
        except Exception as e: st.error(f"저장 중 오류 발생: {e}")
    if col_ov2.button("아니요, 취소", use_container_width=True): st.rerun()

def render_calculator_page(df):
    """💰 배당금 계산기 & 시뮬레이터"""
    if st.session_state.get("ai_modal_open", False): recommendation.show_wizard()
    all_data = []
    
    with st.expander("🧮 나만의 배당 포트폴리오 시뮬레이션", expanded=True):
        col_total, col_select = st.columns([1, 2])
        
        # 종목 검색 최적화
        code_col_name = next((c for c in df.columns if '코드' in c), '종목코드')
        name_col_name = next((c for c in df.columns if 'pure' in c or '명' in c), '종목명')
        def clean_label(row):
            c = str(row.get(code_col_name, '')).strip().split('.')[0]
            if c.isdigit() and len(c) < 6: c = c.zfill(6)
            return f"{str(row.get(name_col_name, '')).strip()} ({c})"

        label_to_real_name = {clean_label(row): row['pure_name'] for _, row in df.iterrows()}
        search_options = sorted(list(label_to_real_name.keys()))
        
        default_labels = []
        if st.session_state.get('selected_stocks'):
            saved = st.session_state.selected_stocks
            for lbl, r_name in label_to_real_name.items():
                if r_name in saved: default_labels.append(lbl)

        selected_search = col_select.multiselect("📊 종목 선택", options=search_options, default=default_labels)
        selected = [label_to_real_name[opt] for opt in selected_search]
        st.session_state.selected_stocks = selected

        # 데이터 동기화 함수
        def sync_from_individual():
            new_sum = sum(st.session_state.get(f"amt_{i}", 0) for i in range(len(st.session_state.selected_stocks)))
            st.session_state.total_invest = new_sum * 10000
            st.session_state.total_invest_input = new_sum 
            st.session_state.portfolio_map = {st.session_state.selected_stocks[i]: st.session_state.get(f"amt_{i}", 0) for i in range(len(st.session_state.selected_stocks))}

        def sync_from_total():
            new_total = st.session_state.total_invest_input
            st.session_state.total_invest = new_total * 10000
            if not st.session_state.selected_stocks: return
            current_amts = [st.session_state.get(f"amt_{i}", 0) for i in range(len(st.session_state.selected_stocks))]
            current_sum = sum(current_amts)
            amounts_map = {}
            for i, stock in enumerate(st.session_state.selected_stocks):
                val = int(new_total * (current_amts[i] / current_sum)) if current_sum > 0 else int(new_total // len(st.session_state.selected_stocks))
                st.session_state[f"amt_{i}"] = val
                amounts_map[stock] = val
            st.session_state.portfolio_map = amounts_map

        # 선행 초기화
        if selected:
            init_sum = 0
            current_base_total = st.session_state.get("total_invest_input", 3000)
            for i, stock in enumerate(selected):
                key = f"amt_{i}"
                if key not in st.session_state:
                    ai_w = st.session_state.get('ai_suggested_weights', {}).get(stock)
                    st.session_state[key] = int(current_base_total * (ai_w / 100)) if ai_w and current_base_total > 0 else int(current_base_total // len(selected)) if len(selected) > 0 else 0
                init_sum += st.session_state[key]
            st.session_state.total_invest_input = init_sum
            st.session_state.total_invest = init_sum * 10000

        if "total_invest_input" not in st.session_state: st.session_state.total_invest_input = int(st.session_state.total_invest / 10000)
        col_total.number_input("💰 총 투자 자산 (만원)", min_value=0, step=100, key="total_invest_input", on_change=sync_from_total)

        # 개별 종목 입력 루프
        if selected:
            if any(df[df['pure_name'] == s].iloc[0]['분류'] == '해외' for s in selected):
                st.warning("📢 선택하신 종목 중 '해외 상장 ETF'가 포함되어 있습니다. ISA/연금계좌 결과는 참고용으로만 봐주세요.")
            
            temp_total_sum = 0
            amounts_map = {}
            cols_input = st.columns(2)
            current_total_view = st.session_state.total_invest_input if st.session_state.total_invest_input > 0 else 1
            
            for i, stock in enumerate(selected):
                with cols_input[i % 2]:
                    val = st.number_input(f"{stock} (만원)", min_value=0, step=10, key=f"amt_{i}", on_change=sync_from_individual)
                    temp_total_sum += val
                    amounts_map[stock] = val
                    
                    # 정보 표시
                    current_weight = (val / current_total_view * 100)
                    stock_match = df[df['pure_name'] == stock]
                    if not stock_match.empty:
                        s_row = stock_match.iloc[0]
                        ex_date = s_row.get('배당락일', '-')
                        info_text = f"**비중 {current_weight:.1f}%**"
                        date_msg = f" | 📅 {ex_date}" if ex_date and ex_date not in ['-', 'nan', 'None'] else " | 📅 미정"
                        
                        if len(selected) == 1 and ex_date and ex_date not in ['-', 'nan']:
                            cal_url = logic.get_google_cal_url(stock, ex_date)
                            if cal_url:
                                if st.session_state.get("is_logged_in"): st.link_button("📅 일정 등록", cal_url, use_container_width=True)
                                else: 
                                    if st.button("📅 일정 등록", key=f"btn_cal_{i}", use_container_width=True): st.toast("🔒 로그인 필요!", icon="🔒")
                            else: st.caption(f"{info_text}{date_msg}")
                        else: st.caption(f"{info_text}{date_msg}")
            
            st.session_state['portfolio_map'] = amounts_map
            if temp_total_sum * 10000 != st.session_state.total_invest: st.session_state.total_invest = temp_total_sum * 10000
            total_invest = st.session_state.total_invest

            # 데이터 생성
            weights = {s: (amounts_map[s]/temp_total_sum)*100 for s, amt in amounts_map.items()} if temp_total_sum > 0 else {s:0 for s in selected}
            for stock in selected:
                s_row = df[df['pure_name'] == stock].iloc[0]
                all_data.append({
                    '종목': stock, '비중': weights.get(stock, 0), '자산유형': s_row['자산유형'], 
                    '투자금액_만원': total_invest * (weights.get(stock, 0)/100) / 10000, '종목명': stock, 
                    '코드': s_row.get('코드', ''), '분류': s_row.get('분류', '국내'), '연배당률': s_row.get('연배당률', 0),
                    '환구분': s_row.get('환구분', '-'), '배당락일': s_row.get('배당락일', '-')
                })
            
            timeline.display_sidebar_roadmap(df, weights, total_invest)
            if len(selected) > 1: st.info("💡 종목이 많아 버튼 대신 배당일만 표시합니다. 전체 일정은 하단에서 다운로드하세요.")

            # 결과 요약
            total_y_div = sum([(total_invest * (weights[n]/100) * (df[df['pure_name']==n].iloc[0]['연배당률']/100)) for n in selected])
            total_m = total_y_div / 12
            avg_y = sum([(df[df['pure_name']==n].iloc[0]['연배당률'] * (weights[n]/100)) for n in selected])

            st.markdown("### 🎯 포트폴리오 결과")
            st.metric("📈 가중 평균 연배당률", f"{avg_y:.2f}%")
            r1, r2, r3 = st.columns(3)
            r1.metric("월 수령액 (세후)", f"{total_m * C.AFTER_TAX_RATIO:,.0f}원", delta="-15.4%", delta_color="inverse")
            r2.metric("월 수령액 (ISA/세전)", f"{total_m:,.0f}원", delta="100%", delta_color="normal")
            r3.success(f"✅ 일반 계좌 대비 월 {total_m * C.TAX_RATE_GENERAL:,.0f}원 이득!")

            # 차트
            st.write("")
            c_data = pd.DataFrame({'계좌 종류': ['일반 계좌', 'ISA/연금계좌'], '월 수령액': [total_m * C.AFTER_TAX_RATIO, total_m]})
            st.altair_chart(alt.Chart(c_data).mark_bar(cornerRadiusTopLeft=10).encode(
                x=alt.X('계좌 종류', axis=None), y=alt.Y('월 수령액'), color=alt.Color('계좌 종류', scale=alt.Scale(range=['#95a5a6', '#f1c40f']))
            ).properties(height=220), use_container_width=True)

            st.divider()
            
            # ICS 다운로드
            st.subheader("📅 배당 일정 등록")
            c_d1, c_d2 = st.columns([1.5, 1])
            c_d1.caption("내 폰/PC 캘린더에 전체 일정을 한 번에 넣으세요.")
            if st.session_state.get("is_logged_in"):
                c_d2.download_button("📥 전체 일정 파일 받기 (.ics)", logic.generate_portfolio_ics(all_data), "dividend_calendar.ics", "text/calendar", use_container_width=True, type="primary")
            else:
                if c_d2.button("📥 전체 일정 파일 받기 (.ics)", use_container_width=True): st.error("🔒 로그인 필요")

            # 저장 기능
            st.write("")
            with st.container(border=True):
                st.write("💾 **포트폴리오 저장 / 수정**")
                if not st.session_state.get('is_logged_in'): st.warning("⚠️ 로그인이 필요합니다.")
                else:
                    try:
                        user = st.session_state.user_info
                        save_mode = st.radio("방식", ["✨ 새로 만들기", "🔄 기존 수정"], horizontal=True, label_visibility="collapsed")
                        save_data = {"total_money": st.session_state.total_invest, "composition": weights, "summary": {"monthly": total_m, "yield": avg_y}, "monthly_expense": st.session_state.monthly_expense}

                        if save_mode == "✨ 새로 만들기":
                            c_n1, c_n2 = st.columns([2, 1])
                            p_name = c_n1.text_input("새 이름", placeholder="자동 이름", label_visibility="collapsed")
                            if c_n2.button("새로 저장", type="primary", use_container_width=True):
                                final_name = p_name.strip()
                                if not final_name:
                                    cnt = supabase.table("portfolios").select("id", count="exact").eq("user_id", user.id).execute()
                                    final_name = f"포트폴리오 {(cnt.count or 0) + 1}"
                                check = supabase.table("portfolios").select("id").eq("user_id", user.id).eq("name", final_name).execute()
                                if check.data: st.session_state.show_overwrite_dialog = {"name": final_name, "id": check.data[0]['id'], "data": save_data}
                                else:
                                    supabase.table("portfolios").insert({"user_id": user.id, "user_email": user.email, "name": final_name, "ticker_data": save_data}).execute()
                                    st.success(f"[{final_name}] 저장 완료!"); st.balloons(); time.sleep(1); st.rerun()
                        else:
                            exist = supabase.table("portfolios").select("id, name, created_at").eq("user_id", user.id).order("created_at", desc=True).execute()
                            if not exist.data: st.warning("수정할 포트폴리오가 없습니다.")
                            else:
                                opts = {f"{p.get('name') or '이름없음'} ({p['created_at'][5:10]})": p['id'] for p in exist.data}
                                sel_lbl = st.columns([2, 1])[0].selectbox("선택", list(opts.keys()), label_visibility="collapsed")
                                if st.columns([2, 1])[1].button("덮어쓰기", type="primary", use_container_width=True):
                                    st.session_state.show_overwrite_dialog = {"name": sel_lbl.split(" (")[0], "id": opts[sel_lbl], "data": save_data}
                        
                        if "show_overwrite_dialog" in st.session_state:
                            info = st.session_state.show_overwrite_dialog
                            del st.session_state.show_overwrite_dialog
                            confirm_overwrite_dialog(info["name"], user.id, user.email, info["data"], info["id"], supabase)
                    except Exception as e: st.error(f"오류: {e}")
            
            if total_y_div > 20000000: st.warning(f"🚨 **주의:** 연간 배당금 {total_y_div/10000:,.0f}만원 (금융소득종합과세 대상 가능)")

    df_ana = pd.DataFrame(all_data)
    if not df_ana.empty:
        st.write("")
        tab_options = ["💎 자산 구성 분석", "🧐 실제 보유 종목", "💰 10년 뒤 자산 미리보기", "🎯 목표 배당 달성"]
        selected_tab = st.segmented_control("main_tab", options=tab_options, default=tab_options[0], label_visibility="collapsed")
        if not selected_tab: selected_tab = tab_options[0]
        saved_monthly = st.session_state.get("shared_monthly_input", 150)
        st.write("")

        if selected_tab == "💎 자산 구성 분석": analysis.render_asset_allocation(df_ana)
        elif selected_tab == "🧐 실제 보유 종목":
            if st.session_state.total_invest > 0:
                user = st.session_state.get('user_info')
                u_name = user.email.split("@")[0] if (user and user.email) else "투자자"
                analysis.render_analysis(st.session_state.get('portfolio_map', {}), u_name, st.session_state.get('is_logged_in', False))
            else: st.info("👆 먼저 투자 금액과 종목을 설정해주세요.")
        elif selected_tab == "💰 10년 뒤 자산 미리보기": simulation.render_10y_sim_page(total_invest, avg_y, saved_monthly)
        elif selected_tab == "🎯 목표 배당 달성": simulation.render_goal_sim_page(selected, avg_y, total_invest)

def render_roadmap_page(df):
    """📅 월별 로드맵"""
    st.header("📅 나의 배당 월급 로드맵")
    selected = st.session_state.get('selected_stocks', [])
    if not selected: st.warning("⚠️ **'💰 배당금 계산기'**에서 종목을 먼저 선택하세요!"); st.stop()
    
    weights = {}
    temp_total = 0
    amounts = {}
    pf_cache = st.session_state.get('portfolio_map', {})
    for i, stock in enumerate(selected):
        val = pf_cache.get(stock, st.session_state.get(f"amt_{i}", 0))
        if val == 0 and st.session_state.total_invest > 0: val = int(st.session_state.total_invest / 10000 / len(selected))
        temp_total += val
        amounts[stock] = val
    if temp_total > 0: weights = {s: (amounts[s]/temp_total)*100 for s in selected}
    else: weights = {s: 0 for s in selected}

    timeline.render_toss_style_heatmap(df, weights, st.session_state.total_invest)
    if not st.session_state.get("is_logged_in", False):
        st.write("")
        with st.container(border=True):
            st.markdown("### 🔓 로그인 전용 기능"); st.write("✅ 내 폰으로 알림 받기 / 포트폴리오 저장")
            st.info("👆 상단 로그인 버튼을 이용해 주세요!")

def render_stocklist_page(df):
    """📃 종목 리스트"""
    st.header("📃 전체 종목 리스트")
    st.info("💡 **이동 안내:** '코드' 클릭 시 블로그 분석글로, '🔗정보' 클릭 시 금융 정보로 이동합니다.")
    
    search_opts = df.apply(lambda x: f"{x['종목명']} ({x['코드']})", axis=1).tolist() if not df.empty else []
    def classify_timing(text):
        import re
        t = str(text).strip()
        if any(k in t for k in ['월초', '초순', '1~']): return "🟢 월초 (1~10일)"
        if any(k in t for k in ['월말', '마지막', '말일', '하순']): return "🔴 월말 (21~31일)"
        m = re.search(r'(\d+)', t)
        if m:
            d = int(m.group(1))
            if 1<=d<=10: return "🟢 월초 (1~10일)"
            elif 11<=d<=20: return "🟡 월중 (11~20일)"
            elif 21<=d<=31: return "🔴 월말 (21~31일)"
        return "⚪ 기타/미정"
    if not df.empty: df['배당시기_temp'] = df['배당락일'].apply(classify_timing)

    with st.container():
        sel_items = st.multiselect("🔍 종목 검색", options=search_opts, placeholder="이름/코드 입력")
        st.write("")
        c1, c2 = st.columns(2)
        sel_type = c1.pills("🏷️ 자산 유형", ["전체"] + sorted(df['유형'].unique().tolist()) if not df.empty else ["전체"], default="전체")
        sel_time = c2.pills("📅 배당락 시기", ["전체", "🟢 월초 (1~10일)", "🟡 월중 (11~20일)", "🔴 월말 (21~31일)"], default="전체")

    df_f = df.copy()
    if sel_items:
        df_f['검색라벨'] = df_f.apply(lambda x: f"{x['종목명']} ({x['코드']})", axis=1)
        df_f = df_f[df_f['검색라벨'].isin(sel_items)].drop(columns=['검색라벨'])
    if sel_type != "전체": df_f = df_f[df_f['유형'] == sel_type]
    if sel_time != "전체": df_f = df_f[df_f['배당시기_temp'] == sel_time]
    if '배당시기_temp' in df_f.columns: df_f = df_f.drop(columns=['배당시기_temp'])

    if not df_f.empty: st.caption(f"📊 총 **{len(df_f)}개** 종목")
    else: st.warning("조건에 맞는 종목이 없습니다.")

    t1, t2, t3 = st.tabs(["🌎 전체", "🇰🇷 국내", "🇺🇸 해외"])
    with t1: ui.render_custom_table(df_f, key_suffix="all")
    with t2: ui.render_custom_table(df_f[df_f['분류'] == '국내'], key_suffix="kor")
    with t3: ui.render_custom_table(df_f[df_f['분류'] == '해외'], key_suffix="usa")

# =============================================================================
# [SECTION 6] 메인 실행
# =============================================================================

def main():
    init_session_state()
    ui.load_css()
    
    # 점검 모드 (Admin 파라미터로 우회 가능)
    if False and st.query_params.get("admin", "false").lower() != "true":
        st.title("🚧 서비스 점검 중"); st.stop()

    st.title("🐌 배당팽이 월배당 계산기")
    st.caption("나만의 배당 포트폴리오를 관리하고, 월별 예상 배당금을 확인하세요.")
    st.divider()
    inject_ga(); logger.info("🚀 App Started"); db.cleanup_old_tokens()

    # 관리자 모드
    is_admin = False
    if st.query_params.get("admin", "false").lower() == "true":
        with st.expander("🔐 관리자 접속", expanded=False):
            if hashlib.sha256(st.text_input("PW", type="password").encode()).hexdigest() == st.secrets["ADMIN_PASSWORD_HASH"]:
                is_admin = True; st.success("Admin Mode ON 🚀")

    auth_manager.render_login_ui(supabase)

    # 상단 로그인/AI 버튼
    with st.container(border=True):
        c_auth, c_ai = st.columns([2, 1.2])
        with c_auth:
            if not st.session_state.get("is_logged_in"): auth_manager.render_login_buttons(supabase, key_suffix="top_header")
            else: st.success(f"👋 **{st.session_state.user_info.email.split('@')[0]}**님 환영합니다!")
        with c_ai:
            if st.button("🕵️ AI 로보어드바이저", use_container_width=True, type="primary"):
                if st.session_state.get("is_logged_in"): st.session_state.ai_modal_open = True; st.session_state.wiz_step = 0
                else: st.toast("🔒 로그인 필요!", icon="👆")

    # 데이터 로드
    df_raw = logic.load_stock_data_from_csv()
    if df_raw.empty: st.stop()

    if is_admin:
        admin_ui.render_admin_tools(df_raw, supabase)
        admin_ui.render_etf_uploader(supabase) # [NEW] ETF 업로더도 admin_ui로 이동

    with st.spinner('⚙️ 엔진 가동 중...'):
        df = logic.load_and_process_data(df_raw, is_admin=is_admin)
        if df is not None and not df.empty and 'df_dirty' in st.session_state:
            try:
                auto_map = df.set_index('종목코드')['연배당금_크롤링_auto'].to_dict()
                st.session_state.df_dirty['연배당금_크롤링_auto'] = st.session_state.df_dirty['종목코드'].map(auto_map).fillna(st.session_state.df_dirty['연배당금_크롤링_auto'])
            except: pass

    # 사이드바
    with st.sidebar:
        if not st.session_state.is_logged_in: st.markdown("---")
        menu = st.radio("📂 **메뉴 이동**", ["💰 배당금 계산기", "📅 월별 로드맵", "📃 전체 종목 리스트"])
        st.markdown("---")
        st.session_state.monthly_expense = st.number_input("💸 월평균 지출 (만원)", min_value=10, value=st.session_state.monthly_expense, step=10)
        st.markdown("---")
        
        # 포트폴리오 관리 (불러오기/삭제)
        with st.expander("📂 불러오기 / 관리", expanded=True):
            if not st.session_state.is_logged_in: st.caption("🔒 로그인 필요")
            else:
                try:
                    uid = st.session_state.user_info.id
                    resp = supabase.table("portfolios").select("*").eq("user_id", uid).order("created_at", desc=True).execute()
                    if resp.data:
                        opts = {f"{p.get('name') or '이름없음'} ({p['created_at'][5:10]})": p for p in resp.data}
                        if st.toggle("🗑️ 정리 모드"):
                            dels = st.multiselect("삭제 목록", list(opts.keys()), label_visibility="collapsed")
                            if dels and st.button(f"🚨 {len(dels)}개 삭제", type="primary", use_container_width=True): confirm_delete_dialog(dels, opts, supabase)
                        else:
                            sel = st.selectbox("선택", list(opts.keys()), label_visibility="collapsed")
                            if st.button("📂 불러오기", use_container_width=True):
                                d = opts[sel]['ticker_data']
                                st.session_state.total_invest = int(d.get('total_money', 30000000))
                                st.session_state.selected_stocks = list(d.get('composition', {}).keys())
                                st.session_state.ai_suggested_weights = d.get('composition', {})
                                st.session_state.monthly_expense = int(d.get('monthly_expense', 200))
                                st.toast("로드 완료!", icon="✅"); time.sleep(0.5); st.rerun()
                    else: st.caption("기록 없음")
                except Exception as e: st.error(f"실패: {e}")
        
        st.markdown("---")
        with st.expander("📄 법적 고지"):
            st.caption("안전한 이용을 위해 정책을 준수합니다.")
            if st.button("🛡️ 개인정보 처리방침"):
                try: 
                    with open("privacy.md", "r", encoding="utf-8") as f: st.markdown(f.read())
                except: st.error("파일 없음")
        render_sidebar_footer()

    # 페이지 렌더링
    if menu == "💰 배당금 계산기": render_calculator_page(df)
    elif menu == "📅 월별 로드맵": render_roadmap_page(df)
    elif menu == "📃 전체 종목 리스트": render_stocklist_page(df)

    st.divider()
    st.caption("© 2025 **배당 팽이** | [📝 투자 일지](https://blog.naver.com/dividenpange)")
    st.write(""); render_install_guide()

if __name__ == "__main__":
    main()
