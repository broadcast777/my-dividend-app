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

    # [추가] 세션 상태 키가 없으면 안전하게 생성 (윤활유 역할)
    if "code_processed" not in st.session_state:
        st.session_state.code_processed = False

    # 1. 기존 세션 확인 (이미 로그인된 경우 최우선 처리)
    try:
        session = supabase.auth.get_session()
        if session and session.user:
            # 이미 로그인된 상태에서 URL에 code가 남아있다면 정리만 하라고 신호 보냄
            if "code" in st.query_params:
                return True, session.user, "EXISTING_WITH_CODE"
            return True, session.user, "EXISTING"
    except: pass

    # 2. 로그인 콜백 처리 (카카오/구글 리다이렉트 후)
    query_params = st.query_params
    if "code" in query_params:
        # [방어 로직] 이미 처리 중이거나 처리 완료된 코드면 중복 실행 방지
        if st.session_state.code_processed:
            return False, None, None
            
        try:
            auth_code = query_params["code"]
            # [중요] 토큰 교환 직전에 플래그를 세워 중복 호출 차단
            st.session_state.code_processed = True
            
            auth_response = supabase.auth.exchange_code_for_session({"auth_code": auth_code})
            session = auth_response.session
            
            if session and session.user:
                return True, session.user, "CALLBACK"
        except Exception as e:
            err_msg = str(e).lower()
            # PKCE 보안 오류(Verifier missing) 발생 시 특별 처리
            if "verifier" in err_msg or "non-empty" in err_msg:
                # 에러 발생 시 플래그 리셋하여 재시도 가능케 함
                st.session_state.code_processed = False
                return False, None, "VERIFIER_ERROR"
            return False, str(e), "OTHER_ERROR"
            
    return False, None, None
