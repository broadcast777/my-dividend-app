import logging
import os
from logging.handlers import TimedRotatingFileHandler

# 1. 로그를 저장할 폴더가 없으면 알아서 만듭니다.
LOG_DIR = ".logs"
if not os.path.exists(LOG_DIR):
    os.makedirs(LOG_DIR)

def setup_logger():
    """
    앱의 모든 움직임을 기록하는 블랙박스 설정
    (기능: 매일 자정에 날짜별로 파일 자동 분리 + 30일 지난 로그 자동 삭제)
    """
    # 'dividend_pange'라는 이름의 로거를 가져옵니다.
    logger = logging.getLogger("dividend_pange")
    
    # [중복 방지] 이미 설정된 로거가 있으면 또 만들지 않고 기존 것을 반환합니다.
    # (이 코드가 없으면 로그가 2번, 3번 중복해서 찍힐 수 있습니다)
    if logger.handlers:
        return logger

    # 로그 레벨 설정 (INFO 이상만 기록)
    logger.setLevel(logging.INFO)

    # 로그 파일의 기본 경로 설정
    log_file = os.path.join(LOG_DIR, "system.log")
    
    # [핵심 업그레이드] 날짜별로 파일 돌리기 (Rotating)
    # - when="midnight": 매일 밤 자정(00:00)에 파일을 바꿉니다.
    # - interval=1: 1일마다 바꿉니다.
    # - backupCount=30: 30일이 지난 오래된 로그 파일은 자동으로 지웁니다.
    file_handler = TimedRotatingFileHandler(
        filename=log_file, 
        when="midnight", 
        interval=1, 
        backupCount=30,
        encoding='utf-8'
    )
    
    # 로그에 찍힐 모양(포맷) 설정: [시간] [등급] 내용
    formatter = logging.Formatter('%(asctime)s [%(levelname)s] %(message)s')
    file_handler.setFormatter(formatter)
    
    # 로거에 핸들러 장착
    logger.addHandler(file_handler)
    
    return logger

# 이 파일이 import 될 때 바로 로거를 생성해서 준비해둡니다.
logger = setup_logger()
