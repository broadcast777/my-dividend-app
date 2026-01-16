import streamlit as st

def calculate_real_monthly_schedule(df, weights, total_invest):
    """단순 1/12이 아니라 배당 주기(월/분기)를 반영한 정밀 계산 엔진"""
    monthly_payouts = [0.0] * 12
    
    for stock, w in weights.items():
        if w <= 0: continue
        
        # 종목 데이터 매칭
        row_match = df[df['pure_name'] == stock]
        if row_match.empty: continue
        row = row_match.iloc[0]
        
        # 연간 예상 배당금 (원 단위)
        annual_div = total_invest * (w / 100) * (row['연배당률'] / 100)
        
        # [데이터 삭정] 배당 주기에 따라 해당 월에만 금액 배분
        # CSV에 '배당주기' 열이 '1,4,7,10' 또는 '월' 등으로 적혀있다고 가정
        cycle = str(row.get('배당주기', '월')) 
        
        if '월' in cycle:
            # 월배당: 12개월 균등 배분
            for m in range(12): 
                monthly_payouts[m] += (annual_div / 12)
        elif '1' in cycle and '4' in cycle:
            # 1/4/7/10 분기배당
            for m in [0, 3, 6, 9]: monthly_payouts[m] += (annual_div / 4)
        elif '2' in cycle and '5' in cycle:
            # 2/5/8/11 분기배당
            for m in [1, 4, 7, 10]: monthly_payouts[m] += (annual_div / 4)
        elif '3' in cycle and '6' in cycle:
            # 3/6/9/12 분기배당
            for m in [2, 5, 8, 11]: monthly_payouts[m] += (annual_div / 4)
        else:
            # 그 외: 데이터가 불분명하면 일단 월배당으로 처리 (안전장치)
            for m in range(12): monthly_payouts[m] += (annual_div / 12)
            
    return monthly_payouts

def render_toss_style_heatmap(df, weights, total_invest):
    """메인 화면용 토스 스타일 12개월 배당 히트맵"""
    
    # 1. 정밀 데이터 계산
    monthly_data = calculate_real_monthly_schedule(df, weights, total_invest)
    max_amt = max(monthly_data) if max(monthly_data) > 0 else 1
    months_labels = ["1월", "2월", "3월", "4월", "5월", "6월", "7월", "8월", "9월", "10월", "11월", "12월"]

    st.write("")
    
    # 2. 히트맵 그리드 생성 (4열 3행 구조)
    cols = st.columns(4)
    for i in range(12):
        amt = monthly_data[i]
        # 색상 농도 계산 (토스 블루: rgba(0, 104, 201, alpha))
        # 금액이 클수록 불투명도(alpha)가 높아짐
        alpha = 0.05 + (amt / max_amt) * 0.90 if amt > 0 else 0.02
        bg_color = f"rgba(0, 104, 201, {alpha})"
        # 글자색 결정 (배경이 진하면 흰색, 연하면 검은색)
        text_color = "#FFFFFF" if alpha > 0.4 else "#333333"
        
        with cols[i % 4]:
            st.markdown(f"""
                <div style="
                    background-color: {bg_color};
                    color: {text_color};
                    padding: 20px 10px;
                    border-radius: 15px;
                    text-align: center;
                    margin-bottom: 15px;
                    border: 1px solid #eef0f2;
                    height: 100px;
                    display: flex;
                    flex-direction: column;
                    justify-content: center;
                    box-shadow: 0 2px 8px rgba(0,0,0,0.05);
                ">
                    <p style="margin: 0; font-size: 0.8rem; opacity: 0.8;">{months_labels[i]}</p>
                    <p style="margin: 5px 0 0 0; font-weight: 800; font-size: 1.2rem;">
                        {amt/10000:,.1f}<span style="font-size:0.7em;">만</span>
                    </p>
                </div>
            """, unsafe_allow_html=True)

    # 3. 하단 총평
    total_annual = sum(monthly_data)
    st.success(f"📊 **연간 예상 총 배당금:** {total_annual/10000:,.0f}만원 (월 평균 {total_annual/12/10000:,.1f}만원)")

def display_sidebar_roadmap(df, weights, total_invest):
    """기존 사이드바용 (심플 버전 유지)"""
    # 사이드바는 공간이 좁으므로 기존 리스트 형태를 유지하되 타이틀만 예쁘게!
    st.sidebar.markdown("---")
    st.sidebar.subheader("🗓️ 배당 캘린더 요약")
    # ... (기존 코드와 유사하게 유지 가능)
