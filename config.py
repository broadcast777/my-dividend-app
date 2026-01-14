# config.py
import os

# 페이지 설정
PAGE_CONFIG = {
    "page_title": "배당팽이 대시보드",
    "layout": "wide",
    "initial_sidebar_state": "expanded"
}

# 관리자
MAINTENANCE_MODE = False
ADMIN_PASSWORD_HASH = "c41b0bb392db368a44ce374151794850417b56c9786e3c482f825327c7153182"

# 배당률 필터
MIN_DIVIDEND_YIELD = 2.0
MAX_DIVIDEND_YIELD = 25.0

# 포트폴리오
DEFAULT_INVESTMENT = 30000000

# 메시지
MESSAGES = {
    "login_required": "🔒 로그인이 필요합니다.",
    "login_success": "✅ 로그인되었습니다!",
    "admin_access": "🔐 관리자 모드 ON 🚀",
    "invalid_password": "❌ 비밀번호 불일치",
    "maintenance": "🚧 시스템 정기 점검 중"
}
