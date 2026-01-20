import streamlit as st
import html
import re

# ---------------------------------------------------------
# [SECTION] UI 렌더링 모듈 (모바일 반응형 서스펜션 장착)
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

    # 2. [안전장치] 모바일용 필수 CSS 강제 주입 (파일이 없어도 깨짐 방지)
    # 기계공학적 설계: 외부 파일 유실 시에도 작동하는 예비 전력(Backup Power)
    mobile_css = """
    <style>
        /* 모바일용 가로 스크롤 컨테이너 */
        .table-wrapper {
            overflow-x: auto;
            -webkit-overflow-scrolling: touch; /* 아이폰 부드러운 스크롤 */
            margin-bottom: 1rem;
            border-radius: 8px;
            border: 1px solid #f0f2f6;
        }
        
        /* 표 디자인 표준화 */
        table {
            width: 100%;
            border-collapse: collapse;
            font-size: 14px; /* 모바일 가독성 최적화 */
            white-space: nowrap; /* 좁은 화면에서 줄바꿈 방지 */
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

        /* 종목명은 왼쪽 정렬 */
        .name-cell {
            text-align: left !important;
            padding-left: 12px !important;
            font-weight: 500;
            color: #333;
        }
    </style>
    """
    
    # 기존 CSS와 필수 CSS를 합쳐서 렌더링
    st.markdown(f"{mobile_css}<style>{css_content}</style>", unsafe_allow_html=True)

def sanitize_url(url):
    """[보안] 안전한 링크만 허용하는 검문소"""
    clean_url = str(url).strip()
    # 자바스크립트 주입 공격 방지
    if clean_url.lower().startswith(('http://', 'https://')):
        return clean_url
    return "#"

def render_custom_table(data_frame):
    """
    데이터프레임을 모바일 반응형 HTML 테이블로 변환
    (HTML 조립 공정 최적화)
    """
    if data_frame.empty:
        st.info("📭 표시할 데이터가 없습니다.")
        return

    html_rows = []
    
    # 성능 최적화를 위해 컬럼 인덱싱 미리 준비
    # itertuples가 iterrows보다 훨씬 빠릅니다 (대량 데이터 대비)
    for row in data_frame.to_dict('records'):
        # 1. 데이터 보안 및 포맷팅 (Null 방어)
        safe_code = html.escape(str(row.get('코드', '')))
        safe_name = html.escape(str(row.get('종목명', '')))
        safe_price = html.escape(str(row.get('현재가', '0')))
        safe_exch = html.escape(str(row.get('환구분', '-')))
        safe_ex_date = html.escape(str(row.get('배당락일', '-')))
        
        # 2. 링크 보안 검사
        blog_link = str(row.get('블로그링크', '')).strip()
        if not blog_link or blog_link == '#' or blog_link == 'nan':
            blog_link = "https://blog.naver.com/dividenpange"
        safe_blog_url = sanitize_url(blog_link)
        
        finance_link = str(row.get('금융링크', '#'))
        safe_finance_url = sanitize_url(finance_link)
        
        # 3. HTML 조각 조립 (가독성 향상)
        # 종목코드 링크 (블로그)
        code_html = f"""<a href='{safe_blog_url}' target='_blank' rel='noopener noreferrer' 
                        style='color:#0068c9; text-decoration:none; font-weight:bold; 
                        background-color:#f0f7ff; padding:2px 6px; border-radius:4px;'>{safe_code}</a>"""
        
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
        info_html = f"""<a href='{safe_finance_url}' target='_blank' rel='noopener noreferrer' 
                        style='text-decoration:none; font-size:1.1em;'>🔗</a>"""
        
        # 행(Row) 조립
        row_html = f"""
        <tr>
            <td>{code_html}</td>
            <td class='name-cell'>{safe_name}</td>
            <td>{safe_price}</td>
            <td>{yield_html}</td>
            <td>{safe_exch}</td>
            <td style='color:#555;'>{safe_ex_date}</td>
            <td>{info_html}</td>
        </tr>
        """
        html_rows.append(row_html)

    # 4. 테이블 전체 렌더링 (div.table-wrapper로 감싸서 가로 스크롤 허용)
    st.markdown(f"""
    <div class="table-wrapper">
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
            <tbody>
                {''.join(html_rows)}
            </tbody>
        </table>
    </div>
    """, unsafe_allow_html=True)
