import streamlit as st
import html  # [추가] 보안을 위한 HTML 이스케이프 라이브러리
import re

# ---------------------------------------------------------
# [SECTION] UI 렌더링 모듈 (보안 강화 버전)
# ---------------------------------------------------------

def sanitize_url(url):
    """
    [보안] 악성 스크립트가 포함된 URL(예: javascript:)을 차단하고 
    안전한 http/https 링크만 허용합니다.
    """
    clean_url = str(url).strip()
    if clean_url.lower().startswith(('http://', 'https://')):
        return clean_url
    return "#"  # 유효하지 않은 링크는 무력화

def render_custom_table(data_frame):
    """
    데이터프레임을 보안이 강화된 HTML/CSS 테이블로 변환하여 출력합니다.
    - XSS 방어: 모든 유저 입력 데이터에 html.escape() 적용
    - 애드센스 규격: 안전한 마크업 구조 유지
    """
    
    html_rows = []
    
    for _, row in data_frame.iterrows():
        # 1. [데이터 추출 및 보안 처리] 모든 텍스트는 html.escape로 감쌉니다.
        # 이렇게 하면 데이터에 <script> 같은 코드가 있어도 단순 문자로 처리됩니다.
        raw_code = str(row.get('코드', ''))
        safe_code = html.escape(raw_code)
        
        raw_name = str(row.get('종목명', ''))
        safe_name = html.escape(raw_name)
        
        safe_price = html.escape(str(row.get('현재가', '0')))
        safe_exch = html.escape(str(row.get('환구분', '-')))
        safe_ex_date = html.escape(str(row.get('배당락일', '-')))
        
        # 2. https://blog.naver.com/softwidesec/222355937953
        blog_link = str(row.get('블로그링크', '')).strip()
        if not blog_link or blog_link == '#':
            blog_link = "https://blog.naver.com/dividenpange"
        safe_blog_url = sanitize_url(blog_link)
        
        finance_link = str(row.get('금융링크', '#'))
        safe_finance_url = sanitize_url(finance_link)
        
        # 3. [HTML 요소 조립]
        # 종목코드 링크
        b_link = f"<a href='{safe_blog_url}' target='_blank' rel='noopener noreferrer' style='color:#0068c9; text-decoration:none; font-weight:bold;'>{safe_code}</a>"
        
        # 종목명 (고정 열)
        stock_name_html = f"<span style='color:#333; font-weight:500;'>{safe_name}</span>"
        
        # 배당률 강조 및 신규주 추정치 표시
        dividend_yield = row.get('연배당률', 0)
        is_new = row.get('신규상장개월수', 0)
        suffix = " (추정)" if (0 < is_new < 12) else ""
        
        yield_style = "color:#ff4b4b; font-weight:bold;" if dividend_yield >= 10 else "color:#333;"
        yield_display = f"<span style='{yield_style}'>{dividend_yield:.2f}%{suffix}</span>"
        
        # 금융정보 링크
        f_link = f"<a href='{safe_finance_url}' target='_blank' rel='noopener noreferrer' style='color:#0068c9; text-decoration:none;'>🔗정보</a>"
        
        # [최종 행 생성]
        html_rows.append(f"""
            <tr>
                <td>{b_link}</td>
                <td class='name-cell'>{stock_name_html}</td>
                <td>{safe_price}</td>
                <td>{yield_display}</td>
                <td>{safe_exch}</td>
                <td>{safe_ex_date}</td>
                <td>{f_link}</td>
            </tr>
        """)

    # -----------------------------------------------------
    # 2. CSS 스타일 정의 및 테이블 렌더링
    # -----------------------------------------------------
    st.markdown(f"""
    <style>
        .table-container {{
            overflow-x: auto; 
            white-space: nowrap;
            margin-bottom: 20px;
            border: 1px solid #eee;
            border-radius: 8px;
            box-shadow: 0 2px 4px rgba(0,0,0,0.05);
        }}
        
        table {{ width: 100%; border-collapse: collapse; font-size: 14px; min-width: 600px; }}
        th {{ background: #f8f9fb; padding: 12px 8px; border-bottom: 2px solid #ddd; text-align: center; color: #555; }}
        td {{ padding: 10px 8px; border-bottom: 1px solid #eee; text-align: center; background: white; }}
        
        .name-cell {{ 
            text-align: left !important; 
            min-width: 140px; 
            position: sticky; 
            left: 0; 
            background: #fff; 
            z-index: 1; 
            border-right: 2px solid #f0f0f0; 
        }}
        
        /* 마우스 호버 효과 (사용자 경험 개선) */
        tr:hover td {{ background-color: #fcfcfc; }}
    </style>
    
    <div class="table-container">
        <table>
            <thead>
                <tr>
                    <th>코드</th>
                    <th style='text-align:left; padding-left:10px;'>종목명</th>
                    <th>현재가</th>
                    <th>연배당률</th>
                    <th>환구분</th>
                    <th>배당락일</th>
                    <th>정보</th>
                </tr>
            </thead>
            <tbody>
                {''.join(html_rows)}
            </tbody>
        </table>
    </div>
    """, unsafe_allow_html=True)
