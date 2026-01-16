import streamlit as st

# [1] 월별 배당 현금흐름 계산 엔진
def calculate_monthly_cashflow(df, weights, total_invest):
    monthly_sums = [0.0] * 12
    for stock, w in weights.items():
        if w <= 0: continue
        row_match = df[df['pure_name'] == stock]
        if row_match.empty: continue
        
        row = row_match.iloc[0]
        rate = row['연배당률']
        amt = total_invest * (w / 100)
        annual_div = amt * (rate / 100)
        
        # 월배당 기준 균등 배분 (데이터에 따라 월별 파싱 가능)
        for m in range(12):
            monthly_sums[m] += (annual_div / 12)
    return monthly_sums

# [2] 사이드바 전용 로드맵 출력 함수
def display_sidebar_roadmap(df, weights, total_invest):
    st.sidebar.markdown("---")
    st.sidebar.subheader("🗓️ 월별 배당 로드맵")
    
    if not weights or sum(weights.values()) == 0:
        st.sidebar.caption("종목과 비중을 설정하면\n실시간 로드맵이 표시됩니다.")
        return

    # 데이터 계산
    monthly_data = calculate_monthly_cashflow(df, weights, total_invest)
    months_labels = ["1월", "2월", "3월", "4월", "5월", "6월", "7월", "8월", "9월", "10월", "11월", "12월"]
    
    # 사이드바용 컴팩트 2열 그리드
    for i in range(0, 12, 2):
        cols = st.sidebar.columns(2)
        for j in range(2):
            idx = i + j
            with cols[j]:
                amount = monthly_data[idx]
                st.markdown(f"""
                <div style="
                    background-color: #f0f2f6; 
                    padding: 8px 2px; 
                    border-radius: 8px; 
                    border-left: 4px solid #007bff; 
                    margin-bottom: 5px;
                    text-align: center;
                ">
                    <p style="margin: 0; font-size: 0.75rem; color: #555;">{months_labels[idx]}</p>
                    <p style="margin: 2px 0 0 0; font-weight: bold; font-size: 0.9rem; color: #111;">
                        {amount/10000:,.1f}<span style="font-size:0.7em;">만</span>
                    </p>
                </div>
                """, unsafe_allow_html=True)

    # 하단 요약
    total_annual = sum(monthly_data)
    st.sidebar.markdown(f"""
    <div style="background-color: #007bff; color: white; padding: 10px; border-radius: 8px; text-align: center; margin-top: 10px;">
        <p style="margin: 0; font-size: 0.8em;">연 예상 총 배당금</p>
        <p style="margin: 0; font-weight: bold; font-size: 1.2em;">{total_annual/10000:,.0f}만원</p>
    </div>
    """, unsafe_allow_html=True)
