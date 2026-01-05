import streamlit as st
from supabase import create_client
import pandas as pd
import altair as alt
import hashlib

# [모듈화] 분리한 파일들을 불러옵니다
import logic 
import ui

# ==========================================
# [1] 기본 설정
# ==========================================
st.set_page_config(page_title="배당팽이 대시보드", layout="wide")

URL = st.secrets["SUPABASE_URL"]
KEY = st.secrets["SUPABASE_KEY"]
supabase = create_client(URL, KEY)

# ==========================================
# [2] 메인 애플리케이션
# ==========================================
def main():
    # --- [추가] 점검 모드 및 개발자 비밀 통로 로직 ---
    is_dev_mode = st.query_params.get("dev", "false").lower() == "true"
    MAINTENANCE_MODE = False  # 점검 끝내려면 False로 바꾸면 됨

    if MAINTENANCE_MODE and not is_dev_mode:
        st.set_page_config(page_title="점검 중 - 배당팽이", page_icon="🚧") # 점검 시 타이틀 변경
        st.title("🚧 시스템 정기 점검 중")
        st.subheader("한투 API 연동 및 데이터 고도화 작업 중입니다.")
        st.info("더 정확하고 빠른 실시간 시세 연동을 위해 시스템을 개선하고 있습니다. 잠시 후 다시 접속해 주세요!")
        st.image("https://media.giphy.com/media/v1.Y2lkPTc5MGI3NjExNHJueGZ3bmZ3bmZ3bmZ3bmZ3bmZ3bmZ3bmZ3bmZ3bmZ3bmZ3JmVwPXYxX2ludGVybmFsX2dpZl9ieV9pZCZjdD1n/3o7TKMGpxVf7caSBa0/giphy.gif")
        st.stop() # 일반인 접속 시 여기서 코드 실행 중단

    # 여기서부터 기존 코드 시작 (is_dev_mode가 True면 이 아래가 실행됨)
    if is_dev_mode:
        st.sidebar.warning("🛠️ 현재 개발자 테스트 모드로 접속 중입니다.")
        
    st.title("💰 배당팽이 실시간 연배당률 대시보드")

    # [logic.py 호출] 데이터 로드
    df_raw = logic.load_stock_data_from_csv()
    if df_raw.empty: st.stop()
    
    is_admin = False
    
    # 관리자 로그인 로직
    if st.query_params.get("admin", "false").lower() == "true":
        ADMIN_HASH = "c41b0bb392db368a44ce374151794850417b56c9786e3c482f825327c7153182"
        st.info("🔒 관리자 보안 인증이 필요합니다.")
        password_input = st.text_input("관리자 비밀번호 입력", type="password")
        
        if password_input:
            if hashlib.sha256(password_input.encode()).hexdigest() == ADMIN_HASH:
                is_admin = True
                st.success("✅ 인증되었습니다. 관리자 모드를 시작합니다.")
            else:
                st.error("❌ 비밀번호가 틀렸습니다.")
                st.stop()
        else:
            st.stop()

    # [logic.py 호출] 데이터 처리 및 크롤링
    with st.spinner('⚙️ 배당 데이터베이스 엔진 가동 중... 실시간 시세를 연동하고 있습니다.'):
        df = logic.load_and_process_data(df_raw, is_admin=is_admin)

    if is_admin:
        st.sidebar.success("✅ 관리자 모드: 필터링 없이 모든 종목을 표시합니다.")
    
    st.warning("⚠️ **투자 유의사항:** 본 대시보드의 연배당률은 과거 분배금 데이터를 기반으로 계산된 참고용 지표입니다.")

    # ------------------------------------------
    # 섹션 1: 포트폴리오 시뮬레이션
    # ------------------------------------------
    with st.expander("🧮 나만의 배당 포트폴리오 시뮬레이션", expanded=True):
        col1, col2 = st.columns([1, 2])
        total_invest = col1.number_input("💰 총 투자 금액 (만원)", min_value=100, value=3000, step=100) * 10000
        selected = col2.multiselect("📊 종목 선택", df['pure_name'].unique())

        if selected:
            # 해외 ETF 경고
            has_foreign_stock = any(df[df['pure_name'] == s_name].iloc[0]['분류'] == '해외' for s_name in selected)
            if has_foreign_stock:
                st.warning("📢 **잠깐!** 선택하신 종목 중 '해외 상장 ETF'가 포함되어 있습니다. ISA/연금계좌 결과는 참고용으로만 봐주세요.")

            weights = {}
            remaining = 100
            cols_w = st.columns(2)
            all_data = []
            
            for i, stock in enumerate(selected):
                with cols_w[i % 2]:
                    safe_rem = max(0, remaining)
                    if i < len(selected) - 1:
                        val = st.number_input(f"{stock} (%)", min_value=0, max_value=safe_rem, value=min(safe_rem, 100 // len(selected)), step=5, key=f"s_{i}")
                        weights[stock] = val
                        remaining -= val
                        amt = total_invest * (val / 100)
                    else:
                        st.info(f"{stock}: {safe_rem}% 자동 적용")
                        weights[stock] = safe_rem
                        amt = total_invest * (safe_rem / 100)
                    st.caption(f"💰 투자금: **{amt/10000:,.0f}만원**")
                
                stock_match = df[df['pure_name'] == stock]
                if not stock_match.empty:
                    s_row = stock_match.iloc[0]
                    all_data.append({'종목': stock, '비중': weights[stock], '자산유형': s_row['자산유형'], '투자금액_만원': amt / 10000})

            # 결과 계산
            total_y_div = sum([(total_invest * (weights[n]/100) * (df[df['pure_name']==n].iloc[0]['연배당률']/100)) for n in selected])
            total_m = total_y_div / 12
            avg_y = sum([(df[df['pure_name']==n].iloc[0]['연배당률'] * (weights[n]/100)) for n in selected])

            # 섹션 2: 결과 표시
            st.markdown("### 🎯 포트폴리오 결과")
            st.metric("📈 가중 평균 연배당률", f"{avg_y:.2f}%")
            r1, r2, r3 = st.columns(3)
            r1.metric("월 수령액 (세후)", f"{total_m * 0.846:,.0f}원", delta="-15.4%", delta_color="inverse")
            r2.metric("월 수령액 (ISA/세전)", f"{total_m:,.0f}원", delta="100%", delta_color="normal")
            with r3:
                st.markdown(f"""<div style="background-color: #d4edda; color: #155724; padding: 15px; border-radius: 8px; border: 1px solid #c3e6cb; height: 100%; display: flex; flex-direction: column; justify-content: center;"><div style="font-weight: bold; font-size: 1.05em;">✅ 일반 계좌 대비 월 {total_m * 0.154:,.0f}원 이득!</div><div style="color: #6c757d; font-size: 0.8em; margin-top: 5px;">(비과세 및 과세이연 단순 가정입니다)</div></div>""", unsafe_allow_html=True)

            st.write("")
            c_data = pd.DataFrame({'계좌 종류': ['일반 계좌', 'ISA/연금계좌'], '월 수령액': [total_m * 0.846, total_m]})
            chart_compare = alt.Chart(c_data).mark_bar(cornerRadiusTopLeft=10, cornerRadiusTopRight=10).encode(x=alt.X('계좌 종류', sort=None, axis=alt.Axis(labelAngle=0, title=None)), y=alt.Y('월 수령액', title=None), color=alt.Color('계좌 종류', scale=alt.Scale(domain=['일반 계좌', 'ISA/연금계좌'], range=['#95a5a6', '#f1c40f']), legend=None), tooltip=[alt.Tooltip('계좌 종류'), alt.Tooltip('월 수령액', format=',.0f')]).properties(height=220)
            st.altair_chart(chart_compare, use_container_width=True)

            if total_y_div > 20000000:
                st.warning(f"🚨 **주의:** 연간 예상 배당금이 **{total_y_div/10000:,.0f}만원**입니다. 금융소득종합과세 대상에 해당될 수 있습니다.")

            # 섹션 3: 상세 분석
            df_ana = pd.DataFrame(all_data)
            if not df_ana.empty:
                st.write("")
                tab_analysis, tab_simulation = st.tabs(["💎 자산 구성 분석", "💰 10년 뒤 자산 미리보기"])
                
                with tab_analysis:
                    chart_col, table_col = st.columns([1.2, 1])
                    def classify_currency(row):
                        try:
                            target = df[df['pure_name'] == row['종목']].iloc[0]
                            hwan = str(target.get('환구분', ''))
                            bunryu = str(target.get('분류', ''))
                            if any(k in hwan for k in ["환노출", "달러", "직투"]) or bunryu == "해외": return "🇺🇸 달러 자산"
                        except: pass
                        if "(해외)" in row['종목']: return "🇺🇸 달러 자산"
                        return "🇰🇷 원화 자산"
                    
                    df_ana['통화'] = df_ana.apply(classify_currency, axis=1)
                    usd_ratio = df_ana[df_ana['통화'] == "🇺🇸 달러 자산"]['비중'].sum()
                    asset_sum = df_ana.groupby('자산유형').agg({'비중': 'sum', '투자금액_만원': 'sum', '종목': lambda x: ', '.join(x)}).reset_index()

                    with chart_col:
                        st.write("💎 **자산 유형 비중**")
                        donut = alt.Chart(asset_sum).mark_arc(innerRadius=60).encode(theta=alt.Theta("비중:Q"), color=alt.Color("자산유형:N", legend=alt.Legend(orient='bottom', title=None)), tooltip=[alt.Tooltip("자산유형"), alt.Tooltip("비중", format=".1f"), alt.Tooltip("투자금액_만원", format=",d"), alt.Tooltip("종목")]).properties(height=320)
                        st.altair_chart(donut, use_container_width=True)
                    with table_col:
                        st.write("📋 **유형별 요약**")
                        st.dataframe(asset_sum.sort_values('비중', ascending=False), column_config={"비중": st.column_config.NumberColumn(format="%d%%"), "투자금액_만원": st.column_config.NumberColumn("투자금(만원)", format="%d"), "종목": st.column_config.TextColumn("포함 종목", width="large")}, hide_index=True, use_container_width=True)
                        st.divider()
                        st.markdown(f"**🌐 달러 자산 노출도: `{usd_ratio:.1f}%`**")
                        st.progress(usd_ratio / 100)
                        if usd_ratio >= 50: st.caption("💡 포트폴리오의 절반 이상이 환율 변동에 영향을 받습니다.")
                        else: st.caption("💡 원화 자산 중심의 구성입니다.")

                # [탭 2] 적립식 시뮬레이션
                with tab_simulation:
                    start_money = total_invest
                    is_over_100m = start_money > 100000000
                    st.info(f"📊 상단에서 설정한 **초기 자산 {start_money/10000:,.0f}만원**으로 시뮬레이션을 시작합니다.")
                    c1, c2 = st.columns([1.5, 1])
                    with c1:
                        if is_over_100m:
                            is_isa_mode = st.toggle("🛡️ ISA 계좌 불가 (한도 1억 초과)", value=False, disabled=True)
                            st.caption("🚫 초기 투자금이 1억원을 초과하여 일반 계좌로만 진행됩니다.")
                        else:
                            is_isa_mode = st.toggle("🛡️ ISA (절세) 계좌로 모으기", value=True)
                            if is_isa_mode: st.caption("💡 **ISA 모드:** 비과세 + 과세이연 효과")
                            else: st.caption("💡 **일반 모드:** 배당소득세(15.4%) 납부 후 재투자")
                    with c2:
                        years_sim = st.select_slider("⏳ 투자 기간", options=[3, 5, 10, 15, 20, 30], value=5, format_func=lambda x: f"{x}년")
                    
                    reinvest_ratio = 100; isa_exempt = 0
                    if is_isa_mode:
                        isa_type = st.radio("ISA 유형", ["일반형 (비과세 200만)", "서민형 (비과세 400만)"], horizontal=True, label_visibility="collapsed")
                        isa_exempt = 400 if "서민형" in isa_type else 200
                        if start_money > 20000000: st.warning(f"⚠️ 기존에 선택한 {start_money/10000:,.0f}만원은 ISA 총 한도(1억)에서 차감됩니다.")
                    else:
                        if not is_over_100m:
                            st.caption("설정한 비율만큼만 재투자하고 나머지는 생활비로 씁니다.")
                            reinvest_ratio = st.slider("💰 재투자 비율 (%)", 0, 100, 100, step=10)
                    st.markdown("---")
                    monthly_input = st.number_input("➕ 매월 추가 적립 (만원)", min_value=0, max_value=3000, value=150, step=10) * 10000
                    monthly_add = monthly_input
                    if is_isa_mode and monthly_add > 1666666:
                        st.warning("⚠️ **ISA 연간 한도 제한:** 월 납입금이 **약 166만원(연 2,000만원)**으로 자동 조정되어 계산됩니다.")
                        monthly_add = 1666666 
                    
                    months_sim = years_sim * 12
                    monthly_yld = avg_y / 100 / 12
                    current_bal = start_money; total_principal = start_money
                    ISA_YEARLY_CAP = 20000000; ISA_TOTAL_CAP = 100000000
                    sim_data = [{"년차": 0, "자산총액": current_bal/10000, "총원금": total_principal/10000, "실제월배당": 0}]
                    yearly_contribution = 0; year_tracker = 0
                    total_tax_paid_general = 0

                    for m in range(1, months_sim + 1):
                        if m // 12 > year_tracker: yearly_contribution = 0; year_tracker = m // 12
                        actual_add = monthly_add
                        if is_isa_mode:
                            remaining_yearly = max(0, ISA_YEARLY_CAP - yearly_contribution)
                            remaining_total = max(0, ISA_TOTAL_CAP - total_principal)
                            actual_add = min(monthly_add, remaining_yearly, remaining_total)
                        current_bal += actual_add; total_principal += actual_add; yearly_contribution += actual_add
                        div_earned = current_bal * monthly_yld
                        if is_isa_mode: reinvest = div_earned
                        else:
                            this_tax = div_earned * 0.154
                            total_tax_paid_general += this_tax
                            after_tax = div_earned - this_tax
                            reinvest = after_tax * (reinvest_ratio / 100)
                        current_bal += reinvest
                        sim_data.append({"년차": m / 12, "자산총액": current_bal / 10000, "총원금": total_principal / 10000, "실제월배당": div_earned})
                    
                    df_sim_chart = pd.DataFrame(sim_data)
                    base = alt.Chart(df_sim_chart).encode(x=alt.X('년차:Q', title='경과 기간 (년)'))
                    area = base.mark_area(opacity=0.3, color='#0068c9').encode(y=alt.Y('자산총액:Q', title='자산 (만원)'))
                    line = base.mark_line(color='#ff9f43', strokeDash=[5,5]).encode(y='총원금:Q')
                    st.altair_chart((area + line).properties(height=280), use_container_width=True)

                    final_row = df_sim_chart.iloc[-1]
                    final_asset = final_row['자산총액'] * 10000
                    final_principal = final_row['총원금'] * 10000
                    profit = final_asset - final_principal
                    monthly_div_final = final_row['실제월배당']

                    if is_isa_mode:
                        taxable = max(0, profit - (isa_exempt * 10000))
                        tax = taxable * 0.099
                        real_money = final_asset - tax
                        tax_msg = f"예상 세금 {tax/10000:,.0f}만원 (9.9% 분리과세)"
                        monthly_pocket = monthly_div_final 
                    else:
                        real_money = final_asset
                        tax_msg = f"기납부 세금 {total_tax_paid_general/10000:,.0f}만원 (15.4% 원천징수)"
                        monthly_pocket = monthly_div_final * 0.846

                    import random
                    analogy_items = [{"name": "스타벅스", "unit": "잔", "price": 4500, "emoji": "☕"}, {"name": "치킨", "unit": "마리", "price": 23000, "emoji": "🍗"}, {"name": "제주도 항공권", "unit": "장", "price": 60000, "emoji": "✈️"}, {"name": "특급호텔 숙박", "unit": "박", "price": 200000, "emoji": "🏨"}]
                    selected_item = random.choice(analogy_items)
                    item_count = int(monthly_pocket // selected_item['price'])

                    st.markdown(f"""<div style="background-color: #e7f3ff; border: 1.5px solid #d0e8ff; border-radius: 16px; padding: 25px; text-align: center; box-shadow: 0 4px 10px rgba(0,104,201,0.05);"><p style="color: #666; font-size: 0.95em; margin: 0 0 8px 0;">{years_sim}년 뒤 모이는 돈 (세후)</p><h2 style="color: #0068c9; font-size: 2.2em; margin: 0; font-weight: 800; line-height: 1.2;">약 {real_money/10000:,.0f}만원</h2><p style="color: #777; font-size: 0.9em; margin: 8px 0 0 0;">(투자원금 {final_principal/10000:,.0f}만원 / {tax_msg})</p><div style="height: 1px; background-color: #d0e8ff; margin: 25px auto; width: 85%;"></div><p style="color: #0068c9; font-weight: bold; font-size: 1.1em; margin: 0 0 12px 0;">📅 월 예상 배당금: {monthly_pocket/10000:,.1f}만원 (실수령)</p><div style="background-color: rgba(255,255,255,0.5); padding: 15px; border-radius: 12px; display: inline-block; min-width: 80%;"><p style="color: #333; font-size: 1.1em; margin: 0; line-height: 1.6;">매달 <b>{selected_item['emoji']} {selected_item['name']} {item_count:,}{selected_item['unit']}</b><br>마음껏 즐기기 가능! 😋</p></div></div>""", unsafe_allow_html=True)
                    
                    annual_div_income = monthly_div_final * 12
                    if annual_div_income > 20000000: st.warning(f"🚨 **주의:** {years_sim}년 뒤 연간 배당금이 2,000만원을 초과하여 금융소득종합과세 대상이 될 수 있습니다.")
                    st.error("""**⚠️ 시뮬레이션 활용 시 유의사항**\n1. 본 결과는 주가·환율 변동과 수수료 등을 제외하고, 현재 배당률로만 계산한 결과입니다.\n2. ISA 계좌의 비과세 한도 및 세율은 세법 개정에 따라 달라질 수 있습니다.\n3. 실제 배당금은 운용사의 공시 및 환율 상황에 따라 매월 달라질 수 있습니다.""")
                     
                   

    # ------------------------------------------
    # 섹션 4: 전체 데이터 테이블 출력
    # ------------------------------------------
    st.info("💡 **이동 안내:** '코드' 클릭 시 블로그 분석글로, '🔗정보' 클릭 시 네이버/야후 금융 정보로 이동합니다. (**⭐ 표시는 상장 1년 미만 종목입니다.**)")
    
    tab_all, tab_kor, tab_usa = st.tabs(["🌎 전체", "🇰🇷 국내", "🇺🇸 해외"])

    with tab_all:
        # [ui.py 호출] 테이블 렌더링
        ui.render_custom_table(df)
    with tab_kor:
        ui.render_custom_table(df[df['분류'] == '국내'])
    with tab_usa:
        ui.render_custom_table(df[df['분류'] == '해외'])

    # ------------------------------------------
    # 하단 푸터 및 방문자 추적
    # ------------------------------------------
    st.divider()
    st.caption("© 2025 **배당팽이** | 실시간 데이터 기반 배당 대시보드")
    st.caption("First Released: 2025.12.31 | [📝 배당팽이의 배당 투자 일지 구경가기](https://blog.naver.com/dividenpange)")

    @st.fragment
    def track_visitors():
        if 'visited' not in st.session_state: st.session_state.visited = False
        if not st.session_state.visited:
            try:
                is_admin = st.query_params.get("admin", "false").lower() == "true"
                if not is_admin:
                    from streamlit.web.server.websocket_headers import _get_websocket_headers
                    headers = _get_websocket_headers()
                    referer = headers.get("Referer", "Direct")
                    source_tag = st.query_params.get("source", referer)
                    supabase.table("visit_logs").insert({"referer": source_tag}).execute()
                    response = supabase.table("visit_counts").select("count").eq("id", 1).execute()
                    if response.data:
                        new_count = response.data[0]['count'] + 1
                        supabase.table("visit_counts").update({"count": new_count}).eq("id", 1).execute()
                        st.session_state.display_count = new_count
                else:
                    response = supabase.table("visit_counts").select("count").eq("id", 1).execute()
                    st.session_state.display_count = response.data[0]['count'] if response.data else "Admin"
                st.session_state.visited = True
            except Exception:
                st.session_state.display_count = "확인 중"; st.session_state.visited = True

        display_num = st.session_state.get('display_count', '집계 중')
        st.write("") 
        st.markdown(f"""<div style="display: flex; justify-content: center; align-items: center; gap: 20px; padding: 25px; background: #f8f9fa; border-radius: 15px; border: 1px solid #eee; box-shadow: 0 2px 4px rgba(0,0,0,0.05); margin-bottom: 10px;"><div style="text-align: center;"><p style="margin: 0; font-size: 0.9em; color: #666; font-weight: 500;">누적 방문자</p><p style="margin: 0; font-size: 2.2em; font-weight: 800; color: #0068c9;">{display_num}</p></div><div style="width: 1px; height: 50px; background: #ddd;"></div><div style="text-align: left;"><p style="margin: 2px 0; font-size: 0.85em; color: #555;">🚀 <b>실시간 데이터</b> 연동 중</p><p style="margin: 2px 0; font-size: 0.85em; color: #555;">🛡️ <b>보안 비밀번호</b> 적용 완료</p></div></div>""", unsafe_allow_html=True)

    track_visitors()
    
    if st.query_params.get("admin", "false").lower() == "true":
        with st.expander("🛠️ 관리자 전용: 최근 유입 로그 (최근 5건)", expanded=False):
            try:
                recent_logs = supabase.table("visit_logs").select("referer, created_at").order("created_at", desc=True).limit(5).execute()
                if recent_logs.data:
                    log_df = pd.DataFrame(recent_logs.data)
                    log_df['created_at'] = pd.to_datetime(log_df['created_at']).dt.tz_convert('Asia/Seoul').dt.strftime('%Y-%m-%d %H:%M:%S')
                    st.table(log_df)
                else: st.write("아직 기록된 유입이 없습니다.")
            except Exception as e: st.error(f"로그 로드 실패: {e}")

if __name__ == "__main__":
    main()
