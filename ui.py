import streamlit as st
import pandas as pd
import time
import logic
import datetime

# ==========================================
# [1] 메인 화면: 커스텀 테이블 렌더링
# ==========================================
def render_custom_table(data_frame):
    """데이터프레임을 HTML 테이블로 예쁘게 렌더링 (모바일 스크롤 적용)"""
    if data_frame.empty:
        st.info("검색 결과가 없습니다.")
        return

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
        yield_val = row.get('연배당률', 0)
        yield_display = f"<span style='color:{'#ff4b4b' if yield_val>=10 else '#333'}; font-weight:{'bold' if yield_val>=10 else 'normal'};'>{yield_val:.2f}%{suffix}</span>"
        
        html_rows.append(f"<tr><td>{b_link}</td><td class='name-cell'>{stock_name}</td><td>{row['현재가']}</td><td>{yield_display}</td><td>{row['환구분']}</td><td>{row['배당락일']}</td><td>{f_link}</td></tr>")

    st.markdown(f"""
    <style>
        .table-container {{ overflow-x: auto; white-space: nowrap; margin-bottom: 20px; border: 1px solid #eee; border-radius: 8px; }}
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

# ==========================================
# [2] 사이드바 상단: 사용자 필터 (복구 완료)
# ==========================================
def render_sidebar_filters(df):
    """사이드바 상단 조작 레버: 검색 및 필터링 기능"""
    with st.sidebar:
        st.header("🔍 검색 및 필터")
        
        # 1. 검색어
        search_query = st.text_input("종목명 또는 코드 검색", "").upper()
        
        # 2. 자산유형 멀티선택
        all_assets = sorted(df['자산유형'].unique())
        selected_assets = st.multiselect("🎨 자산 유형", all_assets, default=all_assets)
        
        # 3. 환구분 멀티선택
        all_hedge = sorted(df['환구분'].unique())
        selected_hedge = st.multiselect("💲 환노출/헤지", all_hedge, default=all_hedge)
        
        # 4. 배당률 슬라이더
        min_y, max_y = float(df['연배당률'].min()), float(df['연배당률'].max())
        selected_yield = st.slider("📈 연배당률 범위 (%)", 0.0, 25.0, (min_y, max_y))

        return search_query, selected_assets, selected_hedge, selected_yield

# ==========================================
# [3] 사이드바 하단: 관리자 엔진 (신규 보호 필터 탑재)
# ==========================================
def render_admin_section(df_raw, supabase):
    """관리자용 자동 삭정 및 저장 도구"""
    with st.sidebar:
        st.markdown("---")
        st.subheader("🛠️ 관리자 전용 엔진")
        
        # [A] ⚡ 일괄 자동 업데이트 (신규 상장주 SKIP 로직)
        with st.expander("⚡ 일괄 자동 삭정 (신규 제외)"):
            if st.button("자동 갱신 시작", type="primary", use_container_width=True):
                progress_bar = st.progress(0)
                status_text = st.empty()
                
                df_temp = df_raw.copy()
                total = len(df_temp)
                updated, skipped = 0, 0

                for i, row in df_temp.iterrows():
                    progress_bar.progress((i + 1) / total)
                    
                    # [🚨 신규 종목 보호 센서]
                    try: months = int(row.get('신규상장개월수', 0))
                    except: months = 0
                    
                    if months > 0:
                        status_text.caption(f"⏩ {row['종목명']}: 신규 종목 패스")
                        skipped += 1
                        continue # 이 종목은 건너뛰고 다음 종목으로!

                    # 일반 종목만 삭정(조회) 시작
                    code, cat = str(row['종목코드']).strip(), str(row.get('분류','국내')).strip()
                    status_text.caption(f"🔍 {row['종목명']} 조회 중...")
                    
                    y_val, _ = logic.fetch_dividend_yield_hybrid(code, cat)
                    if y_val > 0:
                        df_temp.at[i, '연배당률'] = round(y_val, 2)
                        updated += 1
                    
                    time.sleep(0.1) # 서버 과부하 방지
                
                status_text.text("✅ 공정 완료!")
                st.success(f"성공: {updated}건 / 신규 보호: {skipped}건")
                st.session_state.df_dirty = df_temp # 임시 저장고 적재

        # [B] 💾 데이터 영구 저장 (덮어쓰기 버튼)
        with st.expander("💾 데이터 영구 저장"):
            st.info("💡 수정된 내용을 깃허브에 반영하시겠습니까?")
            if st.checkbox("네, 최종 덮어쓰기를 승인합니다.", key="admin_save_confirm"):
                if st.button("🚀 깃허브 저장 (Commit)", type="primary", use_container_width=True):
                    target_df = st.session_state.get('df_dirty', df_raw)
                    success, msg = logic.save_to_github(target_df)
                    if success:
                        st.success(msg)
                        st.balloons()
                        time.sleep(2)
                        st.rerun()

    # 2. 하단 로그 섹션 (기존 유지)
    if supabase:
        with st.expander("🛠️ 유입 로그", expanded=False):
            try:
                resp = supabase.table("visit_logs").select("referer, created_at").order("created_at", desc=True).limit(5).execute()
                if resp.data:
                    log_df = pd.DataFrame(resp.data)
                    log_df['created_at'] = pd.to_datetime(log_df['created_at']).dt.tz_convert('Asia/Seoul').dt.strftime('%Y-%m-%d %H:%M:%S')
                    st.table(log_df)
            except: pass
