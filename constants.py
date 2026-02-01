# constants.py

# 💰 세금 관련
TAX_RATE_GENERAL = 0.154        # 일반 과세 (15.4%)
TAX_RATE_ISA_OVER = 0.099       # ISA 초과분 분리과세 (9.9%)
AFTER_TAX_RATIO = 1 - TAX_RATE_GENERAL  # 세후 실수령 비율 (0.846)

# 🏦 투자금 설정
DEFAULT_INVEST_AMOUNT = 30000000  # 기본 총 투자금 (3천만원)
DEFAULT_MONTHLY_EXPENSE = 200     # 기본 월 지출 (200만원)

# 📅 시뮬레이션 설정
SIMULATION_YEARS = [3, 5, 10, 15, 20, 30]
INFLATION_RATE = 0.025            # 물가상승률 (2.5%)
ISA_YEARLY_CAP = 20000000         # ISA 연간 납입 한도 (현재 2천만원)
ISA_TOTAL_CAP = 100000000         # ISA 총 납입 한도 (현재 1억원)

# ---------------------------------------------------------
# 🧹 데이터 정제 및 필터링 키워드 (리팩토링 추가)
# ---------------------------------------------------------

# 1. 제외할 키워드 (ETF 브랜드명, 파생상품 등)
EXCLUDE_KEYWORDS = [
    'KODEX', 'TIGER', 'RISE', 'ACE', 'SOL', 'KOSEF', 'ARIRANG', 
    '스왑', '설정액', 'PLUS', 'USD', 'KRW', '선물'
]

# 2. 종목명 매핑 (키워드 -> 표준 이름)
STOCK_NAME_MAPPING = {
    '엔비디아': ['NVIDIA', 'NVDA', '엔비디아'],
    '애플': ['APPLE', 'AAPL', '애플'],
    '마이크로소프트': ['MICROSOFT', 'MSFT', '마이크로소프트'],
    '구글(알파벳)': ['ALPHABET', 'GOOG', '알파벳'],
    '메타': ['META', '메타'],
    '테슬라': ['TESLA', 'TSLA', '테슬라'],
    '아마존': ['AMAZON', 'AMZN', '아마존'],
    '브로드컴': ['BROADCOM', 'AVGO', '브로드컴']
}

# 3. 섹터 분류 키워드
SECTOR_KEYWORDS = {
    'HighYield': ['하이일드', 'USHY', 'JNK', 'HYG'],
    'Cash': ['BIL', 'SHV', 'SGOV', '초단기', 'CD금리', 'KOFR', '머니마켓', '현금', '예금'],
    'Bond_Long': ['국채', '채권', 'TLT', '30년'],
    'BigTech': ['엔비디아', '애플', '마이크로소프트', '구글(알파벳)', '메타', '테슬라', '아마존', '브로드컴']
}

# 4. ETF 이름 매핑 (DB 검색용 별명)
ETF_ALIAS_MAP = {
    "KODEX 미국30년국채타겟커버드콜(합성)": "KODEX 미국30년국채액티브(H)",
    "ACE 미국30년국채액티브(H)": "ACE 미국30년국채액티브",
    "SOL 미국30년국채액티브(H)": "SOL 미국30년국채커버드콜(합성)",
    "TIGER 미국초단기(3개월이하)국채": "TIGER 미국초단기채권액티브",
}
