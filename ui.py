import streamlit as st

def render_custom_table(data_frame):
    """데이터프레임을 HTML 테이블로 예쁘게 렌더링 (모바일 스크롤 적용)"""
    html_rows = []
    for _, row in data_frame.iterrows():
        blog_link = str(row.get('블로그링크', '')).strip()
        if not blog_link or blog_link == '#':
            blog_link = "https://blog.naver.com/dividenpange"
        
        b_link = f"<a href='{blog_link}' target='_blank' style='color:#0068c9; text-decoration:none; font-weight:bold;'>{row['코드']}</a>"
        stock_name = f"<span style='color:#333; font-weight:500;'>{row['종목명']}</span>"
        f_link = f"<a href='{row['금융링크']}' target='_blank' style='color:#0068c9; text-decoration:none;'>🔗정보</a>"
        
        is_new = row.get('신규상장개월수', 0)
        suffix = " (추정)" if (0 < is_new < 12) else ""
        yield_display = f"<span style='color:{'#ff4b4b' if row['연배당률']>=10 else '#333'}; font-weight:{'bold' if row['연배당률']>=10 else 'normal'};'>{row['연배당률']:.2f}%{suffix}</span>"
        
        html_rows.append(f"<tr><td>{b_link}</td><td class='name-cell'>{stock_name}</td><td>{row['현재가']}</td><td>{yield_display}</td><td>{row['환구분']}</td><td>{row['배당락일']}</td><td>{f_link}</td></tr>")

    st.markdown(f"""
    <style>
        .table-container {{
            overflow-x: auto; 
            white-space: nowrap;
            margin-bottom: 20px;
            border: 1px solid #eee;
            border-radius: 8px;
        }}
        table {{ width: 100%; border-collapse: collapse; font-size: 14px; min-width: 600px; }}
        th {{ background: #f0f2f6; padding: 12px 8px; border-bottom: 2px solid #ddd; text-align: center; }}
        td {{ padding: 10px 8px; border-bottom: 1px solid #eee; text-align: center; }}
        .name-cell {{ text-align: left !important; min-width: 120px; position: sticky; left: 0; background: white; z-index: 1; border-right: 1px solid #eee; }}
    </style>
    
    <div class="table-container">
        <table>
            <thead><tr><th>코드</th><th style='text-align:left; padding-left:10px;'>종목명</th><th>현재가</th><th>연배당률</th><th>환구분</th><th>배당락일</th><th>정보</th></tr></thead>
            <tbody>{''.join(html_rows)}</tbody>
        </table>
    </div>
    """, unsafe_allow_html=True)

# [ui.py] 테스트용 코드 (나중에 지우세요)

# 1. 토스 스타일 팝업창 정의
@st.dialog("🕵️ 투자 성향 진단")
def open_toss_modal():
    st.write("Q1. 투자할 때 가장 중요하게 생각하는 것은?")
    
    # 2. 질문과 선택지
    answer = st.radio("하나만 골라주세요", ["🔥 수익률 (인생은 한방)", "🛡️ 안정성 (잃으면 잠 못잠)", "⚖️ 밸런스 (반반 무 많이)"], index=None)
    
    if answer:
        st.write(f"아하! **{answer}**을(를) 선호하시는군요.")
        st.write("")
        
        # 3. 결과 적용 버튼
        if st.button("결과 확인하고 적용하기", type="primary"):
            st.session_state.toss_result = answer # 결과 저장
            st.rerun() # 팝업 닫기

# 4. 메인 화면의 버튼
if st.button("코치님, 저 뭐 살까요? (클릭)"):
    open_toss_modal()
