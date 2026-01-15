import streamlit as st
import pandas as pd
import time
import logic
import datetime

# ==========================================
# [1] 메인 테이블 렌더링 (기존 동일)
# ==========================================
def render_custom_table(data_frame):
    """데이터프레임을 HTML 테이블로 예쁘게 렌더링"""
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
# [2] 사용자용: 필터 사이드바 (조작 레버 복구)
# ==========================================
def render_sidebar_filters(df):
    """사이드바 최상단: 일반 사용자용 검색 필터"""
    with st.sidebar:
        st.header("🔍 검색 및 필터")
        search_query = st.text_input("종목명 또는 코드 검색", "").upper()
        
        all_assets = sorted(df['자산유형'].unique())
        selected_assets = st.multiselect("🎨 자산 유형", all_assets, default=all_assets)
        
        all_hedge = sorted(df['환구분'].unique())
        selected_hedge = st.multiselect("💲 환노출/헤지", all_hedge, default=all_hedge)
        
        min_y, max_y = float(df['연배당률'].min()), float(df['연배당률'].max())
        selected_yield = st.slider("📈 연배당률 범위 (%)", 0.0, 25.0, (min_y, max_y))

        return search_query, selected_assets, selected_hedge, selected_yield

# ==========================================
# [3] 관리자용: 통합 제어 섹션 (모든 기능 복구)
# ==========================================
def render_admin_section(df_raw, supabase):
    """관리자용 도구 세트: 개별 수정 + 일괄 업데이트 + 저장"""
    with st.sidebar:
        st.markdown("---")
        st.subheader("🛠️ 관리자 마스터 패널")
        
        # [A] 개별 종목 정밀 도구 (복구 완료)
        with st.expander("🎯 개별 종목 수동 삭정", expanded=True):
            stock_options = {row['종목명']: row['종목명'] for _, row in df_raw.iterrows()}
            selected_name = st.selectbox("수정할 종목 선택", list(stock_options.keys()))
            
            if selected_name:
                row = df_raw[df_raw['종목명'] == selected_name].iloc[0]
                code, cat = str(row['종목코드']).strip(), str(row.get('분류','국내')).strip()
                
                # 1. 실시간 배당률 조회 (한투 API 연동)
                if st.button("🔍 실시간 배당률 조회", use_container_width=True):
                    y_val, src = logic.fetch_dividend_yield_hybrid(code, cat)
                    if y_val > 0: st.success(f"결과: {y_val}% ({src})")
                    else: st.error("조회 실패")
                
                st.divider()
                
                # 2. 이번 달 배당금 수동 계산기 (Rolling History)
                new_div = st.number_input("이번 달 배당금(원/$)", value=0, step=10)
                if st.button("🧮 배당기록 업데이트 계산", use_container_width=True):
                    new_total, new_hist = logic.update_dividend_rolling(row.get('배당기록',""), new_div)
                    st.info(f"계산된 연배당금: {new_total}")
                    st.code(f"새 배당기록: {new_hist}")
                    st.caption("※ 이 결과값을 CSV에 반영하려면 아래 저장 버튼을 누르세요.")

        # [B] ⚡ 일괄 자동 업데이트 (신규 제외 필터)
        with st.expander("⚡ 일괄 자동 삭정 (신규 제외)"):
            if st.button("자동 갱신 시작", type="primary", use_container_width=True):
                progress_bar = st.progress(0)
                status_text = st.empty()
                df_temp = df_raw.copy()
                total, updated, skipped = len(df_temp), 0, 0

                for i, row in df_temp.iterrows():
                    progress_bar.progress((i + 1) / total)
                    try: months = int(row.get('신규상장개월수', 0))
                    except: months = 0
                    
                    if months > 0:
                        status_text.caption(f"⏩ {row['종목명']}: 신규 통과")
                        skipped += 1
                        continue 

                    code, cat = str(row['종목코드']).strip(), str(row.get('분류','국내')).strip()
                    y_val, _ = logic.fetch_dividend_yield_hybrid(code, cat)
                    if y_val > 0:
                        df_temp.at[i, '연배당률'] = round(y_val, 2)
                        updated += 1
                    time.sleep(0.1)
                
                status_text.text("✅ 공정 완료!")
                st.success(f"업데이트: {updated} / 보호: {skipped}")
                st.session_state.df_dirty = df_temp

        # [C] 💾 데이터 영구 저장 (GitHub Commit)
        with st.expander("💾 서버 데이터 저장"):
            if st.checkbox("최종 덮어쓰기 승인", key="admin_save_confirm"):
                if st.button("🚀 깃허브 영구 저장", use_container_width=True):
                    target_df = st.session_state.get('df_dirty', df_raw)
                    success, msg = logic.save_to_github(target_df)
                    if success:
                        st.success(msg)
                        st.balloons()
                        time.sleep(2)
                        st.rerun()

    # 2. 하단 로그 (기존 유지)
    if supabase:
        with st.expander("🛠️ 접속 로그", expanded=False):
            try:
                resp = supabase.table("visit_logs").select("referer, created_at").order("created_at", desc=True).limit(5).execute()
                if resp.data: st.table(pd.DataFrame(resp.data))
            except: pass
