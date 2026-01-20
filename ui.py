import streamlit as st
import html
import re

# ---------------------------------------------------------
# [SECTION] UI 렌더링 모듈 (CSS 내장형 - 파일 로드 문제 원천 차단)
# ---------------------------------------------------------

def load_css():
    """
    [핵심 변경] 외부 파일 읽기를 제거하고, 스타일을 여기에 직접 심었습니다.
    이제 파일 경로 문제나 태그 꼬임 현상이 발생하지 않습니다.
    """
    
    # 모든 디자인 요소를 여기에 통합 (후원버튼, 카카오, 테이블 반응형)
    custom_css = """
    <style>
        /* 1. 후원 버튼 디자인 (아이콘 크기 강제 고정 포함) */
        .bmc-button {
            display: flex;
            align-items: center;
            justify-content: center;
            background-color: #FFDD00;
            color: #000000 !important;
            padding: 10px 15px;
            border-radius: 10px;
            text-decoration: none !important;
            font-weight: bold;
            font-size: 14px;
            box-shadow: 0 4px 8px rgba(0,0,0,0.1);
            transition: transform 0.2s;
            width: 100%;
            margin-bottom: 10px;
        }
        .bmc-button:hover {
            transform: translateY(-2px);
            background-color: #FADA00;
            text-decoration: none !important;
            color: #000000 !important;
        }
        .bmc-logo {
            width: 20px !important;
            height: 20px !important;
            margin-right: 8px;
            margin-bottom: 0px !important;
            vertical-align: middle;
        }

        /* 2. 카카오 로그인 버튼 */
        .kakao-login-btn {
            display: inline-flex;
            justify-content: center;
            align-items: center;
            width: 100%;
            background-color: #FEE500;
            color: #000000 !important;
            text-decoration: none !important;
            border: 1px solid rgba(0,0,0,0.05);
            padding: 0.5rem;
            border-radius: 0.5rem;
            font-weight: bold;
            font-size: 1rem;
            box-shadow: 0 1px 2px rgba(0,0,0,0.1);
            height: 2.6rem;
        }
        .kakao-login-btn:hover {
            color: #000000 !important;
            text-decoration: none !important;
        }

        /* 3. 모바일 반응형 테이블 (가로 스크롤) */
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
            white-space: nowrap; /* 줄바꿈 방지 */
            min-width: 600px; /* 표 최소 너비 확보 */
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
            background-color: #ffffff;
        }
        /* 종목명 왼쪽 고정 스타일 */
        .name-cell {
            text-align: left !important;
            padding-left: 12px !important;
            font-weight: 500;
            color: #333;
            position: sticky;
            left: 0;
            background-color: #fff;
            z-index: 1;
            border-right: 2px solid #f0f0f0;
            min-width: 140px;
        }
        tr:hover td {
            background-color: #fcfcfc;
        }
    </style>
    """
    
    # 화면에 렌더링
    st.markdown(custom_css, unsafe_allow_html=True)

def sanitize_url(url):
    """[보안] 안전한 링크만 허용하는 검문소"""
    clean_url = str(url).strip()
    if clean_url.lower().startswith(('http://', 'https://')):
        return clean_url
    return "#"

def render_custom_table(data_frame):
    """
    데이터프레임을 모바일 반응형 HTML 테이블로 변환
    """
    if data_frame.empty:
        st.info("📭 표시할 데이터가 없습니다.")
        return

    # HTML 행(Row) 조립
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
        
        # 3. HTML 조각 조립
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
        
        # 정보 링크
        info_html = f"<a href='{finance_link}' target='_blank' rel='noopener noreferrer' style='text-decoration:none; font-size:1.1em;'>🔗</a>"
        
        # 행(Row) 조립
        rows_buffer += f"<tr><td>{code_html}</td><td class='name-cell'>{safe_name}</td><td>{safe_price}</td><td>{yield_html}</td><td>{safe_exch}</td><td style='color:#555;'>{safe_ex_date}</td><td>{info_html}</td></tr>"

    # 4. 테이블 전체 렌더링
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
