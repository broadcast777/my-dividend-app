"""
프로젝트: 배당 팽이 (Dividend Top) v1.5
파일명: db.py
설명: Supabase DB 연동 및 사용자 세션(토큰) 관리 로직
핵심 기능: 
 1. Streamlit 세션 만료 대비 토큰 Fallback 저장소 구현
 2. 사용자 포트폴리오 CRUD (생성, 조회, 수정, 삭제)
 3. 방문자 통계 및 로그 기록
"""

import streamlit as st
from supabase import create_client, ClientOptions, Client
from pathlib import Path
import json
import time
import os
from streamlit.runtime.scriptrunner import get_script_run_ctx

# ---------------------------------------------------------
# [SECTION 1] 사용자별 토큰 저장소 클래스 (Session Persistence)
# ---------------------------------------------------------

class StreamlitFileStorageFixed:
    """
    Streamlit 환경에서 Supabase 세션 토큰을 안전하게 유지하는 커스텀 저장소입니다.
    
    [특징]
    - 파일 Rename 없이 읽기 권한을 우선하여 새로고침 시 세션 소멸 문제를 방지합니다.
    - 현재 세션 ID(current_id) 외에도 쿼리 파라미터의 옛날 ID(old_id) 파일을 참조하는 
      Fallback 기능을 포함합니다.
    """
    def __init__(self):
        try:
            # 현재 Streamlit 세션 컨텍스트에서 고유 ID 추출
            ctx = get_script_run_ctx()
            self.current_id = ctx.session_id
        except:
            self.current_id = "unknown"

        # 1. 메인 사물함: 현재 세션 기반의 토큰 파일 경로
        self.main_file = Path(f"auth_token_{self.current_id}.json")
        
        # 2. 백업 사물함: URL 파라미터에 old_id가 있을 경우 해당 파일 경로 기억
        self.fallback_file = None
        if "old_id" in st.query_params:
            old_id = st.query_params["old_id"]
            self.fallback_file = Path(f"auth_token_{old_id}.json")

    def _read_json(self, file_path):
        """지정한 경로의 JSON 파일을 안전하게 읽어오는 내부 헬퍼 함수"""
        if file_path and file_path.exists():
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except:
                return {}
        return {}

    def get_item(self, key: str) -> str:
        """토큰 정보를 가져올 때: 현재 파일 탐색 후, 없으면 옛날 파일(Fallback) 탐색"""
        # 1. [우선순위 1] 현재 세션 파일 확인
        data = self._read_json(self.main_file)
        if key in data:
            return data[key]
            
        # 2. [우선순위 2] 없으면 이전 세션 파일 확인 (세션 끊김 방어)
        if self.fallback_file:
            data_old = self._read_json(self.fallback_file)
            if key in data_old:
                return data_old[key]
        return None

    def set_item(self, key: str, value: str) -> None:
        """토큰 정보 저장: 쓰기 작업은 항상 '현재 세션 파일'에만 수행"""
        try:
            data = self._read_json(self.main_file)
            data[key] = value
            with open(self.main_file, 'w', encoding='utf-8') as f:
                json.dump(data, f)
        except Exception as e:
            print(f"Set Error: {e}")

    def remove_item(self, key: str) -> None:
        """토큰 삭제 (로그아웃 등): 현재 파일과 옛날 파일을 모두 청소"""
        try:
            # 현재 파일에서 삭제
            data = self._read_json(self.main_file)
            if key in data:
                del data[key]
                with open(self.main_file, 'w', encoding='utf-8') as f:
                    json.dump(data, f)
            
            # 옛날 파일에서도 삭제
            if self.fallback_file:
                data_old = self._read_json(self.fallback_file)
                if key in data_old:
                    del data_old[key]
                    with open(self.fallback_file, 'w', encoding='utf-8') as f:
                        json.dump(data_old, f)
        except Exception as e:
            print(f"Remove Error: {e}")


# ---------------------------------------------------------
# [SECTION 2] Supabase 클라이언트 초기화
# ---------------------------------------------------------

def init_supabase():
    """st.secrets를 사용하여 Supabase 클라이언트를 초기화하고 반환합니다."""
    try:
        URL = st.secrets["SUPABASE_URL"]
        KEY = st.secrets["SUPABASE_KEY"]
        
        return create_client(
            URL, 
            KEY,
            options=ClientOptions(
                storage=StreamlitFileStorageFixed(), # 커스텀 토큰 저장소 적용
                persist_session=True, 
                auto_refresh_token=True,
            )
        )
    except Exception as e:
        st.error(f"🚨 Supabase 연결 오류: {e}")
        return None


# ---------------------------------------------------------
# [SECTION 3] 시스템 관리 (토큰 청소)
# ---------------------------------------------------------

def cleanup_old_tokens():
    """서버 공간 관리를 위해 생성된 지 24시간이 지난 임시 토큰 파일(.json)을 삭제합니다."""
    try:
        now = time.time()
        retention_period = 86400  # 24시간 (초 단위)
        for file_path in Path(".").glob("auth_token_*.json"):
            if now - file_path.stat().st_mtime > retention_period:
                try: file_path.unlink()
                except: pass
    except: pass


# ---------------------------------------------------------
# [SECTION 4] 데이터베이스 CRUD 기능 (모듈화용)
# ---------------------------------------------------------

def get_user_portfolios(supabase: Client, user_id: str):
    """사용자의 포트폴리오 리스트를 최신 등록순으로 조회합니다."""
    return supabase.table("portfolios") \
        .select("*") \
        .eq("user_id", user_id) \
        .order("created_at", desc=True) \
        .execute()

def delete_portfolio(supabase: Client, portfolio_id: str):
    """DB에서 특정 포트폴리오 기록을 삭제합니다."""
    return supabase.table("portfolios") \
        .delete() \
        .eq("id", portfolio_id) \
        .execute()

def get_portfolio_count(supabase: Client, user_id: str):
    """사용자가 현재까지 저장한 포트폴리오의 총 개수를 반환합니다."""
    return supabase.table("portfolios") \
        .select("id", count="exact") \
        .eq("user_id", user_id) \
        .execute()

def insert_portfolio(supabase: Client, data: dict):
    """새로운 포트폴리오 데이터를 DB에 저장합니다."""
    return supabase.table("portfolios").insert(data).execute()

def update_portfolio(supabase: Client, portfolio_id: str, data: dict):
    """이미 존재하는 포트폴리오 데이터를 수정합니다."""
    return supabase.table("portfolios") \
        .update(data) \
        .eq("id", portfolio_id) \
        .execute()


# ---------------------------------------------------------
# [SECTION 5] 분석 및 로그 기능
# ---------------------------------------------------------

def log_visit(supabase: Client, source_tag: str):
    """방문 경로(Referer)를 포함하여 방문 로그를 기록합니다."""
    return supabase.table("visit_logs").insert({"referer": source_tag}).execute()

def get_visit_count(supabase: Client):
    """ visit_counts 테이블에서 전체 누적 방문자 수를 조회합니다."""
    return supabase.table("visit_counts").select("count").eq("id", 1).execute()

def update_visit_count(supabase: Client, new_count: int):
    """ visit_counts 테이블의 누적 방문자 수를 새 수치로 업데이트합니다."""
    return supabase.table("visit_counts").update({"count": new_count}).eq("id", 1).execute()
