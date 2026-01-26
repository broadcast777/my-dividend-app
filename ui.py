import streamlit as st
import html
import re
import pandas as pd
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

import streamlit as st
import pandas as pd

import streamlit as st
import pandas as pd

def render_custom_table(data_frame, key_suffix="default"):
    """
    [최종 수정] 소수점 2자리 제한 & 색상 구분 명확화 (보라/빨강/파랑)
    """
    if data_frame.empty:
        st.info("📭 표시할 데이터가 없습니다.")
        return

    # 1. 보기 모드 선택
    view_mode = st.radio(
        "보기 방식 선택", 
        ["📱 리스트(모바일 추천)", "💻 전체 표(PC 추천)"], 
        horizontal=True,
        label_visibility="collapsed",
        key=f"view_mode_{key_suffix}"
    )
    st.write("") 

    # -----------------------------------------------------------
    # 2-A. 모바일 리스트 모드
    # -----------------------------------------------------------
    if "리스트" in view_mode:
        for idx, row in data_frame.iterrows():
            
            # (1) 데이터 준비
            name = str(row.get('종목명', ''))
            code = str(row.get('코드', ''))
            category = str(row.get('분류', '국내'))
            
            blog_link = str(row.get('블로그링크', '')).strip()
            if not blog_link or blog_link == '#' or blog_link == 'nan':
                blog_link = "https://blog.naver.com/dividenpange"

            # (2) 배당률 처리 (소수점 자르기 & 색상 변경)
            raw_yield = row.get('연배당률', '')
            
            if pd.isna(raw_yield) or str(raw_yield).strip() == '':
                disp_yield = "-"
                yield_color = "#999999"
            else:
                try:
                    # 숫자 변환
                    clean_num = float(str(raw_yield).replace('%', '').replace(':black', '').strip())
                    
                    # [색상 로직 변경] 확실하게 구분!
                    if clean_num >= 15: 
                        yield_color = "#8E44AD"   # 보라색 (초고배당)
                    elif clean_num >= 10: 
                        yield_color = "#E74C3C"   # 빨간색 (고배당)
                    elif clean_num >= 5: 
                        yield_color = "#2980B9"   # 파란색 (중배당)
                    else: 
                        yield_color = "#333333"   # 검정색
                    
                    # [핵심] 소수점 2자리로 강제 포맷팅
                    disp_yield = f"{clean_num:.2f}%"
                    
                except:
                    disp_yield = str(raw_yield)
                    yield_color = "#333333"

            # (3) 날짜 처리
            ex_date = str(row.get('배당락일', '-')).replace("매월 ", "").replace("(영업일 기준)", "")
            base_date = str(row.get('데이터기준일', '-'))[:10]

            # (4) HTML 카드 출력
            card_html = f"""
<div style="background-color: white; padding: 16px; border-radius: 12px; box-shadow: 0 2px 5px rgba(0,0,0,0.05); margin-bottom: 12px; border: 1px solid #f0f0f0;">
    <div style="display: flex; justify-content: space-between; align-items: flex-start;">
        <div style="width: 70%;">
            <a href="{blog_link}" target="_blank" style="text-decoration:none; color:#333;">
                <h4 style="margin: 0 0 6px 0; font-size: 1.05rem; font-weight: 700;">{name}</h4>
            </a>
            <span style="font-size: 0.8rem; color: #666; background-color: #f5f6f7; padding: 3px 8px; border-radius: 4px;">
                {code} | {category}
            </span>
        </div>
        <div style="text-align: right; width: 30%;">
            <span style="font-size: 0.75rem; color: #888; display:block; margin-bottom:2px;">연배당률</span>
            <span style="font-size: 1.25rem; font-weight: 800; color: {yield_color};">
                {disp_yield}
            </span>
        </div>
    </div>
    <div style="margin-top: 12px; padding-top: 10px; border-top: 1px dashed #eee; display: flex; justify-content: space-between; font-size: 0.85rem;">
        <div style="color: #666;">
            <span style="color:#999;">기준일</span> {base_date}
        </div>
        <div style="color: #333; font-weight:500;">
            <span style="color:#999; font-weight:400;">배당락일</span> {ex_date}
        </div>
    </div>
</div>
"""
            st.markdown(card_html, unsafe_allow_html=True)

    # -----------------------------------------------------------
    # 2-B. PC 테이블 모드
    # -----------------------------------------------------------
    else:
        rows_buffer = ""
        for row in data_frame.to_dict('records'):
            safe_code = str(row.get('코드', ''))
            safe_name = str(row.get('종목명', ''))
            safe_price = str(row.get('현재가', '0'))
            safe_exch = str(row.get('환구분', '-'))
            safe_ex_date = str(row.get('배당락일', '-'))
            
            blog_link = str(row.get('블로그링크', '')).strip()
            if not blog_link or blog_link == '#' or blog_link == 'nan':
                blog_link = "https://blog.naver.com/dividenpange"
            
            finance_link = str(row.get('금융링크', '#'))
            
            code_html = f"<a href='{blog_link}' target='_blank' style='color:#0068c9; text-decoration:none; font-weight:bold; background-color:#f0f7ff; padding:2px 6px; border-radius:4px;'>{safe_code}</a>"
            
            try: 
                raw_y = float(row.get('연배당률', 0))
                # PC 버전도 소수점 2자리 적용
                dividend_yield_str = f"{raw_y:.2f}%"
            except: 
                raw_y = 0.0
                dividend_yield_str = "0.00%"
                
            try: months = int(row.get('신규상장개월수', 0))
            except: months = 0
                
            suffix = " <span style='font-size:0.8em; color:#999;'>(추정)</span>" if (0 < months < 12) else ""
            
            # PC 버전 색상도 통일
            if raw_y >= 15: y_col = "#8E44AD"
            elif raw_y >= 10: y_col = "#E74C3C"
            elif raw_y >= 5: y_col = "#2980B9"
            else: y_col = "#333"
            
            yield_html = f"<span style='color:{y_col}; font-weight:bold;'>{dividend_yield_str}{suffix}</span>"
            info_html = f"<a href='{finance_link}' target='_blank' style='text-decoration:none; font-size:1.1em;'>🔗</a>"
            
            rows_buffer += f"<tr><td>{code_html}</td><td class='name-cell'>{safe_name}</td><td>{safe_price}</td><td>{yield_html}</td><td>{safe_exch}</td><td style='color:#555;'>{safe_ex_date}</td><td>{info_html}</td></tr>"

        table_html = f"""
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
        <tbody>{rows_buffer}</tbody>
    </table>
</div>
"""
        st.markdown(table_html, unsafe_allow_html=True)
