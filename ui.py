import streamlit as st
import html
import re

# ---------------------------------------------------------
# [SECTION] UI 렌더링 모듈 (공백 제거 패치 완료)
# ---------------------------------------------------------

def load_css():
    """외부 스타일 파일 로드 및 비상용 기본 스타일 적용"""
    # 1. 파일에서 스타일 읽기 시도
    css_content = ""
    try:
        with open("style.css", "r", encoding="utf-8") as f:
            css_content = f.read()
    except FileNotFoundError:
        pass 

    # 2. [안전장치] 모바일용 필수 CSS (들여쓰기 제거됨)
    mobile_css = """<style>
.table-wrapper {
    overflow-x: auto;
    -webkit-overflow-scrolling: touch;
    margin-bottom: 1rem;
    border-radius: 8px;
    border: 1px solid #f0f2f6;
}
table {
    width: 100%;
    border-collapse: collapse;
    font-size: 14px;
    white-space: nowrap;
}
th {
    background-color: #f8f9fa;
    color: #495057;
    font-weight: 600;
    padding: 12px 8px;
    text-align: center;
    border-bottom: 2px solid #e9ecef;
}
td {
    padding: 10px 8px;
    text-align: center;
    border-bottom: 1px solid #f1f3f5;
    vertical-align: middle;
}
.name-cell {
    text-align: left !important;
    padding-left: 12px !important;
    font-weight: 500;
    color: #333;
}
</style>"""
    
    # CSS 결합 및 렌더링
    st.markdown(f"{mobile_css}<style>{css_content}</style>", unsafe_allow_html=True)

def sanitize_url(url):
    """[보안] 안전한 링크만 허용하는 검문소"""
    clean_url = str(url).strip()
    if clean_url.lower().startswith(('http://', 'https://')):
        return clean_url
    return "#"

def render_custom_table(data_frame):
    """
    데이터프레임을 모바일 반응형 HTML 테이블로 변환
    (HTML 조립 공정 최적화 및 들여쓰기 문제 해결)
    """
    if data_frame.empty:
        st.info("📭 표시할 데이터가 없습니다.")
        return

    # [핵심] HTML 행(Row) 조립 시작
    rows_buffer = ""
    
    for row in data_frame.to_dict('records'):
        # 1. 데이터 가져오기
        safe_code = str(row.get('코드', ''))
        safe_name = str(row.get('종목명', ''))
        safe_price = str(row.get('현재가', '0'))
        safe_exch = str(row.get('환구분', '-'))
        safe_ex_date = str(row.get('배당락일', '-'))
        
        # 2. 링크 생성
        blog_link = str(row.get('블로그링크', '')).strip()
        if not blog_link or blog_link == '#' or blog_link == 'nan':
            blog_link = "https://blog.naver.com/dividenpange"
        
        finance_link = str(row.get('금융링크', '#'))
        
        # 3. HTML 조각 조립 (한 줄로 작성하여 공백 문제 차단)
        code_html = f"<a href='{blog_link}' target='_blank' rel='noopener noreferrer' style='color:#0068c9; text-decoration:none; font-weight:bold; background-color:#f0f7ff; padding:2px 6px; border-radius:4px;'>{safe_code}</a>"
        
        # 배당률 스타일링
        try:
            dividend_yield = float(row.get('연배당률', 0))
        except:
            dividend_yield = 0.0
            
        try:
            months = int(row.get('신규상장개월수', 0))
        except:
            months = 0
            
        suffix = " <span style='font-size:0.8em; color:#999;'>(추정)</span>" if (0 < months < 12) else ""
        yield_color = "#ff4b4b" if dividend_yield >= 10 else "#333"
        yield_weight = "bold" if dividend_yield >= 10 else "normal"
        
        yield_html = f"<span style='color:{yield_color}; font-weight:{yield_weight};'>{dividend_yield:.2f}%{suffix}</span>"
        
        # 정보 링크 (아이콘화)
        info_html = f"<a href='{finance_link}' target='_blank' rel='noopener noreferrer' style='text-decoration:none; font-size:1.1em;'>🔗</a>"
        
        # 행(Row) 조립 - 불필요한 공백 제거
        rows_buffer += f"<tr><td>{code_html}</td><td class='name-cell'>{safe_name}</td><td>{safe_price}</td><td>{yield_html}</td><td>{safe_exch}</td><td style='color:#555;'>{safe_ex_date}</td><td>{info_html}</td></tr>"

    # 4. 테이블 전체 렌더링 (div.table-wrapper로 감싸서 가로 스크롤 허용)
    # [중요] f-string 대신 format 사용하고, 태그 앞 공백 제거
    table_html = """<div class="table-wrapper">
    <table>
        <thead>
            <tr>
                <th style="width: 80px;">코드</th>
                <th style="min-width: 140px; text-align:left; padding-left:12px;">종목명</th>
                <th style="min-width: 80px;">현재가</th>
                <th style="min-width: 90px;">연배당률</th>
                <th style="min-width: 80px;">환구분</th>
                <th style="min-width: 100px;">배당락일</th>
                <th style="width: 50px;">정보</th>
            </tr>
        </thead>
        <tbody>{}</tbody>
    </table>
</div>""".format(rows_buffer)
    
    st.markdown(table_html, unsafe_allow_html=True)
