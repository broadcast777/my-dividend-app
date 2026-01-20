import logging
import sys
import os
from logging.handlers import TimedRotatingFileHandler
import streamlit as st # 원격 제어를 위해 추가

# 1. 로그 저장 폴더 설정 (기존 사장님 스타일 유지)
LOG_DIR = ".logs"
if not os.path.exists(LOG_DIR):
    os.makedirs(LOG_DIR)

def setup_logger():
    """
    실시간 계기판(Console)과 블랙박스(File)를 동시에 가동하는 로깅 시스템
    + [NEW] 원격 감도 조절 기능 추가
    """
    # 로거 이름은 앱 명칭에 맞춰 'dividend_pange'로 유지합니다.
    logger = logging.getLogger("dividend_pange")
    
    # [중복 방지] 이미 핸들러가 장착되어 있다면 중복 설치하지 않습니다.
    if logger.handlers:
        return logger

    # 2. [NEW] 센서 민감도 원격 제어 (환경변수 연동)
    # secrets.toml 파일에 [LOG_LEVEL="DEBUG"] 라고 적으면 상세 모드로 변신합니다.
    # 기본값은 'INFO' (정상 작동 기록)입니다.
    try:
        log_level_str = st.secrets.get("LOG_LEVEL", "INFO").upper()
        log_level = getattr(logging, log_level_str, logging.INFO)
    except:
        log_level = logging.INFO

    logger.setLevel(log_level)
    
    # 로그 출력 포맷 (가독성을 높인 파이프 라인 스타일)
    # [시간] | [등급] | 내용
    formatter = logging.Formatter('%(asctime)s | %(levelname)s | %(message)s', datefmt='%Y-%m-%d %H:%M:%S')

    # A. 블랙박스 기록 (파일 저장): 매일 자정 자동 교체 + 30일 보관
    log_file = os.path.join(LOG_DIR, "system.log")
    file_handler = TimedRotatingFileHandler(
        filename=log_file,
        when="midnight",
        interval=1,
        backupCount=30,
        encoding='utf-8'
    )
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    # B. ✅ 실시간 계기판 (콘솔 출력): 사장님 모니터(터미널/클라우드 로그)에 즉시 송출
    # Streamlit Cloud 관리자 화면에서 이 로그를 실시간으로 볼 수 있습니다.
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    return logger

# 기계 기동 시 로거 즉시 활성화
logger = setup_logger()
