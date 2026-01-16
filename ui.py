import streamlit as st

# ---------------------------------------------------------
# [SECTION] UI 렌더링 모듈
# ---------------------------------------------------------

def render_custom_table(data_frame):
    """
    데이터프레임을 Streamlit 환경에 최적화된 HTML/CSS 테이블로 변환하여 출력합니다.
    
    주요 기능:
    1. 모바일 환경 대응: 가로 스크롤 및 종목명 열 고정(Sticky)
    2. 데이터 시각화: 고배당주(10% 이상) 강조 및 신규 상장 추정치 표시
    3. 인터랙티브 링크: 종목 코드 클릭 시 블로그 연결, 정보 클릭 시 금융 정보 연결
    """
    
    # -----------------------------------------------------
    # 1. 데이터 파싱 및 행 생성 로직
    # -----------------------------------------------------
    html_rows = []
    
    for _, row in data_frame.iterrows():
        # [블로그 링크 처리] 링크가 없거나 '#'일 경우 기본 블로그 주소로 대체
        blog_link = str(row.get('블로그링크', '')).strip()
        if not blog_link or blog_link == '#':
            blog_link = "https://blog.naver.com/dividenpange"
        
        # [HTML 요소 생성] 종목코드(링크), 종목명, 금융정보 링크 구성
        b_link = f"<a href='{blog_link}' target='_blank' style='color:#0068c9; text-decoration:none; font-weight:bold;'>{row['코드']}</a>"
        stock_name = f"<span style='color:#333; font-weight:500;'>{row['종목명']}</span>"
        f_link = f"<a href='{row['금융링크']}' target='_blank' style='color:#0068c9; text-decoration:none;'>🔗정보</a>"
        
        # [배당률 강조 로직] 10% 이상은 빨간색/굵게, 12개월 미만 상장주는 '(추정)' 문구 추가
        is_new = row.get('신규상장개월수', 0)
        suffix = " (추정)" if (0 < is_new < 12) else ""
        yield_display = f"<span style='color:{'#ff4b4b' if row['연배당률']>=10 else '#333'}; font-weight:{'bold' if row['연배당률']>=10 else 'normal'};'>{row['연배당률']:.2f}%{suffix}</span>"
        
        # [행 데이터 취합] 최종적으로 테이블의 한 줄(tr)을 완성
        html_rows.append(f"<tr><td>{b_link}</td><td class='name-cell'>{stock_name}</td><td>{row['현재가']}</td><td>{yield_display}</td><td>{row['환구분']}</td><td>{row['배당락일']}</td><td>{f_link}</td></tr>")

    # -----------------------------------------------------
    # 2. CSS 스타일 정의 및 테이블 렌더링
    # -----------------------------------------------------
    st.markdown(f"""
    <style>
        /* 테이블 컨테이너: 가로 스크롤 및 테두리 설정 */
        .table-container {{
            overflow-x: auto; 
            white-space: nowrap;
            margin-bottom: 20px;
            border: 1px solid #eee;
            border-radius: 8px;
        }}
        
        /* 기본 테이블 스타일 */
        table {{ width: 100%; border-collapse: collapse; font-size: 14px; min-width: 600px; }}
        th {{ background: #f0f2f6; padding: 12px 8px; border-bottom: 2px solid #ddd; text-align: center; }}
        td {{ padding: 10px 8px; border-bottom: 1px solid #eee; text-align: center; }}
        
        /* [핵심] 종목명 열 고정 스타일: 좌측 끝에 고정되어 스크롤 시에도 유지됨 */
        .name-cell {{ 
            text-align: left !important; 
            min-width: 120px; 
            position: sticky; 
            left: 0; 
            background: white; 
            z-index: 1; 
            border-right: 1px solid #eee; 
        }}
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
