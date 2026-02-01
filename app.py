"""
프로젝트: 배당 팽이 (Dividend Top) - 메인 애플리케이션
파일명: app.py
설명: 사용자 인터페이스(UI), 페이지 라우팅, 세션 관리, 데이터 시각화 담당
최종 정리: 2026.01.30 (Supabase DB 연동 및 Admin 기능 추가)
"""

import streamlit as st
import pandas as pd
import altair as alt
import hashlib
import time
import random
from streamlit.runtime.scriptrunner import get_script_run_ctx
from logger import logger
from analytics import inject_ga
import streamlit.components.v1 as components
import re
from datetime import datetime, timedelta
import urllib.parse

# 커스텀 모듈 로드
import logic
import ui
import db
import recommendation
import timeline
import analysis  # 👈 [추가] 자산 분석 모듈 (X-Ray)
import constants as C
import simulation
import admin_ui
# =============================================================================
# [SECTION 1] 기본 설정 및 초기화
# =============================================================================

# 페이지 기본 설정 (모바일 최적화: centered -> wide)
st.set_page_config(
    page_title="배당팽이 포트폴리오",
    page_icon="🐌",
    layout="wide"  
)

def init_session_state():
    """
    세션 상태(Session State) 초기화
    - 로그인 상태, 사용자 정보, 포트폴리오 데이터 등 전역 변수 관리
    """
    defaults = {
        "is_logged_in": False,
        "user_info": None,
        "code_processed": False,
        "ai_modal_open": False,
        "age_verified": False,
        "total_invest": C.DEFAULT_INVEST_AMOUNT, 
        "selected_stocks": [],
        "monthly_expense": C.DEFAULT_MONTHLY_EXPENSE, 
        "ai_result_cache": None,
        "show_ai_login": False,
        "portfolio_map": {} # 페이지 이동 간 데이터 보존용 금고
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value

# DB 연결
supabase = db.init_supabase()


# =============================================================================
# [SECTION 2] 인증 시스템 (Supabase Auth)
# =============================================================================

def check_auth_status():
    """로그인 세션 확인 및 OAuth 콜백 처리"""
    if not supabase: return

    # 1. 기존 세션 확인
    try:
        session = supabase.auth.get_session()
        if session and session.user:
            st.session_state.is_logged_in = True
            st.session_state.user_info = session.user
            # URL 정리
            for key in ["code", "old_id"]:
                if key in st.query_params: del st.query_params[key]
            return 
    except Exception:
        pass

    # 2. OAuth 콜백 처리 (로그인 직후 리다이렉트)
    query_params = st.query_params
    if "code" in query_params and not st.session_state.get("code_processed", False):
        st.session_state.code_processed = True
        try:
            auth_code = query_params["code"]
            auth_response = supabase.auth.exchange_code_for_session({"auth_code": auth_code})
            session = auth_response.session
            if session and session.user:
                st.session_state.is_logged_in = True
                st.session_state.user_info = session.user
                logger.info(f"👤 사용자 로그인 성공: {session.user.email}")
            
            if "code" in st.query_params: del st.query_params["code"]
            st.success("✅ 로그인되었습니다!")
            st.rerun()
        except Exception as e:
            logger.error(f"🚨 [Auth Error] 인증 예외: {str(e)}", exc_info=True)
            # 토큰 갱신 이슈 발생 시 재시도 유도
            if "verifier" in str(e).lower() or "non-empty" in str(e).lower():
                st.warning("🔄 보안 토큰 갱신 중... 잠시만 기다려주세요.")
                for key in ["code", "old_id"]:
                    if key in st.query_params: del st.query_params[key]
                time.sleep(1.0)
                st.rerun()
            else:
                st.error(f"🔴 인증 오류: {e}")
                if "code" in st.query_params: del st.query_params["code"]

check_auth_status()


# =============================================================================
# [SECTION 3] 공통 UI 컴포넌트
# =============================================================================

def render_login_ui():
    """사이드바 상단: 로그인 사용자 정보 표시"""
    if not supabase: return
    is_logged_in = st.session_state.get("is_logged_in", False)
    user_info = st.session_state.get("user_info", None)
    
    if is_logged_in and user_info:
        email = user_info.email if user_info.email else "User"
        nickname = email.split("@")[0]
        
        with st.sidebar:
            st.markdown("---")
            st.success(f"👋 반가워요! **{nickname}**님")
            if st.button("🚪 로그아웃", key="logout_btn_sidebar", use_container_width=True):
                logger.info(f"🚪 사용자 로그아웃: {email}")
                supabase.auth.sign_out()
                st.session_state.is_logged_in = False
                st.session_state.user_info = None
                st.session_state.code_processed = False
                st.rerun()


def render_install_guide():
    """앱 설치 안내 가이드 (네이버 앱 대응)"""
    with st.expander("📱 배당팽이를 앱(App)처럼 설치하는 법 (클릭)", expanded=False):
        st.markdown("""
        **매번 검색해서 들어오기 귀찮으셨죠?**<br>
        스마트폰 홈 화면에 아이콘을 추가하면 **1초 만에 접속**하실 수 있습니다.

        **⚠️ (필독) 네이버 앱으로 보고 계신가요?**
        네이버 앱에서는 구글 로그인이 차단될 수 있습니다.
        아래 방법대로 **'다른 브라우저'**로 여신 후 설치해 주세요!

        **1️⃣ 갤럭시 (안드로이드)**
        1. 네이버 앱 하단 **[새로고침 옆 네모(ㅁ)]** 클릭
        2. **[기본 브라우저로 열기]** 클릭 (삼성 인터넷/크롬 등)
        3. 새 창이 뜨면 우측 상단/하단 메뉴에서 **[홈 화면에 추가]** 클릭!

        **2️⃣ 아이폰 (iOS)**
        1. 네이버 앱 우측 하단 **[더보기(≡) 또는 점 3개(⋮)]** 클릭
        2. **[Safari로 열기]** 클릭
        3. 사파리 하단 **[공유 버튼(네모 위 화살표)]** 누르고 **[홈 화면에 추가]** 클릭!
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

def render_login_buttons(key_suffix="default"):
    """소셜 로그인 버튼 렌더링 (카카오/구글)"""
    try:
        ctx = get_script_run_ctx()
        current_session_id = ctx.session_id
    except: current_session_id = "unknown"
    redirect_url = f"https://dividend-pange.streamlit.app?old_id={current_session_id}"

    if key_suffix != "top_header":
        st.caption("🔒 기능을 사용하려면 로그인이 필요합니다.")
        
    col1, col2 = st.columns(2)
    with col1:
        try:
            res_kakao = supabase.auth.sign_in_with_oauth({"provider": "kakao", "options": {"redirect_to": redirect_url, "skip_browser_redirect": True}})
            if res_kakao.url:
                st.markdown(f'''<a href="{res_kakao.url}" target="_blank" class="kakao-login-btn">💬 카카오로 3초 만에 시작</a>''', unsafe_allow_html=True)
        except: st.error("Kakao 오류")
    with col2:
        if st.button("🔵 Google로 시작하기(PC/크롬 권장)", key=f"btn_google_{key_suffix}", use_container_width=True):
            try:
                res_google = supabase.auth.sign_in_with_oauth({"provider": "google", "options": {"redirect_to": redirect_url, "queryParams": {"access_type": "offline", "prompt": "consent"}, "skip_browser_redirect": False}})
                if res_google.url:
                    st.markdown(f'<meta http-equiv="refresh" content="0;url={res_google.url}">', unsafe_allow_html=True)
                    st.stop()
            except: pass


# =============================================================================
# [SECTION 4] 관리자 도구 (Admin Tools)
# =============================================================================



# =============================================================================
# [SECTION 5] 메인 페이지 (계산기 / 로드맵 / 리스트)
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
        except Exception as e:
            st.error(f"삭제 중 오류 발생: {e}")
            
    if col_del2.button("취소", use_container_width=True):
        st.rerun()

@st.dialog("💾 기존 파일 덮어쓰기")
def confirm_overwrite_dialog(final_name, user_id, user_email, save_data, existing_id, supabase):
    """중복 이름 저장 시 덮어쓰기 확인 팝업"""
    st.write(f"이미 **'{final_name}'**이라는 이름의 포트폴리오가 존재합니다.")
    st.info("새로운 데이터로 덮어쓰시겠습니까?")
    
    col_ov1, col_ov2 = st.columns(2)
    
    if col_ov1.button("🎮 네, 덮어씁니다", type="primary", use_container_width=True):
        try:
            supabase.table("portfolios").update({
                "ticker_data": save_data, 
                "created_at": "now()"
            }).eq("id", existing_id).execute()
            
            logger.info(f"🔄 기존 포트폴리오 덮어쓰기 완료: {final_name}")
            st.toast(f"'{final_name}' 파일을 성공적으로 갱신했습니다!", icon="✅")
            st.balloons()
            time.sleep(1.0)
            st.rerun()
        except Exception as e:
            st.error(f"저장 중 오류 발생: {e}")
            
    if col_ov2.button("아니요, 취소", use_container_width=True):
        st.rerun()

def render_calculator_page(df):
    """💰 배당금 계산기 & 시뮬레이터"""
    
    if st.session_state.get("ai_modal_open", False):
        recommendation.show_wizard()
    
    all_data = []
    
    with st.expander("🧮 나만의 배당 포트폴리오 시뮬레이션", expanded=True):
        # 1. 레이아웃 (좌측 총액 / 우측 종목선택)
        col_total, col_select = st.columns([1, 2])

        # 종목 검색 최적화 (이름 + 코드)
        code_col_name = next((c for c in df.columns if '코드' in c), '종목코드')
        name_col_name = next((c for c in df.columns if 'pure' in c or '명' in c), '종목명')

        def clean_label(row):
            c = str(row.get(code_col_name, '')).strip()
            if '.' in c: c = c.split('.')[0]
            if c.isdigit() and len(c) < 6: c = c.zfill(6)
            n = str(row.get(name_col_name, '')).strip()
            return f"{n} ({c})"

        label_to_real_name = {}
        for _, row in df.iterrows():
            lbl = clean_label(row)
            label_to_real_name[lbl] = row['pure_name']

        search_options = sorted(list(label_to_real_name.keys()))
        
        default_selected_labels = []
        if st.session_state.get('selected_stocks'):
            saved_stocks = st.session_state.selected_stocks
            for label, real_name in label_to_real_name.items():
                if real_name in saved_stocks:
                    default_selected_labels.append(label)

        # 종목 선택기
        selected_search = col_select.multiselect(
            "📊 종목 선택 (이름 또는 코드로 검색)", 
            options=search_options, 
            default=default_selected_labels, 
            help="종목코드(숫자)나 종목명을 입력해 보세요!"
        )
        selected = [label_to_real_name[opt] for opt in selected_search]
        st.session_state.selected_stocks = selected

        # 데이터 동기화 함수들 (Top-down / Bottom-up)
        def sync_from_individual():
            new_sum = 0
            amounts_map = {}
            for i, stock in enumerate(st.session_state.selected_stocks):
                val = st.session_state.get(f"amt_{i}", 0)
                new_sum += val
                amounts_map[stock] = val
            
            st.session_state.total_invest = new_sum * 10000
            st.session_state.total_invest_input = new_sum 
            st.session_state.portfolio_map = amounts_map

        def sync_from_total():
            new_total = st.session_state.total_invest_input
            st.session_state.total_invest = new_total * 10000
            
            if not st.session_state.selected_stocks: return

            current_amts = [st.session_state.get(f"amt_{i}", 0) for i in range(len(st.session_state.selected_stocks))]
            current_sum = sum(current_amts)
            
            amounts_map = {}
            for i, stock in enumerate(st.session_state.selected_stocks):
                if current_sum > 0:
                    ratio = current_amts[i] / current_sum
                    val = int(new_total * ratio)
                else:
                    val = int(new_total // len(st.session_state.selected_stocks))
                
                st.session_state[f"amt_{i}"] = val
                amounts_map[stock] = val
            
            st.session_state.portfolio_map = amounts_map

        # 선행 초기화 (값 없을 때)
        if selected:
            init_sum = 0
            current_base_total = st.session_state.get("total_invest_input", 3000)
            
            for i, stock in enumerate(selected):
                key = f"amt_{i}"
                if key not in st.session_state:
                    ai_suggested = st.session_state.get('ai_suggested_weights', {})
                    if stock in ai_suggested and current_base_total > 0:
                        w = ai_suggested[stock]
                        init_val = int(current_base_total * (w / 100))
                    else:
                        init_val = int(current_base_total // len(selected)) if len(selected) > 0 else 0
                    st.session_state[key] = init_val
                
                init_sum += st.session_state[key]
            
            st.session_state.total_invest_input = init_sum
            st.session_state.total_invest = init_sum * 10000

        # 총액 입력창
        if "total_invest_input" not in st.session_state:
            st.session_state.total_invest_input = int(st.session_state.total_invest / 10000)

        col_total.number_input(
            "💰 총 투자 자산 (만원)", 
            min_value=0, 
            step=100, 
            key="total_invest_input", 
            on_change=sync_from_total,
            help="이 금액을 수정하면 아래 종목들에 비율대로 자동 배분됩니다."
        )

        # 개별 종목 입력 루프
        if selected:
            has_foreign_stock = any(df[df['pure_name'] == s_name].iloc[0]['분류'] == '해외' for s_name in selected)
            if has_foreign_stock:
                st.warning("📢 **잠깐!** 선택하신 종목 중 '해외 상장 ETF'가 포함되어 있습니다. ISA/연금계좌 결과는 참고용으로만 봐주세요.")

            temp_total_sum = 0
            amounts_map = {}
            cols_input = st.columns(2)
            
            current_total_view = st.session_state.total_invest_input if st.session_state.total_invest_input > 0 else 1
            
            for i, stock in enumerate(selected):
                
                with cols_input[i % 2]:
                    val = st.number_input(
                        f"{stock} (만원)", 
                        min_value=0, 
                        step=10, 
                        key=f"amt_{i}", 
                        on_change=sync_from_individual
                    )
                    temp_total_sum += val
                    amounts_map[stock] = val
                    
                    # 비중 & 배당일 정보 표시
                    current_weight = (val / current_total_view * 100)
                    stock_match = df[df['pure_name'] == stock]
                    
                    if not stock_match.empty:
                        s_row = stock_match.iloc[0]
                        ex_date_view = s_row.get('배당락일', '-')
                        
                        info_text = f"**종목 비중 {current_weight:.1f}%**"
                        
                        if ex_date_view and ex_date_view not in ['-', 'nan', 'None']:
                            date_msg = f" | 📅 {ex_date_view}"
                            
                            if len(selected) == 1:
                                cal_url = logic.get_google_cal_url(stock, ex_date_view)
                                if cal_url:
                                    st.caption(f"{info_text}{date_msg}")
                                    
                                    if st.session_state.get("is_logged_in", False):
                                        st.link_button("📅 배당 일정 등록", cal_url, use_container_width=True)
                                    else:
                                        if st.button("📅 배당 일정 등록", key=f"btn_cal_indi_{i}", use_container_width=True):
                                            st.toast("🔒 로그인 회원만 일정을 등록할 수 있습니다!", icon="🔒")
                                else:
                                    st.caption(f"{info_text}{date_msg}")
                            else:
                                st.caption(f"{info_text}{date_msg}")
                        else:
                            st.caption(f"{info_text} | 📅 날짜 미정")
            
            # 데이터 백업
            st.session_state['portfolio_map'] = amounts_map

            # 오차 보정
            if temp_total_sum * 10000 != st.session_state.total_invest:
                 st.session_state.total_invest = temp_total_sum * 10000
            total_invest = st.session_state.total_invest

            # 비중 계산 및 결과 데이터 생성
            weights = {}
            if temp_total_sum > 0:
                for s, amt in amounts_map.items():
                    weights[s] = (amt / temp_total_sum) * 100
            else:
                for s in selected: weights[s] = 0

            for stock in selected:
                stock_match = df[df['pure_name'] == stock]
                if not stock_match.empty:
                    s_row = stock_match.iloc[0]
                    w = weights.get(stock, 0)
                    amt = total_invest * (w / 100)
                    all_data.append({
                        '종목': stock, '비중': w, '자산유형': s_row['자산유형'], '투자금액_만원': amt / 10000,
                        '종목명': stock, '코드': s_row.get('코드', ''), '분류': s_row.get('분류', '국내'),
                        '연배당률': s_row.get('연배당률', 0), '금융링크': s_row.get('금융링크', '#'),
                        '신규상장개월수': s_row.get('신규상장개월수', 0), '현재가': s_row.get('현재가', 0),
                        '환구분': s_row.get('환구분', '-'), '배당락일': s_row.get('배당락일', '-')
                    })
            
            # 사이드바 로드맵
            timeline.display_sidebar_roadmap(df, weights, total_invest)
            
            if len(selected) > 1:
                st.markdown("""
                    <div style="padding: 12px; border-radius: 8px; background-color: #f0f7ff; border: 1px solid #d0e8ff; margin: 15px 0;">
                        <small style="color: #0068c9; font-weight: bold;">💡 안내</small><br>
                        <small style="color: #555;">종목이 많아 가독성을 위해 개별 버튼 대신 배당일만 표시합니다.<br>
                        모든 일정은 <b>화면 하단의 [📅 배당 일정 등록]</b>에서 한 번에 저장하세요!</small>
                    </div>
                """, unsafe_allow_html=True)

            # 결과 요약 (월 배당금)
            total_y_div = sum([(total_invest * (weights[n]/100) * (df[df['pure_name']==n].iloc[0]['연배당률']/100)) for n in selected])
            total_m = total_y_div / 12
            avg_y = sum([(df[df['pure_name']==n].iloc[0]['연배당률'] * (weights[n]/100)) for n in selected])

            st.markdown("### 🎯 포트폴리오 결과")
            st.metric("📈 가중 평균 연배당률", f"{avg_y:.2f}%")
            
            r1, r2, r3 = st.columns(3)
            r1.metric("월 수령액 (세후)", f"{total_m * C.AFTER_TAX_RATIO:,.0f}원", delta="-15.4%", delta_color="inverse")
            r2.metric("월 수령액 (ISA/세전)", f"{total_m:,.0f}원", delta="100%", delta_color="normal")
            with r3:
                st.markdown(f"""<div style="background-color: #d4edda; color: #155724; padding: 15px; border-radius: 8px; border: 1px solid #c3e6cb; height: 100%; display: flex; flex-direction: column; justify-content: center;"><div style="font-weight: bold; font-size: 1.05em;">✅ 일반 계좌 대비 월 {total_m * C.TAX_RATE_GENERAL:,.0f}원 이득!</div><div style="color: #6c757d; font-size: 0.8em; margin-top: 5px;">(비과세 및 과세이연 단순 가정입니다)</div></div>""", unsafe_allow_html=True)

            # 차트 시각화
            st.write("")
            c_data = pd.DataFrame({'계좌 종류': ['일반 계좌', 'ISA/연금계좌'], '월 수령액': [total_m * C.AFTER_TAX_RATIO, total_m]})
            chart_compare = alt.Chart(c_data).mark_bar(cornerRadiusTopLeft=10, cornerRadiusTopRight=10).encode(
                x=alt.X('계좌 종류', sort=None, axis=alt.Axis(labelAngle=0, title=None)), 
                y=alt.Y('월 수령액', title=None), 
                color=alt.Color('계좌 종류', scale=alt.Scale(domain=['일반 계좌', 'ISA/연금계좌'], range=['#95a5a6', '#f1c40f']), legend=None), 
                tooltip=[alt.Tooltip('계좌 종류'), alt.Tooltip('월 수령액', format=',.0f')]
            ).properties(height=220)
            st.altair_chart(chart_compare, use_container_width=True)

  

            st.divider()
            
            # ICS 파일 생성 및 다운로드
            ics_data = logic.generate_portfolio_ics(all_data)
            st.subheader("📅 배당 일정 등록")
            col_d1, col_d2 = st.columns([1.5, 1])
            with col_d1:
                st.caption("매번 버튼을 누르기 귀찮으신가요?")
                st.caption("아래 버튼으로 **모든 종목의 알림**을 한 번에 내 폰/PC 캘린더에 넣으세요.")
            with col_d2:
                if st.session_state.get("is_logged_in", False):
                    st.download_button(label="📥 전체 일정 파일 받기 (.ics)", data=ics_data, file_name="dividend_calendar.ics", mime="text/calendar", use_container_width=True, type="primary")
                else:
                    if st.button("📥 전체 일정 파일 받기 (.ics)", key="ics_lock_btn", use_container_width=True):
                        st.error("🔒 로그인 회원 전용 기능입니다. 로그인을 완료해 주세요!")
                        st.toast("로그인이 필요합니다!", icon="🔒")

            with st.expander("❓ 다운로드 받은 파일은 어떻게 쓰나요? (사용법 보기)"):
                st.markdown("""
                **아주 간단합니다! 따라해 보세요.** 👇
                1. 위 **[전체 일정 파일 받기]** 버튼을 누르세요. (로그인 필요)
                2. 다운로드된 파일(`dividend_calendar.ics`)을 클릭(터치)해서 여세요.
                3. 스마트폰이나 PC에서 **"일정을 추가하시겠습니까?"** 라고 물어봅니다.
                4. **[추가]** 또는 **[저장]** 버튼만 누르면 끝!
                """)
            
            st.write("") 
            
            # 포트폴리오 저장 기능
            with st.container(border=True):
                st.write("💾 **포트폴리오 저장 / 수정**")
                if not st.session_state.get('is_logged_in', False):
                    st.warning("⚠️ **로그인이 필요합니다.**")
                    st.markdown("""나만의 포트폴리오를 저장하고 관리하시려면 페이지 최상단(맨 위)에 있는 로그인을 이용해 주세요.""")
                else:
                    try:
                        user = st.session_state.user_info
                        save_mode = st.radio("방식 선택", ["✨ 새로 만들기", "🔄 기존 파일 수정"], horizontal=True, label_visibility="collapsed")
                        save_data = {"total_money": st.session_state.total_invest, "composition": weights, "summary": {"monthly": total_m, "yield": avg_y}, "monthly_expense": st.session_state.monthly_expense}

                        if save_mode == "✨ 새로 만들기":
                            c_new1, c_new2 = st.columns([2, 1])
                            p_name = c_new1.text_input("새 이름 입력", placeholder="비워두면 자동 이름", label_visibility="collapsed")
                            
                            if c_new2.button("새로 저장", type="primary", use_container_width=True):
                                final_name = p_name.strip()
                                if not final_name:
                                    cnt_res = supabase.table("portfolios").select("id", count="exact").eq("user_id", user.id).execute()
                                    next_num = (cnt_res.count or 0) + 1
                                    final_name = f"포트폴리오 {next_num}"
                                
                                # 중복 체크
                                check_res = supabase.table("portfolios").select("id").eq("user_id", user.id).eq("name", final_name).execute()
                                
                                if check_res.data:
                                    st.session_state.show_overwrite_dialog = {
                                        "name": final_name,
                                        "id": check_res.data[0]['id'],
                                        "data": save_data
                                    }
                                else:
                                    supabase.table("portfolios").insert({"user_id": user.id, "user_email": user.email, "name": final_name, "ticker_data": save_data}).execute()
                                    logger.info(f"💾 새 포트폴리오 저장: {final_name}")
                                    st.success(f"[{final_name}] 저장 완료!")
                                    st.balloons()
                                    time.sleep(1.0)
                                    st.rerun()

                        else: # 수정 모드
                            exist_res = supabase.table("portfolios").select("id, name, created_at").eq("user_id", user.id).order("created_at", desc=True).execute()
                            if not exist_res.data:
                                st.warning("수정할 포트폴리오가 없습니다. 새로 만들어주세요.")
                            else:
                                exist_opts = {f"{p.get('name') or '이름없음'} ({p['created_at'][5:10]})": p['id'] for p in exist_res.data}
                                c_up1, c_up2 = st.columns([2, 1])
                                selected_label = c_up1.selectbox("수정할 파일 선택", list(exist_opts.keys()), label_visibility="collapsed")
                                target_id = exist_opts[selected_label]
                                target_name = selected_label.split(" (")[0]

                                if c_up2.button("덮어쓰기", type="primary", use_container_width=True):
                                    st.session_state.show_overwrite_dialog = {
                                        "name": target_name,
                                        "id": target_id,
                                        "data": save_data
                                    }

                        # 덮어쓰기 팝업 실행
                        if "show_overwrite_dialog" in st.session_state:
                            info = st.session_state.show_overwrite_dialog
                            del st.session_state.show_overwrite_dialog
                            confirm_overwrite_dialog(info["name"], user.id, user.email, info["data"], info["id"], supabase)

                    except Exception as e:
                        st.error(f"오류 발생: {e}")
            
            st.write("")
            st.info("""📢 **찾으시는 종목이 안 보이나요?**\n왼쪽 상단(모바일은 ↖ 메뉴 버튼)의 '📂 메뉴'를 누르고 '📃 전체 종목 리스트'를 선택하시면 전체 배당주를 확인하실 수 있습니다.""")
            if total_y_div > 20000000:
                st.warning(f"🚨 **주의:** 연간 예상 배당금이 **{total_y_div/10000:,.0f}만원**입니다. 금융소득종합과세 대상에 해당될 수 있습니다.")

    df_ana = pd.DataFrame(all_data)
    if not df_ana.empty:
        st.write("")
        
        # 메인 분석 탭 (Segmented Control)
        tab_options = ["💎 자산 구성 분석", "🧐 실제 보유 종목", "💰 10년 뒤 자산 미리보기", "🎯 목표 배당 달성"]
        selected_tab = st.segmented_control(
            "main_tab_nav",
            options=tab_options,
            default=tab_options[0],
            selection_mode="single",
            label_visibility="collapsed"
        )
        if not selected_tab: selected_tab = tab_options[0]

        saved_monthly = st.session_state.get("shared_monthly_input", 150)
        
        st.write("")

        # 1. 자산 구성 분석
        if selected_tab == "💎 자산 구성 분석":
            # [수정] 자산 분석 차트/표 그리기도 analysis.py로 이사 갔습니다!
            analysis.render_asset_allocation(df_ana)
            
        # [수정 후] 탭 이름에 맞춰 조건문과 설명 멘트도 수정
        elif selected_tab == "🧐 실제 보유 종목":

            if st.session_state.total_invest > 0:
                # 사용자 정보 및 포트폴리오 가져오기
                user_info_obj = st.session_state.get('user_info')
                user_name_val = user_info_obj.email.split("@")[0] if (user_info_obj and user_info_obj.email) else "투자자"
                is_login_val = st.session_state.get('is_logged_in', False)
                current_pf = st.session_state.get('portfolio_map', {})
                
                # 분석 모듈 호출
                if current_pf:
                    analysis.render_analysis(current_pf, user_name_val, is_login_val)
                else:
                    st.info("분석할 데이터가 없습니다.")
            else:
                st.info("👆 먼저 투자 금액과 종목을 설정해주세요.")
                
        # 2. 10년 뒤 자산 시뮬레이션
        elif selected_tab == "💰 10년 뒤 자산 미리보기":
            # [수정] 복잡한 시뮬레이션 UI와 로직은 simulation.py로 이사 갔습니다!
            simulation.render_10y_sim_page(total_invest, avg_y, saved_monthly)        
    

       
        # 3. 목표 배당 달성 (역산기)
        elif selected_tab == "🎯 목표 배당 달성":
            # [수정] 역산기 UI와 로직도 simulation.py로 이사 갔습니다!
            simulation.render_goal_sim_page(selected, avg_y, total_invest)
                    
def render_roadmap_page(df):
    """📅 월별 로드맵 페이지"""
    st.header("📅 나의 배당 월급 로드맵")
    st.info("💡 종목별 배당 주기를 반영한 데이터입니다. (로그인 없이 이용 가능)")

    selected = st.session_state.get('selected_stocks', [])
    if not selected:
        st.warning("⚠️ **'💰 배당금 계산기'** 메뉴에서 종목을 먼저 선택해 주세요!")
        st.stop()
    
    weights = {}
    temp_total = 0
    amounts = {}
    
    portfolio_cache = st.session_state.get('portfolio_map', {})

    for i, stock in enumerate(selected):
        if stock in portfolio_cache:
            val = portfolio_cache[stock]
        else:
            val = st.session_state.get(f"amt_{i}", 0)
        
        if val == 0 and st.session_state.total_invest > 0:
             val = int(st.session_state.total_invest / 10000 / len(selected))

        temp_total += val
        amounts[stock] = val
        
    if temp_total > 0:
        for stock in selected:
            weights[stock] = (amounts[stock] / temp_total) * 100
    else:
        for stock in selected: weights[stock] = 0

    timeline.render_toss_style_heatmap(df, weights, st.session_state.total_invest)

    if not st.session_state.get("is_logged_in", False):
        st.write("")
        with st.container(border=True):
            st.markdown("### 🔓 로그인이 필요한 기능")
            col_lock1, col_lock2 = st.columns(2)
            with col_lock1:
                st.write("✅ **내 폰으로 배당 알림 받기**")
                st.caption("전체 일정을 .ics 파일로 내려받아 캘린더에 1초 만에 등록하세요.")
            with col_lock2:
                st.write("✅ **설계한 포트폴리오 저장**")
                st.caption("매번 입력할 필요 없이 언제든 다시 불러올 수 있습니다.")
            st.info("👆 페이지 최상단의 로그인 버튼을 이용해 주세요!")
            
def render_stocklist_page(df):
    """📃 전체 종목 리스트 페이지 (검색/필터)"""
    
    st.header("📃 전체 종목 리스트")
    st.info("💡 **이동 안내:** '코드' 클릭 시 블로그 분석글로, '🔗정보' 클릭 시 네이버/야후 금융 정보로 이동합니다. (**⭐ 표시는 상장 1년 미만 종목입니다.**)")
    
    if not df.empty:
        search_options = df.apply(lambda x: f"{x['종목명']} ({x['코드']})", axis=1).tolist()
        
        # 배당 시기 자동 분류
        def classify_timing(text):
            import re
            t = str(text).strip()
            if any(k in t for k in ['월초', '초순', '1~']): return "🟢 월초 (1~10일)"
            if any(k in t for k in ['월말', '마지막', '말일', '하순']): return "🔴 월말 (21~31일)"
            
            match = re.search(r'(\d+)', t)
            if match:
                day = int(match.group(1))
                if 1 <= day <= 10: return "🟢 월초 (1~10일)"
                if 11 <= day <= 20: return "🟡 월중 (11~20일)"
                if 21 <= day <= 31: return "🔴 월말 (21~31일)"
                
            return "⚪ 기타/미정"
            
        df['배당시기_temp'] = df['배당락일'].apply(classify_timing)
    else:
        search_options = []

    # 검색 및 필터 UI
    with st.container():
        col_search = st.columns([1])[0]
        with col_search:
            selected_items = st.multiselect(
                "🔍 종목 검색", 
                options=search_options, 
                placeholder="이름/코드 입력 (자동완성)"
            )
        
        st.write("") 

        col_f1, col_f2 = st.columns(2)
        with col_f1:
            if not df.empty and '유형' in df.columns:
                unique_types = ["전체"] + sorted(df['유형'].unique().tolist())
            else:
                unique_types = ["전체"]
            selected_type = st.pills("🏷️ 자산 유형", unique_types, default="전체", selection_mode="single")

        with col_f2:
            timing_options = ["전체", "🟢 월초 (1~10일)", "🟡 월중 (11~20일)", "🔴 월말 (21~31일)"]
            selected_timing = st.pills("📅 배당락 시기", timing_options, default="전체", selection_mode="single")

    # 필터링 로직
    df_filtered = df.copy()
    if selected_items:
        df_filtered['검색라벨_temp'] = df_filtered.apply(lambda x: f"{x['종목명']} ({x['코드']})", axis=1)
        df_filtered = df_filtered[df_filtered['검색라벨_temp'].isin(selected_items)]
        df_filtered = df_filtered.drop(columns=['검색라벨_temp'])
        
    if selected_type and selected_type != "전체":
        df_filtered = df_filtered[df_filtered['유형'] == selected_type]
        
    if selected_timing and selected_timing != "전체":
        df_filtered = df_filtered[df_filtered['배당시기_temp'] == selected_timing]

    if '배당시기_temp' in df_filtered.columns:
        df_filtered = df_filtered.drop(columns=['배당시기_temp'])

    if not df_filtered.empty:
        st.caption(f"📊 총 **{len(df_filtered)}개** 종목이 표시됩니다.")
    else:
        st.warning("조건에 맞는 종목이 없습니다.")
    
    # ---------------------------------------------------------------
    # [핵심 수정] 각 탭마다 key_suffix를 다르게 지정하여 중복 에러 해결
    # ---------------------------------------------------------------
    tab_all, tab_kor, tab_usa = st.tabs(["🌎 전체", "🇰🇷 국내", "🇺🇸 해외"])
    
    with tab_all: 
        ui.render_custom_table(df_filtered, key_suffix="all") # key="all"
        
    with tab_kor: 
        ui.render_custom_table(df_filtered[df_filtered['분류'] == '국내'], key_suffix="kor") # key="kor"
        
    with tab_usa: 
        ui.render_custom_table(df_filtered[df_filtered['분류'] == '해외'], key_suffix="usa") # key="usa"
        
# =============================================================================
# [SECTION 6] 메인 실행 함수 (진입점)
# =============================================================================

def main():
    # 1. 초기화 및 설정
    init_session_state() 
    ui.load_css() 
    
    # =================================================
    # 🚧 [점검 모드 설정] True = 점검중 / False = 정상
    # =================================================
    MAINTENANCE_MODE = False  
    
    # 점검 모드가 켜져있고, 관리자(?admin=true)가 아니면 멈춤!
    if MAINTENANCE_MODE:
        # URL에 ?admin=true가 없으면 점검 화면 보여주고 멈춤
        if st.query_params.get("admin", "false").lower() != "true":
            st.title("🚧 서비스 점검 중입니다")
            st.markdown("### 🔧 더 나은 기능을 위해 시스템 점검을 진행하고 있습니다.")
            st.info("잠시 후 다시 접속해 주세요.")
            st.divider()
            st.caption("🐌 배당팽이 드림")
            st.stop()  # 🛑 여기서 앱 실행 강제 종료 (이 아래 코드는 실행되지 않음)
    # =================================================
    
    # 헤더
    st.title("🐌 배당팽이 월배당 계산기")
    st.caption("나만의 배당 포트폴리오를 관리하고, 월별 예상 배당금을 확인하세요.")
    st.divider() 

    # 분석 도구
    inject_ga()
    logger.info("🚀 배당팽이 메인 엔진 가동")
    db.cleanup_old_tokens()

    # 2. 관리자 인증 확인
    is_admin = False
    if st.query_params.get("admin", "false").lower() == "true":
        ADMIN_HASH = st.secrets["ADMIN_PASSWORD_HASH"]
        with st.expander("🔐 관리자 접속 (Admin)", expanded=False):
            password_input = st.text_input("비밀번호 입력", type="password")
            if password_input:
                if hashlib.sha256(password_input.encode()).hexdigest() == ADMIN_HASH:
                    is_admin = True
                    logger.info("🔑 관리자 모드 접속 성공")
                    st.success("관리자 모드 ON 🚀")
                else:
                    st.error("비밀번호 불일치")

    render_login_ui()
    
    # 3. 로그인 및 AI 헤더
    with st.container(border=True):
        col_auth, col_ai = st.columns([2, 1.2])
        
        with col_auth:
            if not st.session_state.get("is_logged_in", False):
                if "code" in st.query_params:
                     st.info("🔄 로그인 확인 중입니다...")
                else:
                    render_login_buttons(key_suffix="top_header")
            else:
                user = st.session_state.user_info
                nickname = user.email.split("@")[0] if user.email else "User"
                st.success(f"👋 **{nickname}**님, 환영합니다!")

        with col_ai:
            if st.button("🕵️ AI 로보어드바이저", use_container_width=True, type="primary"):
                if st.session_state.get("is_logged_in"):
                    st.session_state.ai_modal_open = True
                    st.session_state.wiz_step = 0
                    st.session_state.wiz_data = {}
                    if "ai_result_cache" in st.session_state:
                        del st.session_state.ai_result_cache
                else:
                    st.toast("🔒 로그인을 먼저 해주세요!", icon="👆")

    # 4. 데이터 로드 및 처리
    df_raw = logic.load_stock_data_from_csv()
    if df_raw.empty: 
        logger.error("❌ 데이터 로드 실패: CSV 파일이 비어있음")
        st.stop()

    if is_admin:
        admin_ui.render_admin_tools(df_raw, supabase)  # 👈 새 파일(admin_ui)에 있는 함수 호출!
        admin_ui.render_etf_uploader(supabase) # [추가] ETF 업로더도 같이!
        
        # -------------------------------------------------------------
        # 🛠️ [NEW] 관리자 전용: ETF 구성종목 DB 대량 업데이트
        # -------------------------------------------------------------
        st.divider()
        st.subheader("📤 ETF 구성종목 DB 업데이트 (관리자용)")
        st.info("💡 'etf_holdings.csv' (id 포함) 파일을 업로드하면 DB가 덮어씌워집니다.")
        
        uploaded_file = st.file_uploader("CSV 파일 업로드", type=['csv'])
        if uploaded_file is not None:
            st.write("파일명:", uploaded_file.name)
            if st.button("🚀 DB 덮어쓰기 (기존 데이터 삭제됨)", type="primary"):
                with st.spinner("DB 업데이트 중..."):
                    try:
                        # CSV 읽기
                        df_new = pd.read_csv(uploaded_file)
                        
                        # 데이터프레임을 리스트 딕셔너리로 변환
                        data_to_upload = df_new.to_dict(orient='records')
                        
                        # 1. 기존 데이터 삭제 (안전하게 id가 0이 아닌 것들 삭제)
                        # 주의: 테이블이 비어있으면 에러 날 수 있으니 예외처리 필요할 수도 있음
                        supabase.table("etf_holdings").delete().neq("id", 0).execute()
                        
                        # 2. 새 데이터 삽입
                        supabase.table("etf_holdings").insert(data_to_upload).execute()
                        
                        st.success(f"✅ 업데이트 완료! (총 {len(data_to_upload)}건)")
                        st.balloons()
                    except Exception as e:
                        st.error(f"업데이트 실패: {e}")
        # -------------------------------------------------------------
    
    with st.spinner('⚙️ 배당 데이터베이스 엔진 가동 중...'):
        df_calculated = logic.load_and_process_data(df_raw, is_admin=is_admin)
        st.session_state['shared_df'] = df_calculated 
        
        # 크롤링된 Auto 데이터 동기화
        if df_calculated is not None and not df_calculated.empty and 'df_dirty' in st.session_state:
            try:
                auto_map = df_calculated.set_index('종목코드')['연배당금_크롤링_auto'].to_dict()
                st.session_state.df_dirty['연배당금_크롤링_auto'] = (
                    st.session_state.df_dirty['종목코드']
                    .map(auto_map)
                    .fillna(st.session_state.df_dirty['연배당금_크롤링_auto'])
                )
            except Exception as e:
                logger.error(f"⚠️ 데이터 동기화 중 오류: {e}")

        df = df_calculated

    # 5. 사이드바 및 페이지 라우팅
    with st.sidebar:
        if not st.session_state.is_logged_in: st.markdown("---")
        
        menu = st.radio("📂 **메뉴 이동**", ["💰 배당금 계산기", "📅 월별 로드맵", "📃 전체 종목 리스트"], label_visibility="visible")
        
        st.markdown("---")
        
        expense_input = st.number_input(
            "💸 나의 월평균 지출 (만원)", 
            min_value=10, 
            value=st.session_state.monthly_expense, 
            step=10,
            key="sidebar_expense_input",
            help="이 수치는 배당 방어율 계산의 기준이 됩니다."
        )
        st.session_state.monthly_expense = expense_input

        st.markdown("---")

        # 포트폴리오 관리 (불러오기/삭제)
        with st.expander("📂 불러오기 / 관리", expanded=True):
            if not st.session_state.is_logged_in:
                st.caption("🔒 상단에서 로그인을 해주세요.")
            else:
                try:
                    uid = st.session_state.user_info.id
                    resp = supabase.table("portfolios").select("*").eq("user_id", uid).order("created_at", desc=True).execute()
                    if resp.data:
                        opts = {f"{p.get('name') or '이름없음'} ({p['created_at'][5:10]} {p['created_at'][11:16]})": p for p in resp.data}
                        
                        is_delete_mode = st.toggle("🗑️ 포트폴리오 정리(삭제) 모드")

                        if is_delete_mode:
                            st.caption("삭제할 포트폴리오를 모두 선택하세요.")
                            targets_to_delete = st.multiselect(
                                "삭제 목록 선택", 
                                options=list(opts.keys()),
                                placeholder="지울 항목들을 선택하세요",
                                label_visibility="collapsed"
                            )

                            if targets_to_delete:
                                if st.button(f"🚨 선택한 {len(targets_to_delete)}개 영구 삭제", type="primary", use_container_width=True):
                                    confirm_delete_dialog(targets_to_delete, opts, supabase)
                            else:
                                st.button("🚨 삭제 버튼 (항목을 먼저 선택하세요)", disabled=True, use_container_width=True)

                        else:
                            sel_name = st.selectbox("항목 선택", list(opts.keys()), label_visibility="collapsed")
                            
                            if st.button("📂 불러오기", use_container_width=True):
                                data = opts[sel_name]['ticker_data']
                                st.session_state.total_invest = int(data.get('total_money', 30000000))
                                st.session_state.selected_stocks = list(data.get('composition', {}).keys())
                                saved_weights = data.get('composition', {})
                                st.session_state.ai_suggested_weights = saved_weights
                                st.session_state.monthly_expense = int(data.get('monthly_expense', 200))
                                
                                logger.info(f"📂 포트폴리오 로드: {sel_name}")
                                st.toast("성공적으로 불러왔습니다!", icon="✅")
                                time.sleep(0.5)
                                st.rerun()
                    else: 
                        st.caption("저장된 기록이 없습니다.")
                except Exception as e: 
                    st.error(f"불러오기 실패: {e}")

        st.markdown("---")

        with st.expander("📄 법적 고지 및 정책"):
            st.caption("본 서비스는 사용자의 안전한 이용을 위해 아래 정책을 준수합니다.")
            if st.button("🛡️ 개인정보 처리방침 확인", use_container_width=True):
                try:
                    with open("privacy.md", "r", encoding="utf-8") as f: st.markdown(f.read())
                except: st.error("정책 파일을 찾을 수 없습니다.")

        render_sidebar_footer()

    # 6. 페이지 렌더링
    if menu == "💰 배당금 계산기":
        render_calculator_page(df)
    elif menu == "📅 월별 로드맵":
        render_roadmap_page(df)
    elif menu == "📃 전체 종목 리스트":
        render_stocklist_page(df)

    # 7. 푸터
    st.divider()
    st.caption("© 2025 **배당 팽이** | 실시간 데이터 기반 배당 대시보드")
    st.caption("First Released: 2025.12.31 | [📝 배당팽이 투자 일지 ](https://blog.naver.com/dividenpange) | [💌 앱 개선 의견 남기기](https://docs.google.com/forms/d/e/1FAIpQLSdEJWd4sYx-09wZk7gl86Sf7bMliT4X9R0eWTAqxjv_Mal8Jg/viewform?usp=header)")

    
    # [NEW] 앱 설치 가이드 추가
    st.write("")
    render_install_guide()  # <--- 여기 추가했습니다!



if __name__ == "__main__":
    main()
