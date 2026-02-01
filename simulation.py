import constants as C  # 상수 파일 연결

def calculate_goal_simulation(target_monthly_goal, avg_y, total_invest, use_start_money):
    """
    목표 배당 달성 시뮬레이션 로직 (역산기)
    """
    # 1. 초기 자산 설정
    start_balance = total_invest if use_start_money else 0
    
    # 2. 세금 및 수익률 설정
    tax_factor = C.AFTER_TAX_RATIO
    monthly_yld = avg_y / 100 / 12  
    
    # 3. 목표 자산 계산 (공식: 목표월세후 / (월이율 * 세후비율))
    if avg_y > 0:
        required_asset = target_monthly_goal / (monthly_yld * tax_factor)
    else:
        required_asset = 0
        
    # 4. 달성 기간 시뮬레이션 (복리)
    current_bal = start_balance
    months_passed = 0
    max_months = 720 # 60년 제한
    
    # 목표액이 0이거나 이미 달성했으면 0개월
    if required_asset > 0 and current_bal < required_asset:
        while months_passed < max_months:
            if current_bal >= required_asset: break
            # 월 배당금 재투자
            div_reinvest = current_bal * monthly_yld * tax_factor
            current_bal += div_reinvest
            months_passed += 1
            
    # 5. 결과 정리
    gap_money = max(0, required_asset - start_balance)
    progress_rate = (start_balance / required_asset * 100) if required_asset > 0 else 0
    
    return {
        "required_asset": required_asset,
        "gap_money": gap_money,
        "progress_rate": min(progress_rate, 100.0),
        "actual_start_bal": start_balance,
        "months_passed": months_passed,
        "is_impossible": months_passed >= max_months
    }
