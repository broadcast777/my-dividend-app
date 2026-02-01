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
    (무한 로딩 방지 로직 포함)
    """
    if not supabase: return

    # 1. [우선순위 1] URL에 인증 코드(?code=...)가 있는지 확인
    if "code" in st.query_params:
        auth_code = st.query_params["code"]
        
        # 🚨 [핵심] 처리 전 일단 URL 파라미터부터 날림 (무한로딩 원천 봉쇄)
        st.query_params.clear()
        
        try:
            # 토큰 교환 시도
            auth_response = supabase.auth.exchange_code_for_session({"auth_code": auth_code})
            session = auth_response.session
            
            if session and session.user:
                st.session_state.is_logged_in = True
                st.session_state.user_info = session.user
                logger.info(f"👤 사용자 로그인 성공: {session.user.email}")
                st.success("✅ 로그인되었습니다!")
                time.sleep(0.5)
                st.rerun() # 새로고침
                
        except Exception as e:
            logger.error(f"🚨 [Auth Error] 인증 실패: {str(e)}", exc_info=True)
            st.error("⚠️ 로그인 처리 중 오류가 발생했습니다. 다시 시도해 주세요.")
            return

    # 2. [우선순위 2] 기존 세션 확인 (이미 로그인 된 상태인지)
    try:
        session = supabase.auth.get_session()
        if session and session.user:
            st.session_state.is_logged_in = True
            st.session_state.user_info = session.user
            return 
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
                
                # 세션 초기화
                st.session_state.is_logged_in = False
                st.session_state.user_info = None
                
                # 로그아웃 후 URL 정리 및 리런
                st.query_params.clear()
                st.rerun()

def render_login_buttons(supabase, key_suffix="default"):
    """
    [UI] 소셜 로그인 버튼 렌더링 (사장님 원본 코드 복원 완료)
    """
    try:
        ctx = get_script_run_ctx()
        current_session_id = ctx.session_id
    except: current_session_id = "unknown"
    
    # 리다이렉트 URL (루트 경로)
    redirect_url = "https://dividend-pange.streamlit.app"

    if key_suffix != "top_header":
        st.caption("🔒 기능을 사용하려면 로그인이 필요합니다.")
        
    col1, col2 = st.columns(2)
    
    # -------------------------------------------------------
    # [1] 카카오 로그인 (사장님 원본 로직 복구: 새 창 열기)
    # -------------------------------------------------------
    with col1:
        try:
            res_kakao = supabase.auth.sign_in_with_oauth({
                "provider": "kakao", 
                "options": {
                    "redirect_to": redirect_url, 
                    "skip_browser_redirect": True  # 👈 핵심: 브라우저 자동 리다이렉트 막음
                }
            })
            if res_kakao.url:
                # 👈 핵심: target="_blank"로 새 창에서 열기 (사장님 코드 그대로!)
                st.markdown(f'''<a href="{res_kakao.url}" target="_blank" class="kakao-login-btn">💬 카카오로 3초 만에 시작</a>''', unsafe_allow_html=True)
        except: 
            st.error("Kakao 오류")
            
    # -------------------------------------------------------
    # [2] 구글 로그인 (사장님 원본 로직 복구: 메타 리프레시)
    # -------------------------------------------------------
    with col2:
        if st.button("🔵 Google로 시작하기(PC/크롬 권장)", key=f"btn_google_{key_suffix}", use_container_width=True):
            try:
                res_google = supabase.auth.sign_in_with_oauth({
                    "provider": "google", 
                    "options": {
                        "redirect_to": redirect_url, 
                        "queryParams": {"access_type": "offline", "prompt": "consent"}, 
                        "skip_browser_redirect": False
                    }
                })
                if res_google.url:
                    # 👈 핵심: 메타 태그로 즉시 이동
                    st.markdown(f'<meta http-equiv="refresh" content="0;url={res_google.url}">', unsafe_allow_html=True)
                    st.stop()
            except: pass
