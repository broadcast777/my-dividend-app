# auth.py 전체 덮어쓰기 하세요
import streamlit as st
import hashlib
import time

def verify_admin(password_input):
    ADMIN_HASH = "c41b0bb392db368a44ce374151794850417b56c9786e3c482f825327c7153182"
    if not password_input: return False
    return hashlib.sha256(password_input.encode()).hexdigest() == ADMIN_HASH

def check_auth_logic(supabase):
    if not supabase: return False, None, "NO_SUPABASE"

    if "code_processed" not in st.session_state:
        st.session_state.code_processed = False

    # 1. 이미 세션이 있는 경우
    try:
        session = supabase.auth.get_session()
        if session and session.user:
            if "code" in st.query_params: return True, session.user, "EXISTING_WITH_CODE"
            return True, session.user, "EXISTING"
    except: pass

    # 2. 콜백 처리
    query_params = st.query_params
    if "code" in query_params:
        # 이미 처리했거나 에러가 났던 코드라면 무시
        if st.session_state.code_processed:
            return False, None, "ALREADY_DONE"
            
        try:
            auth_code = query_params["code"]
            st.session_state.code_processed = True # 시도 기록
            auth_response = supabase.auth.exchange_code_for_session({"auth_code": auth_code})
            if auth_response.session and auth_response.session.user:
                return True, auth_response.session.user, "CALLBACK_SUCCESS"
        except Exception as e:
            err_msg = str(e).lower()
            if "verifier" in err_msg: return False, None, "VERIFIER_ERROR"
            return False, str(e), "AUTH_FAILED"
            
    return False, None, "IDLE"
