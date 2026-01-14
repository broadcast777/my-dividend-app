# ==========================================
# db.py : 데이터베이스 및 토큰 관리 (Fail-safe 강화판)
# ==========================================
import streamlit as st
from supabase import create_client, ClientOptions
from pathlib import Path
import json
import time
import os
# [필수] 세션 ID 확인용
from streamlit.runtime.scriptrunner import get_script_run_ctx

# ---------------------------------------------------------
# [1] 파일 직통 저장소 (지연 마이그레이션 적용)
# ---------------------------------------------------------
class StreamlitFileStorageFixed:
    """
    사용자별 토큰 저장소.
    초기에 파일을 못 찾으면, URL의 old_id를 추적하여
    데이터를 요청하는 시점(get_item)에 파일을 찾아오는 '지연 마이그레이션' 방식 적용.
    """
    def __init__(self):
        try:
            ctx = get_script_run_ctx()
            self.current_id = ctx.session_id
        except:
            self.current_id = "unknown"

        self.storage_file = Path(f"auth_token_{self.current_id}.json")
        self.old_file = None

        # URL에 꼬리표(old_id)가 있으면 옛날 파일 경로도 기억해둠
        query_params = st.query_params
        if "old_id" in query_params:
            old_id = query_params["old_id"]
            self.old_file = Path(f"auth_token_{old_id}.json")

    def set_item(self, key: str, value: str) -> None:
        try:
            data = {}
            # 현재 파일 읽기 시도
            if self.storage_file.exists():
                with open(self.storage_file, 'r', encoding='utf-8') as f:
                    try: data = json.load(f)
                    except: pass
            
            data[key] = value
            
            # 파일 쓰기
            with open(self.storage_file, 'w', encoding='utf-8') as f:
                json.dump(data, f)
        except Exception as e:
            print(f"Set Error: {e}")

    def get_item(self, key: str) -> str:
        try:
            # 1. [정석] 현재 내 ID로 된 파일이 있으면 거기서 읽음
            if self.storage_file.exists():
                with open(self.storage_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    val = data.get(key)
                    if val: return val # 데이터 있으면 바로 리턴

            # 2. [구조대] 현재 파일에 없는데, 옛날 ID(old_id)가 있다면?
            # -> 옛날 사물함(old_file)을 뒤져본다! (여기가 핵심)
            if self.old_file and self.old_file.exists():
                with open(self.old_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    val = data.get(key)
                    
                    if val:
                        # 옛날 파일에서 데이터를 찾았으면 -> 현재 파일로 이사 시킴 (마이그레이션)
                        self.set_item(key, val)
                        # 옛날 파일은 이제 삭제해도 됨
                        try: self.old_file.unlink()
                        except: pass
                        return val
                        
        except Exception as e:
            print(f"Get Error: {e}")
        return None

    def remove_item(self, key: str) -> None:
        try:
            target_file = self.storage_file
            # 파일이 없으면 옛날 파일이라도 지움
            if not target_file.exists() and self.old_file and self.old_file.exists():
                target_file = self.old_file

            if target_file.exists():
                with open(target_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                if key in data:
                    del data[key]
                    with open(target_file, 'w', encoding='utf-8') as f:
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
            # 파일이 생성된 지 24시간 넘었으면 삭제
            if now - file_path.stat().st_mtime > retention_period:
                try: file_path.unlink()
                except: pass
    except: pass
