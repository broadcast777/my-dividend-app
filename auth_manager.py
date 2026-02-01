"""
모듈명: auth_manager.py
설명: 사용자 인증(로그인/로그아웃/세션) 관리 전담
"""
import streamlit as st
import time
from streamlit.runtime.scriptrunner import get_script_run_ctx
from logger import logger

def check_auth_status(supabase):
    """
    [로직] 앱 시작 시 로그인 세션 확인 및 OAuth 콜백 처리
    """
    if not supabase: return

    # 1. [우선순위 1] URL에 인증 코드가 있으면 처리
    if "code" in st.query_params:
        auth_code = st.query_params["code"]
        
        # 무한 로딩 방지를 위해 URL 파라미터 미리 삭제
        st.query_params.clear()
        
        try:
            auth_response = supabase.auth.exchange_code_for_session({"auth_code": auth_code})
            session = auth_response.session
            
            if session and session.user:
                st.session_state.is_logged_in = True
                st.session_state.user_info = session.user
                logger.info(f"👤 사용자 로그인 성공: {session.user.email}")
                st.success("✅ 로그인되었습니다!")
                time.sleep(0.5)
                st.rerun()
                
        except Exception as e:
            logger.error(f"🚨 인증 실패: {str(e)}")
            st.error("로그인 중 오류가 발생했습니다.")
            return

    # 2. [우선순위 2] 기존 세션 확인
    try:
        session = supabase.auth.get_session()
        if session and session.user:
            st.session_state.is_logged_in = True
            st.session_state.user_info = session.user
    except Exception:
        pass

def render_login_ui(supabase):
    """
    [UI] 사이드바 상단: 로그인 사용자 정보 및 로그아웃 버튼
    """
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
                st.query_params.clear()
                st.rerun()

def render_login_buttons(supabase, key_suffix="default"):
    """
    [UI] 소셜 로그인 버튼 (사장님 원본 코드 100% 복구)
    """
    try:
        ctx = get_script_run_ctx()
        current_session_id = ctx.session_id
    except: current_session_id = "unknown"
    
    # 사장님 원본 리다이렉트 URL 생성 로직
    redirect_url = f"https://dividend-pange.streamlit.app?old_id={current_session_id}"

    if key_suffix != "top_header":
        st.caption("🔒 기능을 사용하려면 로그인이 필요합니다.")
        
    col1, col2 = st.columns(2)
    
    # -------------------------------------------------------------
    # [1] 카카오 (사장님 원본: skip_browser_redirect=True + 새창 띄우기)
    # -------------------------------------------------------------
    with col1:
        try:
            res_kakao = supabase.auth.sign_in_with_oauth({
                "provider": "kakao", 
                "options": {
                    "redirect_to": redirect_url, 
                    "skip_browser_redirect": True 
                }
            })
            if res_kakao.url:
                # 사장님 원본 HTML 코드 그대로
                st.markdown(f'''<a href="{res_kakao.url}" target="_blank" class="kakao-login-btn">💬 카카오로 3초 만에 시작</a>''', unsafe_allow_html=True)
        except: 
            st.error("Kakao 오류")
            
    # -------------------------------------------------------------
    # [2] 구글 (사장님 원본: skip_browser_redirect=False + 메타 리프레시)
    # -------------------------------------------------------------
    with col2:
        if st.button("🔵 Google로 시작하기(PC/크롬 권장)", key=f"btn_google_{key_suffix}", use_container_width=True):
            try:
                res_google = supabase.auth.sign_in_with_oauth({
                    "provider": "google", 
                    "options": {
                        "redirect_to": redirect_url, 
                        "queryParams": {"access_type": "offline", "prompt": "consent"}, 
                        "skip_browser_redirect": False # 원본대로 False 유지
                    }
                })
                # 혹시라도 url이 반환되면 강제 이동
                if res_google.url:
                    st.markdown(f'<meta http-equiv="refresh" content="0;url={res_google.url}">', unsafe_allow_html=True)
                    st.stop()
            except: pass
