import streamlit as st
import html
import re

# ---------------------------------------------------------
# [SECTION] UI 렌더링 모듈 (인테리어 연결 및 보안 강화)
# ---------------------------------------------------------

def load_css():
    """[신규] 외부 배전함(style.css)을 시스템에 연결합니다."""
    try:
        with open("style.css", "r", encoding="utf-8") as f:
            st.markdown(f"<style>{f.read()}</style>", unsafe_allow_html=True)
    except FileNotFoundError:
        pass # 파일이 없으면 기본 디자인으로 출력됨

def sanitize_url(url):
    """[보안] 안전한 링크만 허용하는 검문소"""
    clean_url = str(url).strip()
    if clean_url.lower().startswith(('http://', 'https://')):
        return clean_url
    return "#"

def render_custom_table(data_frame):
    """데이터프레임을 보안 HTML 테이블로 변환 (디자인은 style.css 참고)"""
    html_rows = []
    
    for _, row in data_frame.iterrows():
        # 1. 데이터 보안 처리
        safe_code = html.escape(str(row.get('코드', '')))
        safe_name = html.escape(str(row.get('종목명', '')))
        safe_price = html.escape(str(row.get('현재가', '0')))
        safe_exch = html.escape(str(row.get('환구분', '-')))
        safe_ex_date = html.escape(str(row.get('배당락일', '-')))
        
        # 2. 링크 보안 검사
        blog_link = str(row.get('블로그링크', '')).strip()
        if not blog_link or blog_link == '#':
            blog_link = "https://blog.naver.com/dividenpange"
        safe_blog_url = sanitize_url(blog_link)
        
        finance_link = str(row.get('금융링크', '#'))
        safe_finance_url = sanitize_url(finance_link)
        
        # 3. HTML 조각 조립
        b_link = f"<a href='{safe_blog_url}' target='_blank' rel='noopener noreferrer' style='color:#0068c9; text-decoration:none; font-weight:bold;'>{safe_code}</a>"
        stock_name_html = f"<span style='color:#333; font-weight:500;'>{safe_name}</span>"
        
        dividend_yield = row.get('연배당률', 0)
        is_new = row.get('신규상장개월수', 0)
        suffix = " (추정)" if (0 < is_new < 12) else ""
        
        yield_style = "color:#ff4b4b; font-weight:bold;" if dividend_yield >= 10 else "color:#333;"
        yield_display = f"<span style='{yield_style}'>{dividend_yield:.2f}%{suffix}</span>"
        
        f_link = f"<a href='{safe_finance_url}' target='_blank' rel='noopener noreferrer' style='color:#0068c9; text-decoration:none;'>🔗정보</a>"
        
        html_rows.append(f"<tr><td>{b_link}</td><td class='name-cell'>{stock_name_html}</td><td>{safe_price}</td><td>{yield_display}</td><td>{safe_exch}</td><td>{safe_ex_date}</td><td>{f_link}</td></tr>")

    # 4. 테이블 전체 렌더링 (디자인 코드는 style.css에서 자동으로 가져옴)
    st.markdown(f"""
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
