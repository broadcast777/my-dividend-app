# components.py
import streamlit as st
import hashlib


class SidebarManager:
    def __init__(self, supabase, auth_manager):
        self.supabase = supabase
        self.auth_manager = auth_manager
    
    def render_menu(self):
        """메뉴 렌더링"""
        with st.sidebar:
            if not self.auth_manager.is_authenticated():
                st.markdown("---")
                return st.radio(
                    "📂 **메뉴 이동**",
                    ["💰 배당금 계산기", "📃 전체 종목 리스트"],
                    label_visibility="visible"
                )
        return None
    
    def render_portfolio_loader(self):
        """포트폴리오 불러오기"""
        if not self.auth_manager.is_authenticated():
            st.caption("🔒 로그인이 필요합니다.")
            return None
        
        with st.sidebar:
            with st.expander("📂 불러오기 / 관리"):
                try:
                    uid = self.auth_manager.get_current_user().id
                    resp = self.supabase.table("portfolios") \
                        .select("*") \
                        .eq("user_id", uid) \
                        .order("created_at", desc=True) \
                        .execute()
                    
                    if resp.data:
                        opts = {}
                        for p in resp.data:
                            date_str = p['created_at'][5:10]
                            time_str = p['created_at'][11:16]
                            name = p.get('name') or '이름없음'
                            label = f"{name} ({date_str} {time_str})"
                            opts[label] = p
                        
                        sel_name = st.selectbox(
                            "항목 선택", 
                            list(opts.keys()), 
                            label_visibility="collapsed"
                        )
                        
                        is_delete_mode = st.toggle("🗑️ 삭제 모드 켜기")
                        
                        if is_delete_mode:
                            if st.button("🚨 영구 삭제", type="primary", use_container_width=True):
                                target_id = opts[sel_name]['id']
                                self.supabase.table("portfolios") \
                                    .delete() \
                                    .eq("id", target_id) \
                                    .execute()
                                st.toast("삭제되었습니다.", icon="🗑️")
                                st.rerun()
                        else:
                            if st.button("📂 불러오기", use_container_width=True):
                                data = opts[sel_name]['ticker_data']
                                st.session_state.total_invest = int(data.get('total_money', 30000000))
                                st.session_state.selected_stocks = list(data.get('composition', {}).keys())
                                st.toast("성공적으로 불러왔습니다!", icon="✅")
                                st.rerun()
                    else:
                        st.caption("저장된 기록이 없습니다.")
                
                except Exception as e:
                    st.error("불러오기 실패")


class AdminValidator:
    """관리자 인증"""
    
    @staticmethod
    def check_admin_access():
        from config import ADMIN_PASSWORD_HASH
        
        if st.query_params.get("admin", "false").lower() == "true":
            with st.expander("🔐 관리자 접속 (Admin)", expanded=False):
                password_input = st.text_input("비밀번호 입력", type="password")
                if password_input:
                    if hashlib.sha256(password_input.encode()).hexdigest() == ADMIN_PASSWORD_HASH:
                        return True
                    else:
                        st.error("비밀번호 불일치")
        return False
