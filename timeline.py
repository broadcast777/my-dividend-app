import streamlit as st

def calculate_monthly_cashflow(df, weights, total_invest):
    """실시간으로 12개월 현금흐름을 계산하는 엔진"""
    monthly_sums = [0.0] * 12
    for stock, w in weights.items():
        if w <= 0: continue
        row_match = df[df['pure_name'] == stock]
        if row_match.empty: continue
        
        row = row_match.iloc[0]
        rate = row['연배당률']
        amt = total_invest * (w / 100)
        annual_div = amt * (rate / 100)
        
        # 현재 데이터 기준 12개월 균등 배분 (추후 데이터 확장 시 수정 가능)
        for m in range(12):
            monthly_sums[m] += (annual_div / 12)
    return monthly_sums

def display_sidebar_roadmap(df, weights, total_invest):
    """사이드바에 12개월 배당 로드맵을 렌더링 (로그인 무관)"""
    st.sidebar.markdown("---")
    st.sidebar.subheader("🗓️ 실시간 배당 로드맵")
    
    if not weights or sum(weights.values()) == 0:
        st.sidebar.caption("종목을 담으면 로드맵이 가동됩니다.")
        return

    # 1. 데이터 계산
    monthly_data = calculate_monthly_cashflow(df, weights, total_invest)
    months_labels = ["1월", "2월", "3월", "4월", "5월", "6월", "7월", "8월", "9월", "10월", "11월", "12월"]
    
    # 2. 사이드바 전용 2열 배치
    for i in range(0, 12, 2):
        cols = st.sidebar.columns(2)
        for j in range(2):
            idx = i + j
            with cols[j]:
                amount = monthly_data[idx]
                st.markdown(f"""
                <div style="background-color: #f8f9fa; padding: 10px 5px; border-radius: 8px; 
                            border-left: 4px solid #0068c9; margin-bottom: 8px; text-align: center;
                            box-shadow: 0 1px 2px rgba(0,0,0,0.05);">
                    <p style="margin: 0; font-size: 0.75rem; color: #666;">{months_labels[idx]}</p>
                    <p style="margin: 2px 0 0 0; font-weight: bold; font-size: 1.0rem; color: #111;">
                        {amount/10000:,.1f}<span style="font-size:0.7em;">만</span>
                    </p>
                </div>
                """, unsafe_allow_html=True)

    # 3. 하단 요약 (세전/세후 체감 지표)
    total_annual = sum(monthly_data)
    total_after_tax = total_annual * 0.846
    
    st.sidebar.markdown(f"""
    <div style="background-color: #0068c9; color: white; padding: 15px; border-radius: 12px; 
                text-align: center; margin-top: 10px; box-shadow: 0 4px 6px rgba(0,0,0,0.1);">
        <p style="margin: 0; font-size: 0.85rem; opacity: 0.9;">연간 총 배당액</p>
        <p style="margin: 2px 0; font-weight: bold; font-size: 1.3rem;">{total_annual/10000:,.0f}만원</p>
        <p style="margin: 5px 0 0 0; font-size: 0.75rem; opacity: 0.85;">세후 약 {total_after_tax/10000:,.1f}만원</p>
    </div>
    """, unsafe_allow_html=True)
