import streamlit as st
import pandas as pd

# -----------------------------------------------------------
# [1] 월별 배당 현금흐름 계산 엔진
# -----------------------------------------------------------
def calculate_monthly_cashflow(df, weights, total_invest):
    """
    df: 전체 데이터프레임
    weights: {종목명: 비중(%)} 딕셔너리
    total_invest: 총 투자금액 (원)
    """
    monthly_sums = [0.0] * 12
    
    for stock, w in weights.items():
        if w <= 0: continue
        
        row_match = df[df['pure_name'] == stock]
        if row_match.empty: continue
        
        row = row_match.iloc[0]
        rate = row['연배당률']
        
        # 투자금 및 연간 총 배당금액 계산
        amt = total_invest * (w / 100)
        annual_div = amt * (rate / 100)
        
        # 배당 주기 판단 (데이터의 '배당락일' 컬럼 활용)
        # 월배당 종목은 12개월 전체에 배분
        # (실제 데이터 형식에 따라 파싱 로직은 수정될 수 있습니다)
        # 기본적으로 모든 종목을 '월배당'으로 가정하거나, 분기배당인 경우 4로 나눕니다.
        
        # [로직] 월배당 위주이므로 12개월로 균등 배분 (추후 정밀 파싱 가능)
        for m in range(12):
            monthly_sums[m] += (annual_div / 12)
            
    return monthly_sums

# -----------------------------------------------------------
# [2] 로드맵 UI 출력 함수
# -----------------------------------------------------------
def display_roadmap(df, weights, total_invest):
    st.write("")
    st.subheader("🗓️ 나의 월별 배당 로드맵")
    st.caption("※ 각 종목의 연배당률을 12개월로 균등 배분한 예상치입니다.")
    
    # 1. 데이터 계산
    monthly_data = calculate_monthly_cashflow(df, weights, total_invest)
    
    # 2. 6x2 그리드 레이아웃 생성
    months_labels = ["1월", "2월", "3월", "4월", "5월", "6월", "7월", "8월", "9월", "10월", "11월", "12월"]
    
    # 상단 6개월 / 하단 6개월
    for row_idx in range(2):
        cols = st.columns(6)
        for col_idx in range(6):
            month_idx = row_idx * 6 + col_idx
            with cols[col_idx]:
                amount = monthly_data[month_idx]
                
                # 시각적 카드 디자인
                st.markdown(f"""
                <div style="
                    background-color: #ffffff; 
                    padding: 12px 5px; 
                    border-radius: 10px; 
                    border: 1px solid #eee;
                    border-top: 4px solid #007bff; 
                    text-align: center; 
                    margin-bottom: 10px;
                    box-shadow: 0 2px 4px rgba(0,0,0,0.05);
                ">
                    <p style="margin: 0; font-size: 0.85em; color: #666; font-weight: 500;">{months_labels[month_idx]}</p>
                    <p style="margin: 5px 0 0 0; font-weight: bold; font-size: 1.1em; color: #1f1f1f;">
                        {amount/10000:,.0f}<span style="font-size: 0.7em; margin-left:2px;">만원</span>
                    </p>
                </div>
                """, unsafe_allow_html=True)

    # 3. 요약 정보
    total_annual = sum(monthly_data)
    st.info(f"💡 위 포트폴리오 유지 시, 예상 연간 총 배당금은 **{total_annual/10000:,.0f}만원**입니다.")
