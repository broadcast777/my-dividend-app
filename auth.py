import streamlit as st
import hashlib
import time

# ==========================================
# [1] 관리자 비밀번호 검증 엔진
# ==========================================
def verify_admin(password_input):
    """비밀번호 해시 비교 로직 (순수 로직)"""
    ADMIN_HASH = "c41b0bb392db368a44ce374151794850417b56c9786e3c482f825327c7153182"
    if not password_input:
        return False
    return hashlib.sha256(password_input.encode()).hexdigest() == ADMIN_HASH

# ==========================================
# [2] 인증 상태 체크 엔진 (Supabase 로직 분리)
# ==========================================
def check_auth_logic(supabase):
    """
    Supabase 세션 및 콜백 로직 처리
    - return: (성공여부, 사용자정보, 에러타입)
    """
    if not supabase: return False, None, None

    # 1. 기존 세션 확인
    try:
        session = supabase.auth.get_session()
        if session and session.user:
            return True, session.user, "EXISTING"
    except: pass

    # 2. 로그인 콜백 처리
    query_params = st.query_params
    if "code" in query_params and not st.session_state.get("code_processed", False):
        try:
            auth_code = query_params["code"]
            auth_response = supabase.auth.exchange_code_for_session({"auth_code": auth_code})
            session = auth_response.session
            if session and session.user:
                st.session_state.code_processed = True
                return True, session.user, "CALLBACK"
        except Exception as e:
            err_msg = str(e).lower()
            if "verifier" in err_msg or "non-empty" in err_msg:
                return False, None, "VERIFIER_ERROR"
            return False, str(e), "OTHER_ERROR"
            
    return False, None, None
