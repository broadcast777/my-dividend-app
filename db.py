# ==========================================
# db.py : 데이터베이스 접속 및 토큰 관리 전용 파일
# ==========================================
import streamlit as st
from supabase import create_client, ClientOptions
from pathlib import Path
import time
import os
# [필수] 세션 ID 확인용 라이브러리
from streamlit.runtime.scriptrunner import get_script_run_ctx

# ---------------------------------------------------------
# [1] 파일 직통 저장소 (URL 릴레이 방식)
# ---------------------------------------------------------
class StreamlitFileStorageFixed:
    """
    사용자별로 격리된 파일에 토큰을 저장하고,
    URL 파라미터(old_id)를 통해 리다이렉트 후에도 세션을 연결합니다.
    """
    def __init__(self):
        try:
            ctx = get_script_run_ctx()
            self.current_id = ctx.session_id
        except:
            self.current_id = "unknown"

        # 꼬리표(old_id) 확인 및 연결 로직
        query_params = st.query_params
        if "old_id" in query_params:
            old_id = query_params["old_id"]
            old_file = Path(f"auth_token_{old_id}.json")
            self.storage_file = Path(f"auth_token_{self.current_id}.json")
            
            # 파일 이름표 바꿔달기 (마이그레이션)
            if old_file.exists() and not self.storage_file.exists():
                try:
                    old_file.rename(self.storage_file)
                except Exception as e:
                    print(f"세션 연결 실패: {e}")
        else:
            self.storage_file = Path(f"auth_token_{self.current_id}.json")

    def set_item(self, key: str, value: str) -> None:
        try:
            data = {}
            if self.storage_file.exists():
                with open(self.storage_file, 'r', encoding='utf-8') as f:
                    try: data = json.load(f)
                    except: pass
            data[key] = value
            with open(self.storage_file, 'w', encoding='utf-8') as f:
                json.dump(data, f)
        except Exception as e:
            print(f"Set Error: {e}")

    def get_item(self, key: str) -> str:
        try:
            if self.storage_file.exists():
                with open(self.storage_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    return data.get(key)
        except Exception as e:
            print(f"Get Error: {e}")
        return None

    def remove_item(self, key: str) -> None:
        try:
            if self.storage_file.exists():
                with open(self.storage_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                if key in data:
                    del data[key]
                    with open(self.storage_file, 'w', encoding='utf-8') as f:
                        json.dump(data, f)
        except Exception as e:
            print(f"Remove Error: {e}")

# ---------------------------------------------------------
# [2] Supabase 클라이언트 생성 함수
# ---------------------------------------------------------
def init_supabase():
    try:
        # Streamlit Cloud 배포 시 secrets에서 가져옴
        URL = st.secrets["SUPABASE_URL"]
        KEY = st.secrets["SUPABASE_KEY"]
        
        return create_client(
            URL, 
            KEY,
            options=ClientOptions(
                storage=StreamlitFileStorageFixed(),
                persist_session=True, 
                auto_refresh_token=True,
            )
        )
    except Exception as e:
        st.error(f"🚨 Supabase 연결 오류: {e}")
        return None

# ---------------------------------------------------------
# [3] 청소기 함수 (24시간 지난 토큰 삭제)
# ---------------------------------------------------------
def cleanup_old_tokens():
    try:
        now = time.time()
        retention_period = 86400  # 24시간
        for file_path in Path(".").glob("auth_token_*.json"):
            if now - file_path.stat().st_mtime > retention_period:
                try: file_path.unlink()
                except: pass
    except: pass
