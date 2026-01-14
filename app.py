import streamlit as st
import pandas as pd
import hashlib
import time
import db
import logic
import ui
import admin_view
import calculator_view
from streamlit.runtime.scriptrunner import get_script_run_ctx

# ==========================================
# [1] 기본 설정 및 세션 초기화
# ==========================================
st.set_page_config(page_title="배당팽이 대시보드", layout="wide")

# 세션 변수들 한 번에 초기화
for key in ["is_logged_in", "user_info", "code_processed", "total_invest", "selected_stocks"]:
    if key not in st.session_state:
        if key == "user_info": st.session_state[key] = None
        elif key == "total_invest": st.session_state[key] = 30000000
        elif key == "selected_stocks": st.session_state[key] = []
        else: st.session_state[key] = False

supabase = db.init_supabase()

# ==========================================
# [2] 인증 및 로그인 UI 로직
# ==========================================
def check_auth():
    if not supabase: return
    try:
        session = supabase.auth.get_session()
        if session and session.user:
            st.session_state.is_logged_in = True
            st.session_state.user_info = session.user
    except: pass

    # OAuth 콜백 처리 (카카오/구글 로그인 성공 후 리다이렉트 대응)
    query_params = st.query_params
    if "code" in query_params and not st.session_state.get("code_processed", False):
        st.session_state.code_processed = True
        try:
            auth_response = supabase.auth.exchange_code_for_session({"auth_code": query_params["code"]})
            if auth_response.session:
                st.session_state.is_logged_in = True
                st.session_state.user_info = auth_response.session.user
            st.query_params.clear()
            st.rerun()
        except: st.query_params.clear()

def render_sidebar_login():
    if st.session_state.is_logged_in and st.session_state.user_info:
        nickname = st.session_state.user_info.email.split("@")[0]
        with st.sidebar:
            st.markdown("---")
            st.success(f"👋 반가워요! **{nickname}**님")
            if st.button("🚪 로그아웃", use_container_width=True):
                supabase.auth.sign_out()
                st.session_state.is_logged_in = False
                st.session_state.user_info = None
                st.session_state.code_processed = False
                st.rerun()

# ==========================================
# [3] 메인 애플리케이션
# ==========================================
def main():
    db.cleanup_old_tokens() # 만료 토큰 자동 청소
    check_auth()
    render_sidebar_login()

    # 1. 관리자 접속 체크
    is_admin = False
    if st.query_params.get("admin", "false").lower() == "true":
        ADMIN_HASH = "c41b0bb392db368a44ce374151794850417b56c9786e3c482f825327c7153182"
        with st.expander("🔐 관리자 접속"):
            pwd = st.text_input("비밀번호", type="password")
            if pwd and hashlib.sha256(pwd.encode()).hexdigest() == ADMIN_HASH:
                is_admin = True
                st.success("관리자 모드 활성화 🚀")

    # 2. 데이터 로드 및 가공
    df_raw = logic.load_stock_data_from_csv()
    if df_raw.empty: st.stop()
    
    with st.spinner('⚙️ 엔진 가동 중...'):
        df = logic.load_and_process_data(df_raw, is_admin=is_admin)

    # 3. 사이드바 메뉴 및 불러오기 로직 (복구 완료)
    with st.sidebar:
        menu = st.radio("📂 **메뉴 이동**", ["💰 배당금 계산기", "📃 전체 종목 리스트"])
        st.markdown("---")
        
        with st.expander("📂 불러오기 / 관리"):
            if not st.session_state.is_logged_in:
                st.caption("로그인이 필요합니다.")
            else:
                try:
                    uid = st.session_state.user_info.id
                    resp = supabase.table("portfolios").select("*").eq("user_id", uid).order("created_at", desc=True).execute()
                    if resp.data:
                        opts = {f"{p.get('name') or '이름없음'} ({p['created_at'][5:10]})": p for p in resp.data}
                        sel_label = st.selectbox("항목 선택", list(opts.keys()), label_visibility="collapsed")
                        
                        is_delete = st.toggle("🗑️ 삭제 모드")
                        if is_delete:
                            if st.button("🚨 영구 삭제", type="primary", use_container_width=True):
                                supabase.table("portfolios").delete().eq("id", opts[sel_label]['id']).execute()
                                st.rerun()
                        else:
                            if st.button("📂 불러오기", use_container_width=True):
                                data = opts[sel_label]['ticker_data']
                                st.session_state.total_invest = int(data.get('total_money', 30000000))
                                st.session_state.selected_stocks = list(data.get('composition', {}).keys())
                                st.rerun()
                    else: st.caption("저장된 기록이 없습니다.")
                except: st.error("데이터 로드 실패")

    # 4. 화면 렌더링 (모듈화 연결)
    if is_admin:
        admin_view.render_admin_dashboard(df_raw) # 관리자 뷰 호출

    if menu == "💰 배당금 계산기":
        calculator_view.render_calculator_ui(df, supabase) # 계산기 뷰 호출
    else:
        st.info("💡 **전체 종목 리스트**입니다. (⭐ 표시는 신규 종목)")
        ui.render_custom_table(df) # 테이블 UI 호출

    # 5. 방문자 집계 (기존 로직 복구)
    st.divider()
    track_visitors(is_admin)

@st.fragment
def track_visitors(is_admin):
    """방문자 집계 및 하단 표시 로직"""
    if 'display_count' not in st.session_state:
        try:
            if not is_admin and supabase:
                # 방문 로그 기록
                ctx = get_script_run_ctx()
                supabase.table("visit_logs").insert({"referer": "App"}).execute()
                # 카운트 업데이트
                res = supabase.table("visit_counts").select("count").eq("id", 1).execute()
                if res.data:
                    new_cnt = res.data[0]['count'] + 1
                    supabase.table("visit_counts").update({"count": new_cnt}).eq("id", 1).execute()
                    st.session_state.display_count = new_cnt
            else: st.session_state.display_count = "Admin/Local"
        except: st.session_state.display_count = "집계 중"

    display_num = st.session_state.get('display_count', '집계 중')
    st.markdown(f"""<div style="text-align: center; padding: 20px; background: #f8f9fa; border-radius: 15px;">
        <p style="margin:0; color:#666;">누적 방문자</p>
        <p style="margin:0; font-size:2em; font-weight:800; color:#0068c9;">{display_num}</p>
    </div>""", unsafe_allow_html=True)

if __name__ == "__main__":
    main()
