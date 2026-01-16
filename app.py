"""
프로젝트: 배당 팽이 (Dividend Top) v1.5
파일명: app.py (Phase 2: 통합 관제실 리팩토링 완료)
설명: 라이브러리 로드, 세션 초기화, 중앙 라우팅 시스템 구축
"""

import streamlit as st
import pandas as pd
import altair as alt
import hashlib
import time
import random
from streamlit.runtime.scriptrunner import get_script_run_ctx
from logger import logger  # [추가] 블랙박스 배선 연결
from analytics import inject_ga

# [필수] 날짜 및 URL 라이브러리
from datetime import datetime, timedelta
import urllib.parse

# [모듈화] 기능을 분리한 커스텀 파일들을 불러옵니다
import logic 
import ui
import db
import recommendation
import timeline


# ==========================================
# [SECTION 1] 기본 페이지 설정 및 초기화
# ==========================================

# 앱의 타이틀과 가로 너비를 설정합니다
st.set_page_config(page_title="배당팽이 대시보드", layout="wide")

# ---------------------------------------------------------
# [추가 과제] 4과제: COPPA 나이 확인 (안전 장치)
# ---------------------------------------------------------
# 주석 처리를 원하시면 아래 함수 전체를 드래그해서 Ctrl + / 누르시면 됩니다.
def check_coppa_compliance():
    """만 13세 이상 이용 확인 (법적 준수 안내판)"""
    if "age_verified" not in st.session_state:
        st.warning("📋 **서비스 이용 안내**")
        st.write("본 서비스는 개인정보보호법 및 COPPA 규정에 따라 만 13세 이상 사용자만 이용 가능합니다.")
        if st.checkbox("나는 만 13세 이상이며, 이용 약관 및 개인정보 처리방침에 동의합니다."):
            st.session_state.age_verified = True
            logger.info("✅ 사용자가 나이 확인 및 약관에 동의함")
            st.rerun()
        else:
            st.stop()

# 세션 상태(Session State) 변수 초기화 로직
for key in ["is_logged_in", "user_info", "code_processed"]:
    if key not in st.session_state:
        st.session_state[key] = False if key != "user_info" else None

# AI 추천 모달창 열림/닫힘 상태 관리 변수
if "ai_modal_open" not in st.session_state:
    st.session_state.ai_modal_open = False

# ---------------------------------------------------------
# 외부 데이터베이스(Supabase) 연결 초기화
# ---------------------------------------------------------
supabase = db.init_supabase()


# ==========================================
# [SECTION 2] 인증 및 보안 엔진
# ==========================================

def check_auth_status():
    """
    사용자의 로그인 상태를 확인하고, 카카오/구글 로그인 후 
    돌아오는 콜백(auth code)을 처리하여 세션을 확정합니다.
    """
    if not supabase: return

    # 1. [기존 세션 확인] 이미 브라우저에 로그인 정보가 남아있는지 확인
    try:
        session = supabase.auth.get_session()
        if session and session.user:
            st.session_state.is_logged_in = True
            st.session_state.user_info = session.user
            if "code" in st.query_params or "old_id" in st.query_params:
                st.query_params.clear()
            return 
    except Exception:
        pass

    # 2. [로그인 콜백 처리] OAuth 로그인 후 리다이렉트된 경우 처리
    query_params = st.query_params
    if "code" in query_params and not st.session_state.get("code_processed", False):
        st.session_state.code_processed = True
        
        try:
            # URL의 auth_code를 세션 토큰으로 교환
            auth_code = query_params["code"]
            auth_response = supabase.auth.exchange_code_for_session({"auth_code": auth_code})
            session = auth_response.session
            
            if session and session.user:
                st.session_state.is_logged_in = True
                st.session_state.user_info = session.user
                logger.info(f"👤 사용자 로그인 성공: {session.user.email}") # [3과제] 로깅 추가
            
            # 인증 성공 후 깨끗한 URL로 새로고침
            st.query_params.clear()
            st.success("✅ 로그인되었습니다!")
            st.rerun()
            
        except Exception as e:
            # [자동 복구 로직] verifier 오류(새로고침 시 발생 등) 시 파라미터 리셋 후 재시도
            err_msg = str(e).lower()
            logger.error(f"🔴 인증 과정 중 오류 발생: {err_msg}") # [3과제] 로깅 추가
            if "verifier" in err_msg or "non-empty" in err_msg:
                st.warning("🔄 보안 토큰 갱신 중... 잠시만 기다려주세요.")
                st.query_params.clear()
                time.sleep(1.0)
                st.rerun()
            else:
                st.error(f"🔴 인증 오류: {e}")
                st.query_params.clear()

check_auth_status()


# ==========================================
# [SECTION 3] UI 컴포넌트 (사이드바 및 공통 요소)
# ==========================================

def render_login_ui():
    """사이드바 상단에 현재 로그인된 유저 정보를 표시하고 로그아웃 기능을 제공합니다."""
    if not supabase: return
    is_logged_in = st.session_state.get("is_logged_in", False)
    user_info = st.session_state.get("user_info", None)
    
    if is_logged_in and user_info:
        # 이메일 앞부분을 닉네임으로 활용
        email = user_info.email if user_info.email else "User"
        nickname = email.split("@")[0]
        
        with st.sidebar:
            st.markdown("---")
            st.success(f"👋 반가워요! **{nickname}**님")
            
            # 로그아웃 버튼 클릭 시 세션 초기화 및 새로고침
            if st.button("🚪 로그아웃", key="logout_btn_sidebar", use_container_width=True):
                logger.info(f"🚪 사용자 로그아웃: {email}") # [3과제] 로깅 추가
                supabase.auth.sign_out()
                st.session_state.is_logged_in = False
                st.session_state.user_info = None
                st.session_state.code_processed = False
                st.rerun()

# -----------------------------------------------------------
# [추가됨] 사이드바 하단 커피 후원 버튼 렌더링 함수
# -----------------------------------------------------------
def render_sidebar_footer():
    """사이드바 최하단 후원 버튼 및 저작권 정보"""
    bmc_url = "https://www.buymeacoffee.com/dividenpange"

    st.sidebar.markdown("---") # 구분선
    
    st.sidebar.markdown(f"""
        <style>
        .bmc-container {{
            display: flex;
            justify-content: center;
            margin: 10px 0;
        }}
        .bmc-button {{
            display: flex;
            align-items: center;
            justify-content: center;
            background-color: #FFDD00;
            color: #000000 !important;
            padding: 10px 15px;
            border-radius: 10px;
            text-decoration: none;
            font-weight: bold;
            font-size: 14px;
            box-shadow: 0 4px 8px rgba(0,0,0,0.1);
            transition: transform 0.2s;
            width: 100%;
        }}
        .bmc-button:hover {{
            transform: translateY(-2px);
            text-decoration: none;
            background-color: #FADA00;
        }}
        .bmc-logo {{
            height: 18px;
            margin-right: 8px;
        }}
        </style>
        <div class="bmc-container">
            <a class="bmc-button" href="{bmc_url}" target="_blank">
                <img src="https://cdn.buymeacoffee.com/buttons/bmc-new-btn-logo.svg" alt="BMC logo" class="bmc-logo">
                <span>배당팽이에게 커피 한 잔</span>
            </a>
        </div>
    """, unsafe_allow_html=True)
    



# ==========================================
# [SECTION 4] 페이지별 렌더링 함수 (부품화)
# ==========================================

def render_admin_tools(df_raw):
    """관리자 전용 도구 렌더링"""
    with st.sidebar:
        st.markdown("---")
        st.subheader("🛠️ 배당금 갱신 도구")
        
        # [신규 종목 식별] 신규 상장주에 ⭐ 라벨 추가
        stock_options = {}
        for idx, row in df_raw.iterrows():
            name = row['종목명']
            try: months = int(row.get('신규상장개월수', 0))
            except: months = 0
            label = f"⭐ [신규 {months}개월] {name}" if months > 0 else name
            stock_options[label] = name

        selected_label = st.selectbox("갱신할 종목 선택", list(stock_options.keys()))
        target_stock = stock_options[selected_label]
        
        if target_stock:
            row = df_raw[df_raw['종목명'] == target_stock].iloc[0]
            cur_hist = row.get('배당기록', "")
            code = str(row.get('종목코드', '')).strip()
            category = str(row.get('분류', '국내')).strip()
            
            st.write("") 
            col_info, col_btn = st.columns([1, 1.5])
            with col_info:
                st.caption(f"코드: {code}")
                st.caption(f"분류: {category}")
            with col_btn:
                if st.button("🔍 배당률 조회", key="btn_auto_check", use_container_width=True):
                    with st.spinner("탐색 중..."):
                        y_val, src = logic.fetch_dividend_yield_hybrid(code, category)
                        if y_val > 0:
                            st.success(f"📈 {y_val}%")
                            st.caption(f"출처: {src}")
                        else:
                            st.error("실패")
                            st.caption(f"원인: {src}")
                            
            st.divider()
            new_div = st.number_input("이번 달 확정 배당금", value=0, step=10)
            if st.button("계산 실행", use_container_width=True):
                new_total, new_hist = logic.update_dividend_rolling(cur_hist, new_div)
                st.success("완료!")
                st.code(new_hist, language="text")

        st.markdown("---")
        st.subheader("💾 데이터 저장 및 백업")

        csv_data = df_raw.to_csv(index=False).encode('utf-8')
        st.download_button(
            label="📂 (혹시 모르니) 현재 파일 백업하기",
            data=csv_data,
            file_name=f"stocks_backup_{pd.Timestamp.now().strftime('%Y%m%d')}.csv",
            mime='text/csv',
            use_container_width=True
        )

        st.write("") 
        with st.expander("⚡ 전체 종목 자동 업데이트 (신규 제외)"):
            st.caption("신규 상장 종목(⭐)과 배당률 2% 미만은 건너뜁니다.")
            if st.button("전체 자동 갱신 시작"):
                progress_bar = st.progress(0)
                status_text = st.empty()
                updated_count = 0
                skipped_count = 0
                total_stocks = len(df_raw)
                df_temp = df_raw.copy()
                
                for i, row in df_temp.iterrows():
                    progress_bar.progress((i + 1) / total_stocks)
                    status_text.text(f"검사 중: {row['종목명']}...")
                    try: months = int(row.get('신규상장개월수', 0))
                    except: months = 0
                    if 0 < months < 12:
                        skipped_count += 1
                        continue
                    code = str(row['종목코드']).strip()
                    cat = str(row.get('분류', '국내')).strip()
                    amt, src = logic.fetch_dividend_amount_hybrid(code, cat)
                    if amt > 0:
                        df_temp.at[i, '연배당률_크롤링'] = amt
                        updated_count += 1
                    else:
                        st.warning(f"⚠️ {row['종목명']}({code}) 실패 -> 원인: {src}")
                        
                status_text.text("완료!")
                st.success(f"✅ {updated_count}개 금액 갱신 완료 / 🛡️ {skipped_count}개 신규주 보호됨")
                st.session_state.df_dirty = df_temp

        st.markdown("---")
        st.info("💡 위에서 내용을 충분히 검토하셨나요?")
        confirm_save = st.checkbox("네, 덮어써도 좋습니다.")

        if confirm_save:
            if st.button("🚀 깃허브에 영구 저장 (Commit)", type="primary", use_container_width=True):
                with st.spinner("서버에 업로드 중..."):
                    target_df = st.session_state.get('df_dirty', df_raw)
                    success, msg = logic.save_to_github(target_df)
                    if success:
                        st.success(msg)
                        logger.info("💾 관리자가 깃허브 데이터 업데이트 완료")
                        st.balloons()
                        time.sleep(2)
                        st.rerun()
                    else:
                        st.error(msg)
        else:
            st.button("🚀 깃허브에 영구 저장", disabled=True, use_container_width=True)


def render_calculator_page(df):
    """💰 배당금 계산기 페이지 렌더링"""
    # 6-1. AI 로보어드바이저
    st.write("")
    col_rec1, col_rec2 = st.columns([2, 1])
    with col_rec1:
        st.info("🤔 **어떤 종목을 담아야 할지 막막하신가요?**\n\nAI가 성향을 분석해 최적의 포트폴리오를 제안합니다.")
    with col_rec2:
        st.write("") 
        if st.button("🕵️ AI 로보어드바이저 실행", use_container_width=True, type="primary"):
            if st.session_state.get("is_logged_in"):
                logger.info("🤖 AI 로보어드바이저 세션 시작")
                st.session_state.ai_modal_open = True
                st.session_state.wiz_step = 1
                st.session_state.wiz_data = {}
                if "ai_result_cache" in st.session_state:
                    del st.session_state.ai_result_cache
            else:
                st.error("🔒 로그인이 필요한 기능입니다. 페이지 최상단에서 로그인을 먼저 해주세요!")
                st.toast("위에서 로그인을 해주세요!", icon="👆")
                st.session_state.ai_modal_open = False

        if st.session_state.get("ai_modal_open", False):
            recommendation.show_wizard()
    
    st.markdown("---")

    # 6-2. 포트폴리오 시뮬레이션
    with st.expander("🧮 나만의 배당 포트폴리오 시뮬레이션", expanded=True):
        col1, col2 = st.columns([1, 2])
        current_invest_val = int(st.session_state.total_invest / 10000)
        invest_input = col1.number_input("💰 총 투자 금액 (만원)", min_value=100, value=current_invest_val, step=100)
        st.session_state.total_invest = invest_input * 10000
        total_invest = st.session_state.total_invest 
        
        selected = col2.multiselect("📊 종목 선택", df['pure_name'].unique(), default=st.session_state.selected_stocks)
        st.session_state.selected_stocks = selected

        all_data = []

        if selected:
            has_foreign_stock = any(df[df['pure_name'] == s_name].iloc[0]['분류'] == '해외' for s_name in selected)
            if has_foreign_stock:
                st.warning("📢 **잠깐!** 선택하신 종목 중 '해외 상장 ETF'가 포함되어 있습니다. ISA/연금계좌 결과는 참고용으로만 봐주세요.")

            weights = {}
            remaining = 100
            cols_w = st.columns(2)
            
            for i, stock in enumerate(selected):
                with cols_w[i % 2]:
                    safe_rem = max(0, remaining)
                    ai_suggested = st.session_state.get('ai_suggested_weights', {})
                    default_w = ai_suggested.get(stock, 100 // len(selected))
                    
                    if i < len(selected) - 1:
                        val = st.number_input(f"{stock} (%)", min_value=0, max_value=safe_rem, value=min(safe_rem, default_w), step=5, key=f"s_{i}")
                        weights[stock] = val
                        remaining -= val
                        amt = total_invest * (val / 100)
                    else:
                        st.info(f"{stock}: {safe_rem}% 자동 적용")
                        weights[stock] = safe_rem
                        amt = total_invest * (safe_rem / 100)
                    
                    st.caption(f"💰 투자금: **{amt/10000:,.0f}만원**")
                    
                    stock_match = df[df['pure_name'] == stock]
                    if not stock_match.empty:
                        s_row = stock_match.iloc[0]
                        cal_link = s_row.get('캘린더링크') 
                        ex_date_view = s_row.get('배당락일', '-')
                        btn_label = f"📅 {ex_date_view} (D-3 알림)" if cal_link else f"🗓️ {ex_date_view}"

                        if cal_link:
                            if st.session_state.get("is_logged_in", False):
                                st.link_button(btn_label, cal_link, use_container_width=True)
                            else:
                                if st.button(btn_label, key=f"btn_cal_{i}", use_container_width=True):
                                    st.toast("🔒 로그인 후 캘린더에 등록할 수 있습니다!", icon="🔒")
                        else:
                            st.caption(f"📅 날짜 미정 ({ex_date_view})")
                    
                    if not stock_match.empty:
                        s_row = stock_match.iloc[0]
                        all_data.append({
                            '종목': stock, '비중': weights[stock], '자산유형': s_row['자산유형'], '투자금액_만원': amt / 10000,
                            '종목명': stock, '코드': s_row.get('코드', ''), '분류': s_row.get('분류', '국내'),
                            '연배당률': s_row.get('연배당률', 0), '금융링크': s_row.get('금융링크', '#'),
                            '신규상장개월수': s_row.get('신규상장개월수', 0), '현재가': s_row.get('현재가', 0),
                            '환구분': s_row.get('환구분', '-'), '배당락일': s_row.get('배당락일', '-')
                        })
            
            timeline.display_sidebar_roadmap(df, weights, total_invest)
            
            # 포트폴리오 결과 분석
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

            # 캘린더 다운로드
            st.divider()
            ics_data = logic.generate_portfolio_ics(all_data)
            st.subheader("📅 캘린더 일괄 등록")
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
                        st.toast("맨 위로 올라가서 로그인을 해주세요!", icon="👆")

            with st.expander("❓ 다운로드 받은 파일은 어떻게 쓰나요? (사용법 보기)"):
                st.markdown("""
                **아주 간단합니다! 따라해 보세요.** 👇
                1. 위 **[전체 일정 파일 받기]** 버튼을 누르세요. (로그인 필요)
                2. 다운로드된 파일(`dividend_calendar.ics`)을 클릭(터치)해서 여세요.
                3. 스마트폰이나 PC에서 **"일정을 추가하시겠습니까?"** 라고 물어봅니다.
                4. **[추가]** 또는 **[저장]** 버튼만 누르면 끝!
                """)

            # 포트폴리오 저장
            st.write("") 
            with st.container(border=True):
                st.write("💾 **포트폴리오 저장 / 수정**")
                if not st.session_state.get('is_logged_in', False):
                    st.warning("⚠️ **로그인이 필요합니다.**")
                    st.markdown("""나만의 포트폴리오를 저장하고 관리하시려면 페이지 최상단(맨 위)에 있는 로그인을 이용해 주세요.""")
                else:
                    try:
                        user = st.session_state.user_info
                        save_mode = st.radio("방식 선택", ["✨ 새로 만들기", "🔄 기존 파일 수정"], horizontal=True, label_visibility="collapsed")
                        save_data = {"total_money": st.session_state.total_invest, "composition": weights, "summary": {"monthly": total_m, "yield": avg_y}}

                        if save_mode == "✨ 새로 만들기":
                            c_new1, c_new2 = st.columns([2, 1])
                            p_name = c_new1.text_input("새 이름 입력", placeholder="비워두면 자동 이름", label_visibility="collapsed")
                            if c_new2.button("새로 저장", type="primary", use_container_width=True):
                                final_name = p_name.strip()
                                if not final_name:
                                    cnt_res = supabase.table("portfolios").select("id", count="exact").eq("user_id", user.id).execute()
                                    next_num = (cnt_res.count or 0) + 1
                                    final_name = f"포트폴리오 {next_num}"
                                supabase.table("portfolios").insert({"user_id": user.id, "user_email": user.email, "name": final_name, "ticker_data": save_data}).execute()
                                logger.info(f"💾 새 포트폴리오 저장: {final_name}")
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
                                    supabase.table("portfolios").update({"ticker_data": save_data, "created_at": "now()"}).eq("id", target_id).execute()
                                    logger.info(f"🔄 기존 포트폴리오 업데이트: {target_id}")
                                    st.success("수정 완료! 내용이 업데이트되었습니다.")
                                    st.balloons()
                                    time.sleep(1.0)
                                    st.rerun()
                    except Exception as e:
                        st.error(f"오류 발생: {e}")
            
            st.write("")
            st.info("""📢 **찾으시는 종목이 안 보이나요?**\n왼쪽 상단(모바일은 ↖ 메뉴 버튼)의 '📂 메뉴'를 누르고 '📃 전체 종목 리스트'를 선택하시면 전체 배당주를 확인하실 수 있습니다.""")
            if total_y_div > 20000000:
                st.warning(f"🚨 **주의:** 연간 예상 배당금이 **{total_y_div/10000:,.0f}만원**입니다. 금융소득종합과세 대상에 해당될 수 있습니다.")

    # 6-7. 심층 분석
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
            st.error("""**⚠️ 포트폴리오 분석 시 유의사항**\n1. 과거의 데이터를 기반으로 한 단순 결과값이며, 실제 투자 수익을 보장하지 않습니다.\n2. '달러 자산' 비율 실제 환노출 여부와 다를 수 있습니다 투자 전 확인이 필요합니다.\n3. 실제 배당금 지급일과 금액은 운용사의 사정에 따라 변경될 수 있습니다.""")

        with tab_simulation:
            start_money = total_invest
            is_over_100m = start_money > 100000000
            st.info(f"📊 상단에서 설정한 **초기 자산 {start_money/10000:,.0f}만원**으로 시뮬레이션을 시작합니다.")
            c1, c2 = st.columns([1.5, 1])
            with c1:
                if is_over_100m:
                    is_isa_mode = st.toggle("🛡️ ISA 계좌 불가 (한도 1억 초과)", value=False, disabled=True)
                    st.caption("🚫 초기 투자금이 1억원을 초과하여 일반 계좌로만 진행됩니다.")
                else:
                    is_isa_mode = st.toggle("🛡️ ISA (절세) 계좌로 모으기", value=True)
                    if is_isa_mode: st.caption("💡 **ISA 모드:** 비과세 + 과세이연 효과")
                    else: st.caption("💡 **일반 모드:** 배당소득세(15.4%) 납부 후 재투자")
            with c2:
                years_sim = st.select_slider("⏳ 투자 기간", options=[3, 5, 10, 15, 20, 30], value=5, format_func=lambda x: f"{x}년")
                apply_inflation = st.toggle("📉 물가상승률(2.5%) 반영", value=False)
            
            reinvest_ratio = 100
            isa_exempt = 0
            if is_isa_mode:
                isa_type = st.radio("ISA 유형", ["일반형 (비과세 200만)", "서민형 (비과세 400만)"], horizontal=True, label_visibility="collapsed")
                isa_exempt = 400 if "서민형" in isa_type else 200
            else:
                if not is_over_100m:
                    st.caption("설정한 비율만큼만 재투자하고 나머지는 생활비로 씁니다.")
                    reinvest_ratio = st.slider("💰 재투자 비율 (%)", 0, 100, 100, step=10)
            
            st.markdown("---")
            monthly_input = st.number_input("➕ 매월 추가 적립 (만원)", min_value=0, max_value=3000, value=150, step=10) * 10000
            monthly_add = monthly_input
            if is_isa_mode and monthly_add > 1666666:
                st.warning("⚠️ **ISA 연간 한도 제한:** 월 납입금이 **약 166만원(연 2,000만원)**으로 자동 조정되어 계산됩니다.")
                monthly_add = 1666666 
            
            months_sim = years_sim * 12
            monthly_yld = avg_y / 100 / 12
            current_bal = start_money
            total_principal = start_money
            ISA_YEARLY_CAP = 20000000
            ISA_TOTAL_CAP = 100000000
            sim_data = [{"년차": 0, "자산총액": current_bal/10000, "총원금": total_principal/10000, "실제월배당": 0}]
            
            year_tracker = 0
            yearly_contribution = 0
            total_tax_paid_general = 0

            for m in range(1, months_sim + 1):
                if m // 12 > year_tracker:
                    yearly_contribution = 0
                    year_tracker = m // 12
                actual_add = monthly_add
                if is_isa_mode:
                    remaining_yearly = max(0, ISA_YEARLY_CAP - yearly_contribution)
                    remaining_total = max(0, ISA_TOTAL_CAP - total_principal)
                    actual_add = min(monthly_add, remaining_yearly, remaining_total)
                current_bal += actual_add
                total_principal += actual_add
                yearly_contribution += actual_add
                div_earned = current_bal * monthly_yld
                if is_isa_mode: reinvest = div_earned
                else:
                    this_tax = div_earned * 0.154
                    total_tax_paid_general += this_tax
                    reinvest = (div_earned - this_tax) * (reinvest_ratio / 100)
                current_bal += reinvest
                sim_data.append({"년차": m / 12, "자산총액": current_bal / 10000, "총원금": total_principal / 10000, "실제월배당": div_earned})
            
            df_sim_chart = pd.DataFrame(sim_data)
            base = alt.Chart(df_sim_chart).encode(x=alt.X('년차:Q', title='경과 기간 (년)'))
            area = base.mark_area(opacity=0.3, color='#0068c9').encode(y=alt.Y('자산총액:Q', title='자산 (만원)'))
            line = base.mark_line(color='#ff9f43', strokeDash=[5,5]).encode(y='총원금:Q')
            st.altair_chart((area + line).properties(height=280), use_container_width=True)

            final_row = df_sim_chart.iloc[-1]
            final_asset = final_row['자산총액'] * 10000
            final_principal = final_row['총원금'] * 10000
            profit = final_asset - final_principal
            monthly_div_final = final_row['실제월배당']

            if is_isa_mode:
                taxable = max(0, profit - (isa_exempt * 10000))
                tax = taxable * 0.099
                real_money = final_asset - tax
                tax_msg = f"예상 세금 {tax/10000:,.0f}만원 (9.9% 분리과세)"
                monthly_pocket = monthly_div_final 
            else:
                real_money = final_asset
                tax_msg = f"기납부 세금 {total_tax_paid_general/10000:,.0f}만원 (15.4% 원천징수)"
                monthly_pocket = monthly_div_final * 0.846

            inflation_msg_money = ""
            inflation_msg_monthly = ""
            if apply_inflation:
                discount_rate = (1.025) ** years_sim 
                pv_money = real_money / discount_rate
                pv_monthly = monthly_pocket / discount_rate
                inflation_msg_money = f"<br><span style='font-size:0.6em; color:#ff6b6b;'>(현재가치: 약 {pv_money/10000:,.0f}만원)</span>"
                inflation_msg_monthly = f"<span style='font-size:0.7em; color:#ff6b6b;'>(현재가치: {pv_monthly/10000:,.1f}만원)</span>"

            analogy_items = [
                {"name": "스타벅스", "unit": "잔", "price": 4500, "emoji": "☕"},
                {"name": "뜨끈한 국밥", "unit": "그릇", "price": 10000, "emoji": "🍲"},
                {"name": "넷플릭스 구독", "unit": "개월", "price": 17000, "emoji": "📺"},
                {"name": "치킨", "unit": "마리", "price": 23000, "emoji": "🍗"},
                {"name": "제주도 항공권", "unit": "장", "price": 60000, "emoji": "✈️"},
                {"name": "특급호텔 숙박", "unit": "박", "price": 200000, "emoji": "🏨"},
                {"name": "최신 아이폰", "unit": "대", "price": 1500000, "emoji": "📱"}
            ]
            affordable_items = [item for item in analogy_items if monthly_pocket >= item['price']]
            if not affordable_items:
                selected_item = analogy_items[0]
                msg_count = f"{monthly_pocket / selected_item['price']:.1f}"
            else:
                selected_item = random.choice(affordable_items)
                item_count = int(monthly_pocket // selected_item['price'])
                msg_count = f"{item_count:,}"

            st.markdown(f"""
                <div style="background-color: #e7f3ff; border: 1.5px solid #d0e8ff; border-radius: 16px; padding: 25px; text-align: center; box-shadow: 0 4px 10px rgba(0,104,201,0.05);">
                    <p style="color: #666; font-size: 0.95em; margin: 0 0 8px 0;">{years_sim}년 뒤 모이는 돈 (세후)</p>
                    <h2 style="color: #0068c9; font-size: 2.2em; margin: 0; font-weight: 800; line-height: 1.2;">약 {real_money/10000:,.0f}만원{inflation_msg_money}</h2>
                    <p style="color: #777; font-size: 0.9em; margin: 8px 0 0 0;">(투자원금 {final_principal/10000:,.0f}만원 / {tax_msg})</p>
                    <div style="height: 1px; background-color: #d0e8ff; margin: 25px auto; width: 85%;"></div>
                    <p style="color: #0068c9; font-weight: bold; font-size: 1.1em; margin: 0 0 12px 0;">📅 월 예상 배당금: {monthly_pocket/10000:,.1f}만원 {inflation_msg_monthly}</p>
                    <div style="background-color: rgba(255,255,255,0.5); padding: 15px; border-radius: 12px; display: inline-block; min-width: 80%;">
                        <p style="color: #333; font-size: 1.1em; margin: 0; line-height: 1.6;">
                            매달 <b>{selected_item['emoji']} {selected_item['name']} {msg_count}{selected_item['unit']}</b><br>
                            마음껏 즐기기 가능! 😋
                        </p>
                    </div>
                </div>
            """, unsafe_allow_html=True)
            
            annual_div_income = monthly_div_final * 12
            if annual_div_income > 20000000: st.warning(f"🚨 **주의:** {years_sim}년 뒤 연간 배당금이 2,000만원을 초과하여 금융소득종합과세 대상이 될 수 있습니다.")
            st.error("""**⚠️ 시뮬레이션 활용 시 유의사항**\n1. 본 결과는 주가·환율 변동을 제외하고, 현재 배당률로만 계산한 결과입니다.\n2. ISA 계좌의 비과세 한도 및 세율은 세법 개정에 따라 달라질 수 있습니다.\n3. 과거의 데이터를 기반으로 한 단순 시뮬레이션이며, 실제 투자 수익을 보장하지 않습니다.""")

        with tab_goal:
            st.subheader("🎯 목표 배당금 역산기 (은퇴 시뮬레이터)")
            st.caption("내가 원하는 월급을 받기 위해 얼마를 더 모아야 할지 정밀하게 계산합니다.")
            col_g1, col_g2 = st.columns(2)
            with col_g1:
                target_monthly_goal = st.number_input("목표 월 배당금 (만원, 세후)", min_value=10, value=166, step=10) * 10000
                st.caption(f"💡 월 166.5만원 설정 시 연간 약 1,998만원으로 절세가 가능합니다.")
                use_start_money = st.checkbox("위에서 설정한 초기 자산을 포함하여 계산", value=True)
                start_bal_goal = total_invest if use_start_money else 0
            with col_g2:
                monthly_add_goal = st.number_input("매월 추가 적립 가능 금액 (만원)", min_value=0, value=150, step=10) * 10000
                apply_inflation_goal = st.toggle("📈 목표치에 물가상승률 반영", value=False, help="미래 가치를 고려해 목표를 상향 조정합니다.")
            
            tax_factor = 0.846
            required_asset_goal = (target_monthly_goal / tax_factor) / (avg_y / 100) * 12
            st.markdown("---")
            c_res1, c_res2 = st.columns(2)
            with c_res1:
                st.metric("목표 달성 필요 자산", f"{required_asset_goal/100000000:,.2f} 억원")
                st.caption(f"평균 배당률 {avg_y:.2f}% 및 배당세 15.4% 가정")
            with c_res2:
                current_bal_goal = start_bal_goal
                months_passed = 0
                max_months = 600 
                while current_bal_goal < required_asset_goal and months_passed < max_months:
                    div_reinvest = current_bal_goal * (avg_y / 100 / 12) * tax_factor
                    current_bal_goal += monthly_add_goal + div_reinvest
                    months_passed += 1
                if months_passed >= max_months:
                    st.error("⚠️ 현재 적립액으로는 50년 내 달성이 어렵습니다. 적립액을 높여주세요.")
                else:
                    st.metric("목표 달성까지 소요 기간", f"{months_passed // 12}년 {months_passed % 12}개월")
            
            if apply_inflation_goal and months_passed < max_months:
                discount_factor = (1.025) ** (months_passed / 12)
                real_value = target_monthly_goal / discount_factor
                st.warning(f"⚠️ **물가 반영 시:** {months_passed // 12}년 뒤 {target_monthly_goal/10000:,.0f}만원의 실질 가치는 현재 기준 **약 {real_value/10000:,.1f}만원**입니다.")
            
            target_annual_income = target_monthly_goal * 12
            if (target_annual_income / tax_factor) > 20000000:
                st.warning(f"🚨 **현실적 조언:** 목표 달성 시 연간 배당소득(세전)이 2,000만원을 초과하여 **금융소득종합과세** 대상이 될 수 있습니다.")
            elif (target_annual_income / tax_factor) > 19000000:
                st.success(f"✅ **절세 전략:** 현재 목표는 금융소득종합과세 기준선 이내에서 최적화되어 있습니다.")
            st.error("""**⚠️ 시뮬레이션 활용 시 유의사항**\n1. 본 결과는 주가·환율 변동을 제외하고, 현재 배당률로만 계산한 단순 결과입니다.\n2. 재투자가 매월 칼같이 이루어진다는 가정하에 계산된 복리 결과입니다.\n3. 실제 투자 시에는 배당 삭감이나 주가 하락의 리스크를 반드시 고려해야 합니다.""")


def render_roadmap_page(df):
    """📅 월별 로드맵 페이지 렌더링"""
    st.header("📅 나의 배당 월급 로드맵")
    st.info("💡 종목별 배당 주기를 반영한 데이터입니다. (로그인 없이 이용 가능)")

    selected = st.session_state.get('selected_stocks', [])
    if not selected:
        st.warning("⚠️ **'💰 배당금 계산기'** 메뉴에서 종목을 먼저 선택해 주세요!")
        st.stop()
    
    weights = {}
    remaining = 100
    for i, stock in enumerate(selected):
        if i < len(selected) - 1:
            val = st.session_state.get(f"s_{i}", 100 // len(selected))
            weights[stock] = val
            remaining -= val
        else:
            weights[stock] = max(0, remaining)

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
    """📃 전체 종목 리스트 페이지 렌더링"""
    st.info("💡 **이동 안내:** '코드' 클릭 시 블로그 분석글로, '🔗정보' 클릭 시 네이버/야후 금융 정보로 이동합니다. (**⭐ 표시는 상장 1년 미만 종목입니다.**)")
    tab_all, tab_kor, tab_usa = st.tabs(["🌎 전체", "🇰🇷 국내", "🇺🇸 해외"])
    
    with tab_all: ui.render_custom_table(df)
    with tab_kor: ui.render_custom_table(df[df['분류'] == '국내'])
    with tab_usa: ui.render_custom_table(df[df['분류'] == '해외'])


# ==========================================
# [SECTION 5] 메인 애플리케이션 실행 엔진 (관제실)
# ==========================================
def main():
    inject_ga()
    
    
    # 1. 안전 장치 및 로깅
    # check_coppa_compliance() # 필요시 주석 해제
    logger.info("🚀 배당팽이 메인 엔진 가동")
    db.cleanup_old_tokens()

    # 2. 관리자 인증
    is_admin = False
    if st.query_params.get("admin", "false").lower() == "true":
        ADMIN_HASH = "c41b0bb392db368a44ce374151794850417b56c9786e3c482f825327c7153182"
        with st.expander("🔐 관리자 접속 (Admin)", expanded=False):
            password_input = st.text_input("비밀번호 입력", type="password")
            if password_input:
                if hashlib.sha256(password_input.encode()).hexdigest() == ADMIN_HASH:
                    is_admin = True
                    logger.info("🔑 관리자 모드 접속 성공")
                    st.success("관리자 모드 ON 🚀")
                else:
                    st.error("비밀번호 불일치")

    # ---------------------------------------------------------
    # 3. [긴급 추가] 필수 세션 변수 초기화 (연료 주입)
    # ---------------------------------------------------------
    if "total_invest" not in st.session_state:
        st.session_state.total_invest = 30000000  # 기본 투자금 3,000만원
    if "selected_stocks" not in st.session_state:
        st.session_state.selected_stocks = []     # 선택 종목 리스트 초기화

    # 4. 사이드바 UI 및 인증
    render_login_ui()
    
    # 5. 상단 로그인 버튼 구역
    auth_container = st.container(border=True)
    with auth_container:
        if not st.session_state.get("is_logged_in", False):
            if "code" in st.query_params:
                 st.info("🔄 로그인 확인 중입니다... 잠시만 기다려주세요.")
            else:
                st.info("🔒 로그인이 필요합니다. (AI 진단 및 저장 기능 활성화)")
                try:
                    ctx = get_script_run_ctx()
                    current_session_id = ctx.session_id
                except: current_session_id = "unknown"
                redirect_url = f"https://dividend-pange.streamlit.app?old_id={current_session_id}"

                col_l, col_r = st.columns(2)
                with col_l:
                    try:
                        res_kakao = supabase.auth.sign_in_with_oauth({"provider": "kakao", "options": {"redirect_to": redirect_url, "skip_browser_redirect": True}})
                        if res_kakao.url:
                            st.markdown(f'''<a href="{res_kakao.url}" target="_blank" style="display: inline-flex; justify-content: center; align-items: center; width: 100%; background-color: #FEE500; color: #000000; border: 1px solid rgba(0,0,0,0.05); padding: 0.8rem; border-radius: 0.5rem; text-decoration: none; font-weight: bold; font-size: 1.1em; box-shadow: 0 1px 2px rgba(0,0,0,0.1); margin-bottom: 10px;">💬 Kakao로 3초 만에 시작하기</a>''', unsafe_allow_html=True)
                    except: pass
                with col_r:
                    if st.button("🔵 Google로 시작하기(pc/크롬 권장)", use_container_width=True, key="top_google_btn"):
                        try:
                            res_google = supabase.auth.sign_in_with_oauth({"provider": "google", "options": {"redirect_to": redirect_url, "queryParams": {"access_type": "offline", "prompt": "consent"}, "skip_browser_redirect": False}})
                            if res_google.url:
                                st.markdown(f'<meta http-equiv="refresh" content="0;url={res_google.url}">', unsafe_allow_html=True)
                                st.stop()
                        except: pass
        else:
            # 로그인 완료 메시지
            user = st.session_state.user_info
            nickname = user.email.split("@")[0] if user.email else "User"
            st.success(f"👋 **{nickname}**님, 환영합니다! 모든 기능이 활성화되었습니다.")

    # 6. 데이터 로드
    df_raw = logic.load_stock_data_from_csv()
    if df_raw.empty: 
        logger.error("❌ 데이터 로드 실패: CSV 파일이 비어있음")
        st.stop()

    # 7. 관리자 도구 렌더링
    if is_admin:
        render_admin_tools(df_raw)

    # 8. 데이터 엔진 가동
    with st.spinner('⚙️ 배당 데이터베이스 엔진 가동 중...'):
        df = logic.load_and_process_data(df_raw, is_admin=is_admin)
        st.session_state['shared_df'] = df

    # 9. 라우팅 (페이지 전환)
    with st.sidebar:
        if not st.session_state.is_logged_in: st.markdown("---")
        menu = st.radio("📂 **메뉴 이동**", ["💰 배당금 계산기", "📅 월별 로드맵", "📃 전체 종목 리스트"], label_visibility="visible")
        
        # 개인정보 처리방침
        st.markdown("---")
        with st.expander("📄 법적 고지 및 정책"):
            st.caption("본 서비스는 사용자의 안전한 이용을 위해 아래 정책을 준수합니다.")
            if st.button("🛡️ 개인정보 처리방침 확인", use_container_width=True):
                try:
                    with open("privacy.md", "r", encoding="utf-8") as f: st.markdown(f.read())
                except: st.error("정책 파일을 찾을 수 없습니다.")
        
        # 포트폴리오 불러오기 (사이드바)
        st.markdown("---")
        with st.expander("📂 불러오기 / 관리"):
            if not st.session_state.is_logged_in:
                st.caption("🔒 상단에서 로그인을 해주세요.")
            else:
                try:
                    uid = st.session_state.user_info.id
                    resp = supabase.table("portfolios").select("*").eq("user_id", uid).order("created_at", desc=True).execute()
                    if resp.data:
                        opts = {f"{p.get('name') or '이름없음'} ({p['created_at'][5:10]} {p['created_at'][11:16]})": p for p in resp.data}
                        sel_name = st.selectbox("항목 선택", list(opts.keys()), label_visibility="collapsed")
                        is_delete_mode = st.toggle("🗑️ 삭제 모드 켜기")
                        if is_delete_mode:
                            if st.button("🚨 영구 삭제", type="primary", use_container_width=True):
                                target_id = opts[sel_name]['id']
                                supabase.table("portfolios").delete().eq("id", target_id).execute()
                                logger.info(f"🗑️ 포트폴리오 삭제: {target_id}")
                                st.toast("삭제되었습니다.", icon="🗑️")
                                st.rerun()
                        else:
                            if st.button("📂 불러오기", use_container_width=True):
                                data = opts[sel_name]['ticker_data']
                                st.session_state.total_invest = int(data.get('total_money', 30000000))
                                st.session_state.selected_stocks = list(data.get('composition', {}).keys())
                                logger.info(f"📂 포트폴리오 로드: {sel_name}")
                                st.toast("성공적으로 불러왔습니다!", icon="✅")
                                st.rerun()
                    else: st.caption("저장된 기록이 없습니다.")
                except Exception as e: st.error("불러오기 실패")

        # [추가된 부분] 사이드바 하단 후원 버튼 호출 (여기 한 줄만 추가했습니다!)
        render_sidebar_footer()

    # [라우팅 실행] 선택된 메뉴에 따라 해당 페이지 렌더링 함수 호출
    if menu == "💰 배당금 계산기":
        render_calculator_page(df)
    elif menu == "📅 월별 로드맵":
        render_roadmap_page(df)
    elif menu == "📃 전체 종목 리스트":
        render_stocklist_page(df)

    # 10. 하단 정보 및 방문자 추적
    st.divider()
    st.caption("© 2025 **배당팽이** | 실시간 데이터 기반 배당 대시보드")
    st.caption("First Released: 2025.12.31 | [📝 배당팽이의 배당 투자 일지 구경가기](https://blog.naver.com/dividenpange)")

    

# ==========================================
# [ENTRY POINT] 앱 실행 시작점
# ==========================================
if __name__ == "__main__":
    main()
