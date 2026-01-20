"""
프로젝트: 배당 팽이 (Dividend Top) v2.0
파일명: db.py
설명: Supabase DB 연동 및 암호화된 사용자 세션 관리 (보안 및 안정성 강화 버전)
핵심 기능: 
 1. 토큰 암호화(Fernet) 모듈 분리 및 예외 처리 강화
 2. 사용자 포트폴리오 CRUD (저장, 조회, 수정, 삭제) 안전장치 적용
 3. 방문자 통계 및 로그 기록
"""

import streamlit as st
from supabase import create_client, ClientOptions, Client
from pathlib import Path
import json
import time
import os
from streamlit.runtime.scriptrunner import get_script_run_ctx
from cryptography.fernet import Fernet
from logger import logger # 로깅 시스템 연동

# ---------------------------------------------------------
# [SECTION 1] 보안 암호화 매니저 (The Vault)
# ---------------------------------------------------------

class CipherManager:
    """암호화/복호화를 전담하는 보안 관리자"""
    def __init__(self):
        try:
            key = st.secrets["ENCRYPTION_KEY"]
            if not key: raise ValueError("키 없음")
            self.cipher_suite = Fernet(key.encode())
        except Exception as e:
            logger.critical(f"🔐 암호화 키 로드 실패: {e}")
            # 키가 없으면 작동 중지 (보안 필수)
            st.error("시스템 보안 설정 오류. 관리자에게 문의하세요.")
            st.stop()

    def encrypt(self, text: str) -> str:
        if not text: return ""
        try:
            return self.cipher_suite.encrypt(text.encode()).decode()
        except Exception as e:
            logger.error(f"암호화 실패: {e}")
            return text # 실패 시 원문 유지 (또는 빈값)

    def decrypt(self, text: str) -> str:
        if not text: return ""
        try:
            return self.cipher_suite.decrypt(text.encode()).decode()
        except Exception:
            # 복호화 실패(키 불일치 등) 시 조용히 무시하고 빈 값 반환
            return ""

# 전역 암호화 객체 생성
cipher_manager = CipherManager()


# ---------------------------------------------------------
# [SECTION 2] 보안 강화된 토큰 저장소 (File Storage)
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

    def _read_json(self, file_path):
        """파일을 읽을 때 자동으로 암호를 해독합니다."""
        if file_path and file_path.exists():
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    # 복호화 실패 시 해당 키는 무시됨
                    return {k: cipher_manager.decrypt(v) for k, v in data.items() if v}
            except Exception as e:
                logger.warning(f"토큰 파일 읽기 오류: {e}")
                return {}
        return {}

    def get_item(self, key: str) -> str:
        data = self._read_json(self.main_file)
        if key in data and data[key]: return data[key]
        
        if self.fallback_file:
            data_old = self._read_json(self.fallback_file)
            if key in data_old and data_old[key]: return data_old[key]
        return None

    def set_item(self, key: str, value: str) -> None:
        """저장 시 암호화하여 저장합니다."""
        try:
            data = self._read_json(self.main_file)
            data[key] = value 
            final_to_save = {k: cipher_manager.encrypt(v) for k, v in data.items()}
            with open(self.main_file, 'w', encoding='utf-8') as f:
                json.dump(final_to_save, f)
        except Exception as e:
            logger.error(f"토큰 저장 실패: {e}")

    def remove_item(self, key: str) -> None:
        try:
            for f_path in [self.main_file, self.fallback_file]:
                if f_path and f_path.exists():
                    data = self._read_json(f_path)
                    if key in data:
                        del data[key]
                        enc_data = {k: cipher_manager.encrypt(v) for k, v in data.items()}
                        with open(f_path, 'w', encoding='utf-8') as f:
                            json.dump(enc_data, f)
        except Exception as e:
            logger.error(f"토큰 삭제 실패: {e}")


# ---------------------------------------------------------
# [SECTION 3] Supabase 클라이언트 초기화
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
        logger.critical(f"🚨 Supabase 연결 치명적 오류: {e}")
        st.error("데이터베이스 연결에 실패했습니다. 잠시 후 다시 시도해주세요.")
        return None


# ---------------------------------------------------------
# [SECTION 4] 시스템 관리 (토큰 청소)
# ---------------------------------------------------------

def cleanup_old_tokens():
    """오래된(24시간 경과) 인증 토큰 파일 자동 삭제"""
    try:
        now = time.time()
        # glob 패턴 매칭으로 파일 탐색
        for file_path in Path(".").glob("auth_token_*.json"):
            try:
                if file_path.is_file() and (now - file_path.stat().st_mtime > 86400):
                    file_path.unlink() # 파일 삭제
                    logger.info(f"🧹 만료된 토큰 삭제: {file_path.name}")
            except Exception:
                continue
    except Exception as e:
        logger.warning(f"토큰 청소 중 오류: {e}")


# ---------------------------------------------------------
# [SECTION 5] 데이터베이스 CRUD 기능 (안전장치 적용)
# ---------------------------------------------------------

def _safe_execute(query):
    """DB 쿼리 실행 래퍼 (공통 예외 처리)"""
    try:
        return query.execute()
    except Exception as e:
        logger.error(f"DB Query Error: {e}")
        return None

def get_user_portfolios(supabase: Client, user_id: str):
    """사용자의 포트폴리오 리스트 조회"""
    return _safe_execute(
        supabase.table("portfolios").select("*").eq("user_id", user_id).order("created_at", desc=True)
    )

def delete_portfolio(supabase: Client, portfolio_id: str):
    """특정 포트폴리오 삭제"""
    return _safe_execute(
        supabase.table("portfolios").delete().eq("id", portfolio_id)
    )

def get_portfolio_count(supabase: Client, user_id: str):
    """포트폴리오 총 개수 확인"""
    return _safe_execute(
        supabase.table("portfolios").select("id", count="exact").eq("user_id", user_id)
    )

def insert_portfolio(supabase: Client, data: dict):
    """새 포트폴리오 저장"""
    return _safe_execute(
        supabase.table("portfolios").insert(data)
    )

def update_portfolio(supabase: Client, portfolio_id: str, data: dict):
    """기존 포트폴리오 수정"""
    return _safe_execute(
        supabase.table("portfolios").update(data).eq("id", portfolio_id)
    )


# ---------------------------------------------------------
# [SECTION 6] 분석 및 로그 기능
# ---------------------------------------------------------

def log_visit(supabase: Client, source_tag: str):
    """방문 기록 로그 작성 (실패해도 무방함)"""
    try:
        supabase.table("visit_logs").insert({"referer": source_tag}).execute()
    except Exception:
        pass # 로그 실패는 사용자 경험을 방해하면 안 됨

def get_visit_count(supabase: Client):
    """누적 방문자 수 조회"""
    return _safe_execute(
        supabase.table("visit_counts").select("count").eq("id", 1)
    )

def update_visit_count(supabase: Client, new_count: int):
    """누적 방문자 수 업데이트"""
    return _safe_execute(
        supabase.table("visit_counts").update({"count": new_count}).eq("id", 1)
    )
