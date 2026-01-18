import logging
import sys
import os
from logging.handlers import TimedRotatingFileHandler

# 1. 로그 저장 폴더 설정 (기존 사장님 스타일 유지)
LOG_DIR = ".logs"
if not os.path.exists(LOG_DIR):
    os.makedirs(LOG_DIR)

def setup_logger():
    """
    실시간 계기판(Console)과 블랙박스(File)를 동시에 가동하는 로깅 시스템
    """
    # 로거 이름은 앱 명칭에 맞춰 'dividend_pange'로 유지합니다.
    logger = logging.getLogger("dividend_pange")
    
    # [중복 방지] 이미 핸들러가 장착되어 있다면 중복 설치하지 않습니다.
    if logger.handlers:
        return logger

    # 센서 민감도 설정 (INFO 레벨 이상 기록)
    logger.setLevel(logging.INFO)
    
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

    # B. ✅ 실시간 계기판 추가 (콘솔 출력): 사장님 모니터(터미널)에 즉시 송출
    # 이 부분이 있어야 파일을 열지 않고도 실시간 정비가 가능합니다.
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    return logger

# 기계 기동 시 로거 즉시 활성화
logger = setup_logger()
