# constants.py

# 💰 세금 관련
TAX_RATE_GENERAL = 0.154       # 일반 과세 (15.4%)
TAX_RATE_ISA_OVER = 0.099      # ISA 초과분 분리과세 (9.9%)
AFTER_TAX_RATIO = 1 - TAX_RATE_GENERAL  # 세후 실수령 비율 (0.846)

# 🏦 투자금 설정
DEFAULT_INVEST_AMOUNT = 30000000  # 기본 총 투자금 (3천만원)
DEFAULT_MONTHLY_EXPENSE = 200     # 기본 월 지출 (200만원)

# 📅 시뮬레이션 설정
SIMULATION_YEARS = [3, 5, 10, 15, 20, 30]
INFLATION_RATE = 0.025            # 물가상승률 (2.5%)
ISA_YEARLY_CAP = 20000000         # ISA 연간 납입 한도
ISA_TOTAL_CAP = 100000000         # ISA 총 납입 한도
