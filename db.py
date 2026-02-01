"""
프로젝트: 배당 팽이 (Dividend Top) v1.7 (Refined)
파일명: db.py
설명: Supabase DB 연동 및 암호화된 사용자 세션 관리 (내구성/안전성 강화)
"""

import streamlit as st
from supabase import create_client, ClientOptions, Client
from pathlib import Path
import json
import time
import os
from streamlit.runtime.scriptrunner import get_script_run_ctx
from cryptography.fernet import Fernet

# ---------------------------------------------------------
# [SECTION 1] 보안 강화된 토큰 저장소 (암호화 공정)
# ---------------------------------------------------------

class StreamlitFileStorageFixed:
    def __init__(self):
        try:
            ctx = get_script_run_ctx()
            self.current_id = ctx.session_id
        except:
            self.current_id = "unknown"

        self.main_file = Path(f"auth_token_{self.current_id}.json")
        self.fallback_file = None
        if "old_id" in st.query_params:
            old_id = st.query_params["old_id"]
            self.fallback_file = Path(f"auth_token_{old_id}.json")

        try:
            key = st.secrets["ENCRYPTION_KEY"].encode()
            self.cipher_suite = Fernet(key)
        except Exception:
            st.error("🔑 보안 설정(ENCRYPTION_KEY)이 누락되었습니다. 관리자 설정을 확인하세요.")
            st.stop()

    def _encrypt(self, value: str) -> str:
        if not value: return value
        try:
            return self.cipher_suite.encrypt(value.encode()).decode()
        except Exception as e:
            print(f"Encryption Error: {e}")
            return ""

    def _decrypt(self, encrypted_value: str) -> str:
        if not encrypted_value: return ""
        try:
            return self.cipher_suite.decrypt(encrypted_value.encode()).decode()
        except Exception:
            return ""

    def _read_json(self, file_path):
        if file_path and file_path.exists():
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    return {k: self._decrypt(v) for k, v in data.items() if self._decrypt(v)}
            except Exception:
                return {}
        return {}

    def get_item(self, key: str) -> str:
        data = self._read_json(self.main_file)
        if key in data: return data[key]
        if self.fallback_file:
            data_old = self._read_json(self.fallback_file)
            if key in data_old: return data_old[key]
        return None

    def set_item(self, key: str, value: str) -> None:
        try:
            data = self._read_json(self.main_file)
            data[key] = value 
            final_to_save = {k: self._encrypt(v) for k, v in data.items()}
            with open(self.main_file, 'w', encoding='utf-8') as f:
                json.dump(final_to_save, f)
        except Exception as e:
            print(f"Set Error: {e}")

    def remove_item(self, key: str) -> None:
        try:
            for f_path in [self.main_file, self.fallback_file]:
                if f_path and f_path.exists():
                    data = self._read_json(f_path)
                    if key in data:
                        del data[key]
                        enc_data = {k: self._encrypt(v) for k, v in data.items()}
                        with open(f_path, 'w', encoding='utf-8') as f:
                            json.dump(enc_data, f)
        except: pass

# ---------------------------------------------------------
# [SECTION 2] Supabase 클라이언트 초기화
# ---------------------------------------------------------

def init_supabase():
    try:
        URL = st.secrets["SUPABASE_URL"]
        KEY = st.secrets["SUPABASE_KEY"]
        return create_client(
            URL, KEY,
            options=ClientOptions(
                storage=StreamlitFileStorageFixed(),
                persist_session=True, 
                auto_refresh_token=True,
            )
        )
    except Exception as e:
        st.error(f"🚨 데이터베이스 연결 실패: 잠시 후 다시 시도해주세요.")
        return None

# ---------------------------------------------------------
# [SECTION 3] 시스템 관리 (토큰 청소)
# ---------------------------------------------------------

def cleanup_old_tokens():
    """오래된 세션 파일 정리 (완전 무소음 모드)"""
    try:
        now = time.time()
        # glob 패턴 매칭 및 파일 접근 시 발생할 수 있는 모든 에러 방어
        for file_path in Path(".").glob("auth_token_*.json"):
            try:
                if file_path.exists() and now - file_path.stat().st_mtime > 86400: # 24시간
                    file_path.unlink()
            except Exception:
                continue 
    except Exception:
        pass

# ---------------------------------------------------------
# [SECTION 4] 데이터베이스 CRUD 기능 (창고 로봇)
# ---------------------------------------------------------

def safe_execute(query):
    """CRUD 공통 예외 처리 래퍼 (중복 코드 제거용)"""
    try:
        return query.execute()
    except Exception as e:
        # 에러 발생 시 사용자에게 알림 (선택 사항)
        # st.error(f"데이터 처리 중 오류 발생: {e}") 
        return None

def get_user_portfolios(supabase: Client, user_id: str):
    """사용자의 포트폴리오 리스트 조회"""
    query = supabase.table("portfolios").select("*").eq("user_id", user_id).order("created_at", desc=True)
    return safe_execute(query)

def delete_portfolio(supabase: Client, portfolio_id: str):
    """특정 포트폴리오 삭제"""
    query = supabase.table("portfolios").delete().eq("id", portfolio_id)
    return safe_execute(query)

def get_portfolio_count(supabase: Client, user_id: str):
    """포트폴리오 총 개수 확인"""
    query = supabase.table("portfolios").select("id", count="exact").eq("user_id", user_id)
    return safe_execute(query)

def insert_portfolio(supabase: Client, data: dict):
    """새 포트폴리오 저장"""
    query = supabase.table("portfolios").insert(data)
    return safe_execute(query)

def update_portfolio(supabase: Client, portfolio_id: str, data: dict):
    """기존 포트폴리오 수정"""
    query = supabase.table("portfolios").update(data).eq("id", portfolio_id)
    return safe_execute(query)

# ---------------------------------------------------------
# [SECTION 5] 분석 및 로그 기능 (출입 명부)
# ---------------------------------------------------------

def log_visit(supabase: Client, source_tag: str):
    """방문 기록 로그 작성 (실패해도 무시)"""
    try:
        supabase.table("visit_logs").insert({"referer": source_tag}).execute()
    except: pass

def get_visit_count(supabase: Client):
    """누적 방문자 수 조회"""
    try:
        return supabase.table("visit_counts").select("count").eq("id", 1).execute()
    except: return None

def update_visit_count(supabase: Client, new_count: int):
    """누적 방문자 수 업데이트"""
    try:
        return supabase.table("visit_counts").update({"count": new_count}).eq("id", 1).execute()
    except: return None
