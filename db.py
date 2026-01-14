# ==========================================
# db.py : 데이터베이스 및 토큰 관리 (Read-Fallback 방식)
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
# [1] 파일 직통 저장소 (수정됨: 파일 이동 없이 읽기만 함)
# ---------------------------------------------------------
class StreamlitFileStorageFixed:
    """
    사용자별 토큰 저장소.
    파일을 옮기거나 이름을 바꾸지 않고,
    현재 파일에 데이터가 없으면 '옛날 파일(old_id)'을 읽어서 반환합니다.
    (파일 잠금/삭제 오류 원천 차단)
    """
    def __init__(self):
        try:
            ctx = get_script_run_ctx()
            self.current_id = ctx.session_id
        except:
            self.current_id = "unknown"

        # 1. 내 현재 사물함
        self.main_file = Path(f"auth_token_{self.current_id}.json")
        
        # 2. (만약 있다면) 옛날 사물함 위치 기억
        self.fallback_file = None
        if "old_id" in st.query_params:
            old_id = st.query_params["old_id"]
            self.fallback_file = Path(f"auth_token_{old_id}.json")

    def _read_json(self, file_path):
        """안전하게 파일 읽기"""
        if file_path and file_path.exists():
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except:
                return {}
        return {}

    def get_item(self, key: str) -> str:
        # 1. [우선순위 1] 현재 내 파일 뒤져보기
        data = self._read_json(self.main_file)
        if key in data:
            return data[key]
            
        # 2. [우선순위 2] 없으면 옛날 파일 뒤져보기 (Fail-safe)
        if self.fallback_file:
            data_old = self._read_json(self.fallback_file)
            if key in data_old:
                # 옛날 파일에 있으면 가져옴 (파일을 지우거나 옮기지 않음!)
                return data_old[key]
        return None

    def set_item(self, key: str, value: str) -> None:
        try:
            # 쓰기는 무조건 '현재 내 파일'에만 함
            data = self._read_json(self.main_file)
            data[key] = value
            with open(self.main_file, 'w', encoding='utf-8') as f:
                json.dump(data, f)
        except Exception as e:
            print(f"Set Error: {e}")

    def remove_item(self, key: str) -> None:
        try:
            # 현재 파일에서 삭제 시도
            data = self._read_json(self.main_file)
            if key in data:
                del data[key]
                with open(self.main_file, 'w', encoding='utf-8') as f:
                    json.dump(data, f)
            
            # 옛날 파일에서도 삭제 시도 (청소)
            if self.fallback_file:
                data_old = self._read_json(self.fallback_file)
                if key in data_old:
                    del data_old[key]
                    with open(self.fallback_file, 'w', encoding='utf-8') as f:
                        json.dump(data_old, f)
        except Exception as e:
            print(f"Remove Error: {e}")

# ---------------------------------------------------------
# [2] Supabase 클라이언트 생성 함수
# ---------------------------------------------------------
def init_supabase():
    try:
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
