"""
프로젝트: 배당 팽이 (Dividend Top)
파일명: simulation.py
설명: 미래 자산 예측 및 목표 달성 시뮬레이션 로직/UI 전담
업데이트: 2026.02.01
"""

import streamlit as st
import pandas as pd
import altair as alt
import random
import constants as C

# =======================================================
# [PART 1] 목표 배당 달성 역산기 (Target Calculator)
# =======================================================

def calculate_goal_simulation(target_monthly_goal, avg_y, total_invest, use_start_money):
    """
    [로직] 목표 월 배당금을 받으려면 얼마가 필요한지 계산
    Returns: 결과 Dictionary
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
        
    # 4. 달성 기간 시뮬레이션 (단순 복리 가정)
    current_bal = start_balance
    months_passed = 0
    max_months = 720 # 60년 제한 (무한루프 방지)
    
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


# =======================================================
# [PART 2] 10년 자산 시뮬레이션 (10-Year Asset Projection)
# =======================================================

def run_asset_simulation(start_money, monthly_add, years, avg_y, is_isa, apply_inflation):
    """
    [로직] ISA/일반 계좌별 미래 자산 성장 시뮬레이션
    Returns: 차트 데이터 및 최종 금액 정보
    """
    reinvest_ratio = 100 # 기본 100% 재투자 가정
    months_sim = years * 12
    monthly_yld = avg_y / 100 / 12
    
    # ISA 공제 한도 설정 (일반형 200만원 가정)
    isa_exempt = 200 if is_isa else 0
        
    # 초기 자산 배분 (ISA 한도 고려)
    isa_bal = start_money if (is_isa and start_money <= C.ISA_TOTAL_CAP) else 0
    general_bal = max(0, start_money - C.ISA_TOTAL_CAP) if is_isa else start_money
    
    if not is_isa: # ISA 미사용 시 전액 일반 계좌
        isa_bal = 0
        general_bal = start_money

    isa_principal = isa_bal
    general_principal = general_bal
    
    total_tax_paid_general = 0
    sim_data = [{"년차": 0, "자산총액": (isa_bal + general_bal)/10000, "총원금": (isa_principal + general_principal)/10000, "실제월배당": 0}]
    
    year_tracker = 0
    yearly_contribution = 0

    # 월별 시뮬레이션 루프
    for m in range(1, months_sim + 1):
        if m // 12 > year_tracker:
            yearly_contribution = 0
            year_tracker = m // 12
        
        # 1. 납입 (Contribution)
        if is_isa:
            remaining_isa_yearly = max(0, C.ISA_YEARLY_CAP - yearly_contribution)
            remaining_isa_total = max(0, C.ISA_TOTAL_CAP - isa_principal)
            
            actual_isa_add = min(monthly_add, remaining_isa_yearly, remaining_isa_total)
            actual_general_add = monthly_add - actual_isa_add
            
            isa_bal += actual_isa_add
            isa_principal += actual_isa_add
            yearly_contribution += actual_isa_add
            general_bal += actual_general_add
            general_principal += actual_general_add
        else:
            general_bal += monthly_add
            general_principal += monthly_add

        # 2. 배당 및 재투자 (Dividend & Reinvest)
        div_isa = isa_bal * monthly_yld
        isa_bal += div_isa # ISA는 비과세/과세이연 (세금 없이 재투자)
        
        div_gen = general_bal * monthly_yld
        this_tax = div_gen * C.TAX_RATE_GENERAL # 일반 계좌는 15.4% 떼고 재투자
        total_tax_paid_general += this_tax
        reinvest_gen = (div_gen - this_tax) * (reinvest_ratio / 100)
        general_bal += reinvest_gen
        
        sim_data.append({
            "년차": m / 12, 
            "자산총액": (isa_bal + general_bal) / 10000, 
            "총원금": (isa_principal + general_principal) / 10000, 
            "실제월배당": div_isa + div_gen
        })
        
    # 최종 결과 정리
    final_asset = isa_bal + general_bal
    final_principal = isa_principal + general_principal
    profit_isa = isa_bal - isa_principal
    monthly_div_final = sim_data[-1]['실제월배당']
    
    # 세금 정산 (만기 해지 시점 가정)
    if is_isa:
        taxable_isa = max(0, profit_isa - (isa_exempt * 10000))
        tax_isa = taxable_isa * C.TAX_RATE_ISA_OVER # 9.9% 분리과세
        real_money = final_asset - tax_isa
        tax_msg = f"예상 세금 {tax_isa/10000:,.0f}만원 (9.9% 분리과세)"
        monthly_pocket = monthly_div_final 
    else:
        real_money = final_asset
        tax_msg = f"기납부 세금 {total_tax_paid_general/10000:,.0f}만원 (15.4% 원천징수)"
        monthly_pocket = monthly_div_final * C.AFTER_TAX_RATIO

    # 물가상승률 반영 (현재 가치 환산)
    if apply_inflation:
        discount_rate = (1.0 + C.INFLATION_RATE) ** years
        real_money = real_money / discount_rate
        monthly_pocket = monthly_pocket / discount_rate

    return {
        "df": pd.DataFrame(sim_data),
        "real_money": real_money,
        "final_principal": final_principal,
        "monthly_pocket": monthly_pocket,
        "tax_msg": tax_msg,
        "general_bal": general_bal,
        "is_isa": is_isa
    }


# =======================================================
# [PART 3] 화면 렌더링 (UI Rendering)
# =======================================================

def render_10y_sim_page(total_invest, avg_y, saved_monthly):
    """
    [UI] 10년 자산 시뮬레이션 탭 전체 화면 표시
    """
    start_money = total_invest
    is_over_100m = start_money > 100000000
    
    st.info(f"📊 상단에서 설정한 **초기 자산 {start_money/10000:,.0f}만원**으로 시뮬레이션을 시작합니다.")
    
    # 1. 사용자 입력 컨트롤 (Input)
    c1, c2 = st.columns([1.5, 1])
    with c1:
        if is_over_100m:
            is_isa_mode = st.toggle("🛡️ ISA 계좌 불가 (한도 1억 초과)", value=False, disabled=True)
            st.caption("🚫 초기 투자금이 1억원을 초과하여 일반 계좌로만 진행됩니다.")
        else:
            is_isa_mode = st.toggle("🛡️ ISA (절세) 계좌로 모으기", value=True)
            if is_isa_mode: st.caption("💡 **ISA 모드:** 비과세 + 과세이연 효과")
            else: st.caption("💡 **일반 모드:** 배당소득세(15.4%) 납부 후 재투자")
    with c2:
        years_sim = st.select_slider("⏳ 투자 기간", options=[3, 5, 10, 15, 20, 30], value=5, format_func=lambda x: f"{x}년")
        apply_inflation = st.toggle("📉 물가상승률(2.5%) 반영", value=False)
    
    st.markdown("---")
    
    monthly_input_val = st.number_input(
        "➕ 매월 추가 적립 (만원)", min_value=0, max_value=3000, value=saved_monthly, step=10, key="shared_monthly_input"
    )
    monthly_add = monthly_input_val * 10000
    
    # ISA 한도 초과 경고
    isa_limit_mo = C.ISA_YEARLY_CAP / 12
    if is_isa_mode and monthly_add > isa_limit_mo:
        st.warning(f"⚠️ **ISA 연간 한도 제한:** 월 납입금이 **약 {isa_limit_mo/10000:,.0f}만원**을 초과하면 초과분은 일반 계좌로 자동 계산됩니다.")

    # 2. 로직 실행 (Computation)
    result = run_asset_simulation(start_money, monthly_add, years_sim, avg_y, is_isa_mode, apply_inflation)
    
    # 3. 차트 시각화 (Visualization)
    base = alt.Chart(result['df']).encode(x=alt.X('년차:Q', title='경과 기간 (년)'))
    area = base.mark_area(opacity=0.3, color='#0068c9').encode(y=alt.Y('자산총액:Q', title='자산 (만원)'))
    line = base.mark_line(color='#ff9f43', strokeDash=[5,5]).encode(y='총원금:Q')
    st.altair_chart((area + line).properties(height=280), use_container_width=True)

    # 4. 결과 카드 표시 (Result Card)
    _render_result_card(result, years_sim, apply_inflation)
    
    # 5. 하단 주의사항 (Footer)
    annual_div = result['monthly_pocket'] * 12
    if annual_div > C.ISA_YEARLY_CAP: 
        st.warning(f"🚨 **주의:** {years_sim}년 뒤 연간 배당금이 2,000만원을 초과하여 금융소득종합과세 대상이 될 수 있습니다.")
    
    st.error("""**⚠️ 시뮬레이션 활용 시 유의사항**
            1. 본 결과는 주가·환율 변동을 제외하고, 현재 배당률로만 계산한 단순 결과입니다.
            2. 재투자가 매월 이루어진다는 가정하에 계산된 복리 결과입니다.""")

def _render_result_card(res, years, inflation):
    """[Helper] 결과 카드 HTML 생성"""
    real_money = res['real_money']
    monthly_pocket = res['monthly_pocket']
    
    # 물가상승률 문구 처리
    inf_msg_m = f"<br><span style='font-size:0.6em; color:#ff6b6b;'>(현재가치 환산됨)</span>" if inflation else ""
    inf_msg_mo = f"<span style='font-size:0.7em; color:#ff6b6b;'>(현재가치)</span>" if inflation else ""

    # 체감 물가 비유 (랜덤 아이템)
    analogy_items = [
        {"name": "스타벅스", "unit": "잔", "price": 4500, "emoji": "☕"},
        {"name": "뜨끈한 국밥", "unit": "그릇", "price": 10000, "emoji": "🍲"},
        {"name": "치킨", "unit": "마리", "price": 23000, "emoji": "🍗"},
        {"name": "호텔 숙박", "unit": "박", "price": 200000, "emoji": "🏨"},
    ]
    # 월 배당금으로 살 수 있는 아이템 찾기
    affordable = [item for item in analogy_items if monthly_pocket >= item['price']]
    selected = random.choice(affordable) if affordable else analogy_items[0]
    count = int(monthly_pocket // selected['price'])
    count_str = f"{count:,}" if count > 0 else f"{monthly_pocket / selected['price']:.1f}"

    # ISA 한도 초과 시 일반 계좌 혼용 안내 문구
    gen_msg = ""
    if res['is_isa'] and res['general_bal'] > 10000:
        gen_val = res['general_bal'] / 10000
        gen_msg = f"<div style='color: #6c757d; font-size: 0.85em; margin-top: 15px; border-top: 1px dashed #d0e8ff; padding-top: 10px;'>💡 최종 자산 중 <b>약 {gen_val:,.0f}만원</b>은 ISA 한도 초과로 인해<br>일반 계좌(15.4% 과세)로 운용된 결과입니다.</div>"

    html = f"""
    <div style="background-color: #e7f3ff; border: 1.5px solid #d0e8ff; border-radius: 16px; padding: 25px; text-align: center; box-shadow: 0 4px 10px rgba(0,104,201,0.05);">
        <p style="color: #666; font-size: 0.95em; margin: 0 0 8px 0;">{years}년 뒤 모이는 돈 (세후)</p>
        <h2 style="color: #0068c9; font-size: 2.2em; margin: 0; font-weight: 800; line-height: 1.2;">약 {real_money/10000:,.0f}만원{inf_msg_m}</h2>
        <p style="color: #777; font-size: 0.9em; margin: 8px 0 0 0;">(투자원금 {res['final_principal']/10000:,.0f}만원 / {res['tax_msg']})</p>
        <div style="height: 1px; background-color: #d0e8ff; margin: 25px auto; width: 85%;"></div>
        <p style="color: #0068c9; font-weight: bold; font-size: 1.1em; margin: 0 0 12px 0;">📅 월 예상 배당금: {monthly_pocket/10000:,.1f}만원 {inf_msg_mo}</p>
        <div style="background-color: rgba(255,255,255,0.5); padding: 15px; border-radius: 12px; display: inline-block; min-width: 80%;">
            <p style="color: #333; font-size: 1.1em; margin: 0; line-height: 1.6;">
                매달 <b>{selected['emoji']} {selected['name']} {count_str}{selected['unit']}</b><br>
                마음껏 즐기기 가능! 😋
            </p>{gen_msg}
        </div>
    </div>
    """
    st.markdown(html, unsafe_allow_html=True)

# ... (위에는 10년 시뮬레이션 관련 코드들이 있습니다) ...

# =======================================================
# 4. [UI] 목표 달성 역산기 화면 렌더링 (app.py에서 호출)
# =======================================================
def render_goal_sim_page(selected_stocks, avg_y, total_invest):
    """
    [UI] 목표 배당 달성(역산기) 탭 전체 화면 표시
    """
    import streamlit as st
    
    st.subheader("🎯 목표 배당금 역산기 (은퇴 시뮬레이터)")
    st.caption("내가 원하는 월급을 받기 위해 총 얼마가 필요한지 계산합니다.")

    with st.container(border=True):
        col_info1, col_info2 = st.columns(2)
        col_info1.metric("📊 평균 연배당률", f"{avg_y:.2f}%")
        col_info2.metric("📦 선택 종목 수", f"{len(selected_stocks)}개")
        st.caption(f"🔎 **적용 종목:** {', '.join(selected_stocks)}")

    st.write("")

    col_g1, col_g2 = st.columns(2)
    with col_g1:
        input_val = st.number_input(
            "목표 월 배당금 (만원, 세후)", 
            min_value=10, value=166, step=10, 
            key="target_monthly_goal_input"
        )
        target_monthly_goal = input_val * 10000
        st.caption(f"💡 '세후' 월 {input_val}만원 설정 시 연간 세전 약 {int(input_val * 12 / 0.846):,}만원 이내로 절세가 가능합니다.")
    
    with col_g2:
        st.write("") 
        st.write("") 
        use_start_money = st.checkbox(
            "현재 설정된 초기 자산을 포함하여 계산", 
            value=True, 
            help="체크 해제 시 0원에서 시작한다고 가정합니다.",
            key="use_start_money_chk"
        )
        st.caption(f"보유: {total_invest/10000:,.0f}만원")

    # [내부 호출] 위에 정의해둔 계산 로직을 사용합니다.
    sim_result = calculate_goal_simulation(
        target_monthly_goal, 
        avg_y, 
        total_invest, 
        use_start_money
    )

    st.markdown("---")
    
    # 결과 시각화
    progress = sim_result['progress_rate']
    st.write(f"📊 **목표 달성 진행률: {progress:.1f}%**")
    st.progress(progress / 100)

    if sim_result['is_impossible']:
        st.warning("⚠️ 현재 조건(추가 납입 없음)으로는 목표 달성에 60년 이상 걸립니다. 초기 자산을 늘리거나 목표를 조정해 보세요.")
    else:
        c_res1, c_res2 = st.columns(2)
        with c_res1:
            req_asset = sim_result['required_asset']
            st.metric("최종 필요 자산", f"{req_asset/100000000:,.2f} 억원")
            st.caption(f"월 {target_monthly_goal/10000:,.0f}만원을 받기 위해 필요한 돈")
        
        with c_res2:
            gap = sim_result['gap_money']
            start_bal = sim_result['actual_start_bal']
            
            if gap > 0:
                st.metric(
                    "앞으로 더 모아야 할 금액", 
                    f"{gap/100000000:,.2f} 억원", 
                    delta=f"✅ {start_bal/10000:,.0f}만원 보유 중", 
                    delta_color="normal"
                )
            else:
                st.success("🎉 이미 목표 달성! 은퇴하셔도 됩니다.")
        
    st.write("") 
    st.info("💡 이 계산은 **추가 납입 없이**, 배당금 재투자만으로 목표에 도달하는 기준입니다.")
    st.error("""
            **⚠️ 시뮬레이션 활용 시 유의사항**
            1. 본 결과는 주가·환율 변동을 제외하고, 현재 배당률로만 계산한 단순 결과입니다.
            2. 재투자가 매월 이루어진다는 가정하에 계산된 복리 결과입니다.
            """)
