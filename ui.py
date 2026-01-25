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

# [ui.py]

# 1. 함수 인자에 key_suffix 추가 (기본값은 'default')
def render_custom_table(data_frame, key_suffix="default"):
    """
    [업그레이드] 모바일(카드) vs PC(표) 보기 모드 지원 + 탭 중복 에러 방지(key)
    """
    if data_frame.empty:
        st.info("📭 표시할 데이터가 없습니다.")
        return

    # -----------------------------------------------------------
    # 1. 보기 모드 선택 (화면 상단 토글)
    # -----------------------------------------------------------
    view_mode = st.radio(
        "보기 방식 선택", 
        ["📱 리스트(모바일 추천)", "💻 전체 표(PC 추천)"], 
        horizontal=True,
        label_visibility="collapsed", # 라벨 숨김
        key=f"view_mode_{key_suffix}" # 🔥 [핵심] 탭마다 다른 키를 부여해서 중복 방지!
    )

    st.write("") 
    
    # ... (아래 코드는 기존과 동일) ...

    # -----------------------------------------------------------
    # 2-A. 모바일 리스트 모드 (토스 스타일 카드 뷰)
    # -----------------------------------------------------------
    if "리스트" in view_mode:
        # 데이터를 한 줄씩 꺼내서 '카드'로 만듭니다.
        for row in data_frame.to_dict('records'):
            
            # 데이터 준비
            name = str(row.get('종목명', ''))
            code = str(row.get('코드', ''))
            category = str(row.get('분류', '')) # 국내/해외
            
            try: yield_val = float(row.get('연배당률', 0))
            except: yield_val = 0.0
            
            ex_date = str(row.get('배당락일', '-')).replace("매월 ", "").replace("(영업일 기준)", "").strip()
            
            # 링크 준비
            blog_link = str(row.get('블로그링크', '')).strip()
            if not blog_link or blog_link == '#' or blog_link == 'nan':
                blog_link = "https://blog.naver.com/dividenpange"

            # --- 카드 디자인 시작 (st.container) ---
            with st.container(border=True):
                # 3단 분할 (이름 / 배당률 / 시기)
                c1, c2, c3 = st.columns([3.5, 1.5, 1.5])
                
                with c1:
                    # 종목명 (클릭하면 블로그 이동하게 링크 적용)
                    st.markdown(f"**[{name}]({blog_link})**")
                    st.caption(f"{code} | {category}")
                
                with c2:
                    # 배당률 강조
                    color = "red" if yield_val >= 10 else "black"
                    st.markdown(f":{color}[**{yield_val:.2f}%**]")
                    st.caption("연배당률")
                
                with c3:
                    # 시기 표시
                    st.markdown(f"**{ex_date}**")
                    st.caption("기준일")

    # -----------------------------------------------------------
    # 2-B. PC 테이블 모드 (기존에 만드신 HTML 코드 유지)
    # -----------------------------------------------------------
    else:
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
            info_html = f"<a href='{finance_link}' target='_blank' rel='noopener noreferrer' style='text-decoration:none; font-size:1.1em;'>🔗</a>"
            
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
