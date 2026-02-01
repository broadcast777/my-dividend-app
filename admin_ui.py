import streamlit as st
import pandas as pd
import time
import re
import logic
from logger import logger

def render_admin_tools(df_raw, supabase):
    """관리자 전용 패널: 배당금 갱신 및 DB 관리"""
    
    with st.sidebar:
        st.markdown("---")
        st.subheader("🛠️ 배당금 갱신 도구")

        # 1. 종목 선택
        stock_options = {}
        for idx, row in df_raw.iterrows():
            name = row['종목명']
            try: months = int(row.get('신규상장개월수', 0))
            except: months = 0
            label = f"⭐ [신규 {months}개월] {name}" if months > 0 else name
            stock_options[label] = name

        selected_label = st.selectbox("갱신할 종목 선택", list(stock_options.keys()))
        target_stock = stock_options[selected_label]
        
        if target_stock:
            row = df_raw[df_raw['종목명'] == target_stock].iloc[0]
            cur_hist = row.get('배당기록', "")
            code = str(row.get('종목코드', '')).strip()
            category = str(row.get('분류', '국내')).strip()
            
            st.write("") 
            col_info, col_btn = st.columns([1, 1.5])
            with col_info:
                st.caption(f"코드: {code}")
                st.caption(f"분류: {category}")
            
            # 2. 배당률 조회
            with col_btn:
                if st.button("🔍 배당률 조회", key="btn_auto_check", use_container_width=True):
                    with st.spinner("탐색 중..."):
                        y_val, src = logic.fetch_dividend_yield_hybrid(code, category)
                        
                        if y_val and y_val > 0:
                            st.success(f"📈 {y_val}%")
                            st.caption(f"출처: {src}")
                        else:
                            st.error("실패")
                            st.caption(f"원인: {src}")
                        
                        # 조회값 임시 저장
                        try:
                            df_raw.loc[df_raw['종목코드'] == code, '연배당률_크롤링'] = float(y_val) if y_val else 0.0
                        except:
                            df_raw.loc[df_raw['종목코드'] == code, '연배당률_크롤링'] = 0.0

                        if category == '국내':
                            latest_div = None
                            try:
                                m = re.search(r'\(([\d,\.]+)원\)', str(src))
                                if m: latest_div = int(m.group(1).replace(',', '').split('.')[0])
                            except: latest_div = None
                            
                            if latest_div:
                                df_raw.loc[df_raw['종목코드'] == code, '연배당금_크롤링_auto'] = float(latest_div) * 12
                                st.success("조회값을 저장했습니다.")
                                st.session_state.df_dirty = df_raw

            st.divider()

            # 3. 데이터 우선순위 관리
            with st.expander("🚨 데이터 우선순위 관리 (특별배당 대응)"):
                st.caption("Auto 값이 이상하게 높으면(특별배당), 여기서 삭제하여 **TTM(2순위)**이나 **수동(3순위)**이 적용되게 하세요.")
                if st.button(f"🗑️ [{target_stock}] Auto 데이터 삭제", use_container_width=True):
                    success, msg = logic.reset_auto_data(code)
                    if success:
                        st.success(msg)
                        time.sleep(1)
                        st.rerun()
                    else:
                        st.error(msg)
            
            st.divider()

            # 4. 수동 업데이트
            st.caption("👇 배당금 수동 업데이트")
            new_div = st.number_input("이번 달 확정 배당금 (또는 월평균)", value=0, step=10)
            
            col_btn1, col_btn2 = st.columns(2)
            if col_btn1.button("💾 1개월 추가", use_container_width=True):
                new_total, new_hist = logic.update_dividend_rolling(cur_hist, new_div)
                df_raw.loc[df_raw['종목코드'] == code, '배당기록'] = new_hist
                df_raw.loc[df_raw['종목코드'] == code, '연배당금'] = new_total
                df_raw.loc[df_raw['종목코드'] == code, '연배당금_크롤링'] = new_total
                
                current_price = row.get('현재가', 0)
                if isinstance(current_price, str): current_price = float(re.sub(r'[^0-9.]', '', current_price) or 0)
                if not current_price: current_price = logic.get_safe_price(st.session_state.get('broker'), code, category)
                
                if current_price and current_price > 0:
                    new_yield = round((new_total / current_price) * 100, 2)
                    df_raw.loc[df_raw['종목코드'] == code, '연배당률'] = new_yield
                    df_raw.loc[df_raw['종목코드'] == code, '연배당률_크롤링'] = new_yield
                    st.success(f"✅ 추가 완료 ({new_total}원 / {new_yield}%)")
                st.session_state.df_dirty = df_raw

            if col_btn2.button("⚡ 1년치 강제", type="primary", use_container_width=True):
                new_total = new_div * 12
                new_hist = "|".join([str(new_div)] * 12)
                df_raw.loc[df_raw['종목코드'] == code, '배당기록'] = new_hist
                df_raw.loc[df_raw['종목코드'] == code, '연배당금'] = new_total
                
                current_price = row.get('현재가', 0)
                if isinstance(current_price, str): current_price = float(re.sub(r'[^0-9.]', '', current_price) or 0)
                if not current_price: current_price = logic.get_safe_price(st.session_state.get('broker'), code, category)
                
                if current_price and current_price > 0:
                    new_yield = round((new_total / current_price) * 100, 2)
                    df_raw.loc[df_raw['종목코드'] == code, '연배당률'] = new_yield
                    df_raw.loc[df_raw['종목코드'] == code, '연배당금_크롤링'] = new_total 
                    df_raw.loc[df_raw['종목코드'] == code, '연배당률_크롤링'] = new_yield 
                    st.success(f"⚡ 적용 완료 ({new_total}원 / {new_yield}%)")
                else:
                    st.warning("⚠️ 현재가를 가져오지 못해 배당률은 계산되지 않았습니다. (배당금은 저장됨)")
                st.session_state.df_dirty = df_raw

        st.markdown("---")
        st.subheader("💾 데이터 저장 및 백업")
        
        csv_data = df_raw.to_csv(index=False).encode('utf-8')
        st.download_button("📂 CSV 백업 다운로드", data=csv_data, file_name=f"stocks_backup.csv", mime='text/csv', use_container_width=True)

        st.write("") 
        
        # 5. 스마트 업데이트
        with st.expander("⚡ 전체/선택 종목 업데이트 (스마트)"):
            st.info("신규 상장(1년 미만)과 저배당주는 건너뜁니다.\nAuto가 0인 종목은 TTM(2순위)을 크롤링합니다.")
            
            all_stocks = df_raw['종목명'].tolist()
            selected_targets = st.multiselect(
                "갱신할 종목 선택 (비워두면 전체 갱신)", 
                options=all_stocks,
                placeholder="특정 종목만 갱신하려면 선택하세요"
            )
            
            if st.button("🔄 스마트 갱신 시작", key="btn_smart_update", use_container_width=True):
                targets = selected_targets if selected_targets else None
                my_bar = st.progress(0, text="데이터 수집 준비 중...")
                
                def update_progress_ui(percent, message):
                    my_bar.progress(percent, text=message)

                try:
                    success, msg, failed_list, new_df = logic.smart_update_and_save(
                        target_names=targets, 
                        progress_callback=update_progress_ui 
                    )
                    my_bar.empty()

                    if success:
                        if new_df is not None and not new_df.empty:
                            st.session_state.df_dirty = new_df
                        st.success(msg)
                        if failed_list:
                            with st.expander("⚠️ 일부 종목 업데이트 제외 (데이터 없음)"):
                                for f_name in failed_list:
                                    st.write(f"- {f_name}")
                    else:
                        st.error(msg)
                except Exception as e:
                    my_bar.empty()
                    st.error(f"실행 중 오류가 발생했습니다: {e}")

def render_etf_uploader(supabase):
    """(메인화면) 관리자용 ETF DB 업데이터"""
    st.divider()
    st.subheader("📤 ETF 구성종목 DB 업데이트 (관리자용)")
    st.info("💡 'etf_holdings.csv' (id 포함) 파일을 업로드하면 DB가 덮어씌워집니다.")
    
    uploaded_file = st.file_uploader("CSV 파일 업로드", type=['csv'])
    if uploaded_file is not None:
        st.write("파일명:", uploaded_file.name)
        if st.button("🚀 DB 덮어쓰기 (기존 데이터 삭제됨)", type="primary"):
            with st.spinner("DB 업데이트 중..."):
                try:
                    df_new = pd.read_csv(uploaded_file)
                    data_to_upload = df_new.to_dict(orient='records')
                    
                    supabase.table("etf_holdings").delete().neq("id", 0).execute()
                    supabase.table("etf_holdings").insert(data_to_upload).execute()
                    
                    st.success(f"✅ 업데이트 완료! (총 {len(data_to_upload)}건)")
                    st.balloons()
                except Exception as e:
                    st.error(f"업데이트 실패: {e}")


      
