import streamlit as st
import pandas as pd
import logic
import time

def render_admin_dashboard(df_raw):
    """
    관리자 전용 대시보드 및 데이터 관리 도구를 렌더링합니다.
    (기존 app.py의 관리자 로직을 그대로 가져옴)
    """
    with st.sidebar:
        st.markdown("---")
        st.subheader("🛠️ 배당금 갱신 도구")
        
        # 1. 종목 식별 및 선택 로직
        stock_options = {}
        for idx, row in df_raw.iterrows():
            name = row['종목명']
            try:
                months = int(row.get('신규상장개월수', 0))
            except: months = 0
            
            if months > 0:
                label = f"⭐ [신규 {months}개월] {name}"
            else:
                label = name
            stock_options[label] = name

        selected_label = st.selectbox("갱신할 종목 선택", list(stock_options.keys()))
        target_stock = stock_options[selected_label]
        
        if target_stock:
            row = df_raw[df_raw['종목명'] == target_stock].iloc[0]
            cur_hist = row.get('배당기록', "")
            code = str(row.get('종목코드', '')).strip()
            category = str(row.get('분류', '국내')).strip()
            
            # 2. 배당률 자동 조회 UI
            st.write("") 
            col_info, col_btn = st.columns([1, 1.5])
            with col_info:
                st.caption(f"코드: {code}")
                st.caption(f"분류: {category}")
            with col_btn:
                if st.button("🔍 배당률 조회", key="btn_auto_check", use_container_width=True):
                    with st.spinner("탐색 중..."):
                        y_val, src = logic.fetch_dividend_yield_hybrid(code, category)
                        if y_val > 0:
                            st.success(f"📈 {y_val}%")
                            st.caption(f"출처: {src}")
                        else:
                            st.error("실패")
                            st.caption(f"원인: {src}")
                            
            st.divider()

            # 3. 수동 입력 및 계산
            new_div = st.number_input("이번 달 확정 배당금", value=0, step=10)
            if st.button("계산 실행", use_container_width=True):
                new_total, new_hist = logic.update_dividend_rolling(cur_hist, new_div)
                st.success("완료!")
                st.code(new_hist, language="text")

    # 4. 데이터 저장 및 백업 시스템
    st.subheader("💾 데이터 저장 및 백업")

    # [안전 장치 1] 백업 다운로드
    csv_data = df_raw.to_csv(index=False).encode('utf-8')
    st.download_button(
        label="📂 (혹시 모르니) 현재 파일 백업하기",
        data=csv_data,
        file_name=f"stocks_backup_{pd.Timestamp.now().strftime('%Y%m%d')}.csv",
        mime='text/csv',
        use_container_width=True
    )

    st.write("") 

    # [안전 장치 2] 신규 제외 자동 갱신
    with st.expander("⚡ 전체 종목 자동 업데이트 (신규 제외)"):
        st.caption("신규 상장 종목(⭐)과 배당률 2% 미만은 건너뜁니다.")
        if st.button("전체 자동 갱신 시작"):
            progress_bar = st.progress(0)
            status_text = st.empty()
            updated_count = 0
            skipped_count = 0
            total_stocks = len(df_raw)
            df_temp = df_raw.copy()
            
            for i, row in df_temp.iterrows():
                progress_bar.progress((i + 1) / total_stocks)
                status_text.text(f"검사 중: {row['종목명']}...")
                
                try: months = int(row.get('신규상장개월수', 0))
                except: months = 0
                
                if months > 0:
                    skipped_count += 1
                    continue
                
                code = str(row['종목코드']).strip()
                cat = str(row.get('분류', '국내')).strip()
                y_val, _ = logic.fetch_dividend_yield_hybrid(code, cat)
                
                if y_val < 2.0:
                    skipped_count += 1
                    continue

                df_temp.at[i, '연배당률'] = round(y_val, 2) 
                updated_count += 1
                
            status_text.text("완료!")
            st.success(f"✅ {updated_count}개 업데이트 대기 / 🛡️ {skipped_count}개 보호됨")
            st.session_state.df_dirty = df_temp

    st.markdown("---")

    # [안전 장치 3] 최종 저장 (체크박스 확인)
    st.info("💡 위에서 내용을 충분히 검토하셨나요?")
    confirm_save = st.checkbox("네, 덮어써도 좋습니다.")

    if confirm_save:
        if st.button("🚀 깃허브에 영구 저장 (Commit)", type="primary", use_container_width=True):
            with st.spinner("서버에 업로드 중..."):
                target_df = st.session_state.get('df_dirty', df_raw)
                success, msg = logic.save_to_github(target_df)
                if success:
                    st.success(msg)
                    st.balloons()
                    time.sleep(2)
                    st.rerun()
                else:
                    st.error(msg)
    else:
        st.button("🚀 깃허브에 영구 저장", disabled=True, use_container_width=True)
