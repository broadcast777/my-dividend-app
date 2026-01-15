import streamlit as st
import pandas as pd
import time  # <--- [확인] 섀도잉 에러 방지를 위해 전역에 배치
import logic
import datetime

# ==========================================
# [1] 기존 기능: 커스텀 테이블 렌더링
# ==========================================
def render_custom_table(data_frame):
    """데이터프레임을 HTML 테이블로 예쁘게 렌더링 (모바일 스크롤 적용)"""
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
        yield_display = f"<span style='color:{'#ff4b4b' if row['연배당률']>=10 else '#333'}; font-weight:{'bold' if row['연배당률']>=10 else 'normal'};'>{row['연배당률']:.2f}%{suffix}</span>"
        
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

def render_admin_section(df_raw, supabase):
    """관리자용 사이드바 도구와 로그 섹션 (신규 필터링 자동화 로직 추가)"""
    
    # 1. 사이드바 관리자 도구
    with st.sidebar:
        st.markdown("---")
        st.subheader("🛠️ 배당금 갱신 도구")
        
        # [A] 종목 선택 및 개별 조회 (수동 공정)
        stock_options = {}
        for _, row in df_raw.iterrows():
            name = row['종목명']
            try: months = int(row.get('신규상장개월수', 0))
            except: months = 0
            label = f"⭐ [신규 {months}개월] {name}" if months > 0 else name
            stock_options[label] = name

        selected_label = st.selectbox("갱신할 종목 선택", list(stock_options.keys()))
        target_stock = stock_options[selected_label]
        
        if target_stock:
            row = df_raw[df_raw['종목명'] == target_stock].iloc[0]
            code, cat = str(row['종목코드']).strip(), str(row.get('분류','국내')).strip()
            
            col_info, col_btn = st.columns([1, 1.5])
            with col_info:
                st.caption(f"코드: {code}\n분류: {cat}")
            with col_btn:
                if st.button("🔍 배당률 조회", key="btn_admin_check"):
                    y_val, src = logic.fetch_dividend_yield_hybrid(code, cat)
                    if y_val > 0: st.success(f"📈 {y_val}%"); st.caption(f"출처: {src}")
                    else: st.error("조회 실패")
            
            st.divider()
            new_div = st.number_input("이번 달 확정 배당금", value=0, step=10, key="admin_div_input")
            if st.button("계산 실행", use_container_width=True, key="admin_calc_btn"):
                _, new_hist = logic.update_dividend_rolling(row.get('배당기록',""), new_div)
                st.success("완료!"); st.code(new_hist)

        st.markdown("---")
        
        # [B] ⚡ 전체 자동 업데이트 (일괄 자동화 공정)
        st.subheader("⚡ 일괄 업데이트")
        with st.expander("일반 종목 자동 삭정 (신규 제외)"):
            if st.button("자동 갱신 시작", type="primary", use_container_width=True):
                progress_bar = st.progress(0)
                status_text = st.empty()
                
                df_temp = df_raw.copy()
                total_stocks = len(df_temp)
                updated_count = 0
                skipped_count = 0

                for i, row in df_temp.iterrows():
                    # 진행바 업데이트
                    progress_bar.progress((i + 1) / total_stocks)
                    
                    # [핵심 안전 센서] 신규 상장 종목 필터링
                    try: months = int(row.get('신규상장개월수', 0))
                    except: months = 0
                    
                    if months > 0:
                        status_text.caption(f"⏩ {row['종목명']} (신규 종목 패스)")
                        skipped_count += 1
                        continue # 신규 상장주는 업데이트를 수행하지 않고 다음 공정으로!

                    # 일반 종목 데이터 갱신
                    code, cat = str(row['종목코드']).strip(), str(row.get('분류','국내')).strip()
                    status_text.caption(f"🔍 {row['종목명']} 조회 중...")
                    
                    y_val, _ = logic.fetch_dividend_yield_hybrid(code, cat)
                    
                    if y_val > 0:
                        df_temp.at[i, '연배당률'] = round(y_val, 2)
                        updated_count += 1
                    
                    # 서버 과부하 방지를 위한 미세한 공정 대기
                    time.sleep(0.1)
                
                status_text.text("✅ 공정 완료!")
                st.success(f"성공: {updated_count}건 / 신규 보호: {skipped_count}건")
                # 결과물을 세션 스테이트에 저장 (나중에 깃허브 저장 시 사용)
                st.session_state.df_dirty = df_temp

        st.markdown("---")
        st.subheader("💾 데이터 저장 및 백업")
        
        # 백업 및 저장 (수정 없음)
        st.download_button(
            label="📂 현재 파일 백업하기", 
            data=df_raw.to_csv(index=False).encode('utf-8'), 
            file_name=f"stocks_backup_{datetime.datetime.now().strftime('%Y%m%d')}.csv", 
            mime='text/csv', 
            use_container_width=True
        )

        st.info("💡 수정 사항을 반영하시겠습니까?")
        if st.checkbox("네, 덮어써도 좋습니다.", key="admin_save_confirm"):
            if st.button("🚀 깃허브에 영구 저장 (Commit)", type="primary", use_container_width=True):
                target_df = st.session_state.get('df_dirty', df_raw)
                success, msg = logic.save_to_github(target_df)
                if success:
                    st.success(msg)
                    st.balloons()
                    time.sleep(2)
                    st.rerun()

    # 2. 메인 화면 하단 관리자 로그 (기존과 동일)
    if supabase:
        with st.expander("🛠️ 관리자 전용: 최근 유입 로그 (최근 5건)", expanded=False):
            try:
                resp = supabase.table("visit_logs").select("referer, created_at").order("created_at", desc=True).limit(5).execute()
                if resp.data:
                    log_df = pd.DataFrame(resp.data)
                    log_df['created_at'] = pd.to_datetime(log_df['created_at']).dt.tz_convert('Asia/Seoul').dt.strftime('%Y-%m-%d %H:%M:%S')
                    st.table(log_df)
                else: st.write("기록된 로그가 없습니다.")
            except: st.write("로그 로드 중 오류 발생")
