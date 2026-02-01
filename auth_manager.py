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

    # 1. 기존 세션 확인 (이미 로그인 되어 있는지)
    try:
        session = supabase.auth.get_session()
        if session and session.user:
            st.session_state.is_logged_in = True
            st.session_state.user_info = session.user
            
            # [중요] 로그인 성공했으면 URL 찌꺼기 즉시 청소
            if "code" in st.query_params: 
                del st.query_params["code"]
                time.sleep(0.1)
                st.rerun()
            return 
    except Exception:
        pass

    # 2. OAuth 콜백 처리 (로그인 직후 돌아왔을 때)
    # [수정] code_processed 체크 로직 삭제 -> 무조건 시도하고 결과를 냄
    if "code" in st.query_params:
        auth_code = st.query_params["code"]
        try:
            # 인증 시도
            auth_response = supabase.auth.exchange_code_for_session({"auth_code": auth_code})
            session = auth_response.session
            
            if session and session.user:
                st.session_state.is_logged_in = True
                st.session_state.user_info = session.user
                logger.info(f"👤 사용자 로그인 성공: {session.user.email}")
                st.success("✅ 로그인되었습니다!")
            
            # 성공 시 URL 청소 및 리런
            if "code" in st.query_params: del st.query_params["code"]
            time.sleep(0.1)
            st.rerun()

        except Exception as e:
            logger.error(f"🚨 [Auth Error] 인증 예외: {str(e)}", exc_info=True)
            
            # 실패해도 무조건 URL 청소 (그래야 무한로딩 안 걸림)
            if "code" in st.query_params: del st.query_params["code"]
            
            # 토큰 갱신 이슈면 잠시 대기 후 리런
            if "verifier" in str(e).lower() or "non-empty" in str(e).lower():
                st.warning("🔄 보안 토큰 갱신 중... 잠시만 기다려주세요.")
                time.sleep(1.0)
                st.rerun()
            else:
                st.error(f"🔴 인증 오류가 발생했습니다. 다시 시도해주세요. ({e})")

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
    [UI] 소셜 로그인 버튼 렌더링 (카카오/구글)
    """
    try:
        ctx = get_script_run_ctx()
        current_session_id = ctx.session_id
    except: current_session_id = "unknown"
    
    # 로그인 후 돌아올 주소 (불필요한 파라미터 제거)
    redirect_url = f"https://dividend-pange.streamlit.app"

    if key_suffix != "top_header":
        st.caption("🔒 기능을 사용하려면 로그인이 필요합니다.")
        
    col1, col2 = st.columns(2)
    with col1:
        try:
            res_kakao = supabase.auth.sign_in_with_oauth({
                "provider": "kakao", 
                "options": {"redirect_to": redirect_url, "skip_browser_redirect": True}
            })
            if res_kakao.url:
                st.markdown(f'''<a href="{res_kakao.url}" target="_blank" class="kakao-login-btn">💬 카카오로 3초 만에 시작</a>''', unsafe_allow_html=True)
        except: st.error("Kakao 오류")
        
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
                    st.markdown(f'<meta http-equiv="refresh" content="0;url={res_google.url}">', unsafe_allow_html=True)
                    st.stop()
            except: pass
