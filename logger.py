import logging
import os
from datetime import datetime

# 로그를 저장할 폴더 만들기
LOG_DIR = ".logs"
if not os.path.exists(LOG_DIR):
    os.makedirs(LOG_DIR)

def setup_logger():
    """앱의 모든 움직임을 기록하는 블랙박스 설정"""
    logger = logging.getLogger("dividend_pange")
    logger.setLevel(logging.INFO)

    # 로그 파일 이름 설정 (날짜별로 저장)
    log_file = os.path.join(LOG_DIR, f"{datetime.now().strftime('%Y%m%d')}.log")
    
    # 기록 양식 설정 (시간 [중요도] 내용)
    formatter = logging.Formatter('%(asctime)s [%(levelname)s] %(message)s')

    # 파일에 기록하는 도구
    file_handler = logging.FileHandler(log_file, encoding='utf-8')
    file_handler.setFormatter(formatter)
    
    logger.addHandler(file_handler)
    return logger

# 다른 파일에서 바로 쓸 수 있게 로거 생성
logger = setup_logger()
