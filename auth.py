# auth.py
import streamlit as st
import time
from db import init_supabase


class AuthManager:
    def __init__(self):
        self.supabase = init_supabase()
    
    def check_status(self):
        """인증 상태 확인 (자동 복구 로직 포함)"""
        if not self.supabase:
            return False
        
        # 1. 이미 로그인된 상태인지 확인
        try:
            session = self.supabase.auth.get_session()
            if session and session.user:
                st.session_state.is_logged_in = True
                st.session_state.user_info = session.user
                if "code" in st.query_params or "old_id" in st.query_params:
                    st.query_params.clear()
                return True
        except Exception:
            pass
        
        # 2. 로그인 콜백 처리
        query_params = st.query_params
        if "code" in query_params and not st.session_state.get("code_processed", False):
            st.session_state.code_processed = True
            try:
                auth_code = query_params["code"]
                auth_response = self.supabase.auth.exchange_code_for_session(
                    {"auth_code": auth_code}
                )
                session = auth_response.session
                if session and session.user:
                    st.session_state.is_logged_in = True
                    st.session_state.user_info = session.user
                    st.query_params.clear()
                    st.success("✅ 로그인되었습니다!")
                    st.rerun()
            except Exception as e:
                err_msg = str(e).lower()
                if "verifier" in err_msg or "non-empty" in err_msg:
                    st.warning("🔄 보안 토큰 갱신 중... 잠시만 기다려주세요.")
                    st.query_params.clear()
                    time.sleep(1.0)
                    st.rerun()
                else:
                    st.error(f"🔴 인증 오류: {e}")
                    st.query_params.clear()
        
        return False
    
    def render_ui(self):
        """로그인 UI 렌더링 (사이드바용)"""
        if not self.supabase:
            return
        
        is_logged_in = st.session_state.get("is_logged_in", False)
        user_info = st.session_state.get("user_info", None)
        
        if is_logged_in and user_info:
            email = user_info.email if user_info.email else "User"
            nickname = email.split("@")
            
            with st.sidebar:
                st.markdown("---")
                st.success(f"👋 반가워요! **{nickname}**님")
                if st.button("🚪 로그아웃", key="logout_btn_sidebar", use_container_width=True):
                    self.logout()
    
    def logout(self):
        """로그아웃 처리"""
        self.supabase.auth.sign_out()
        st.session_state.is_logged_in = False
        st.session_state.user_info = None
        st.session_state.code_processed = False
        st.rerun()
    
    def get_current_user(self):
        """현재 사용자 정보 반환"""
        return st.session_state.get("user_info", None)
    
    def is_authenticated(self):
        """로그인 여부"""
        return st.session_state.get("is_logged_in", False)
