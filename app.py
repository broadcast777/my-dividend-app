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

try:
    URL = st.secrets["SUPABASE_URL"]
    KEY = st.secrets["SUPABASE_KEY"]
    supabase = create_client(URL, KEY)
except:
    # 로컬 테스트 등 시크릿이 없을 경우를 대비해 예외 처리
    supabase = None

# ==========================================
# [수정] 로그인 기능 함수 (구글 + 카카오)
# ==========================================
def show_login_button():
    # supabase 클라이언트가 생성되지 않았으면 중단
    if not supabase: return None 
    
    # 1. 현재 세션(로그인 여부) 확인
    session = supabase.auth.get_session()
    
    if session:
        # 로그인 성공 상태
        user_email = session.user.email
        nickname = user_email.split("@")[0]
        
        st.sidebar.markdown("---")
        st.sidebar.success(f"👋 반가워요! **{nickname}**님")
        
        # 로그아웃 버튼
        if st.sidebar.button("로그아웃", key="logout_btn"):
            supabase.auth.sign_out()
            st.rerun() # 화면 새로고침
        return session.user
        
    else:
        # 로그인 안 된 상태
        st.sidebar.markdown("---")
        st.sidebar.info("💾 포트폴리오 저장을 위해 로그인")
        
        # 버튼을 가로로 2개 배치 (왼쪽: 구글, 오른쪽: 카카오)
        col1, col2 = st.sidebar.columns(2)
        
        # 1. 구글 로그인 설정
        with col1:
            res_google = supabase.auth.sign_in_with_oauth({
                "provider": "google",
                "options": {
                    "redirect_to": "https://dividend-pange.streamlit.app"
                }
            })
            if res_google.url:
                st.link_button("G 구글", res_google.url, type="primary", use_container_width=True)

        # 2. 카카오 로그인 설정
        with col2:
            res_kakao = supabase.auth.sign_in_with_oauth({
                "provider": "kakao",
                "options": {
                    "redirect_to": "https://dividend-pange.streamlit.app"
                }
            })
            if res_kakao.url:
                # 카카오 버튼 (이모지로 포인트 줌)
                st.link_button("💬 카카오", res_kakao.url, type="secondary", use_container_width=True)
            
        # 보안 문구 추가
        st.sidebar.caption("🔒 본 서비스는 구글/카카오 및 Supabase의 보안 인증을 통해 안전하게 로그인됩니다.")
        
        return None
# ==========================================
# [2] 메인 애플리케이션
# ==========================================
def main():
    # 🔥 [점검 모드 스위치] 작업할 때 True로 바꾸세요!
    # True: 일반 사용자에게는 '점검 중' 화면이 뜸 (관리자는 접속 가능)
    # False: 정상 서비스 운영
    MAINTENANCE_MODE = False

    # ---------------------------------------------------------
    # [1] 관리자 인증 (사이드바)
    # ---------------------------------------------------------
    is_admin = False
    if st.query_params.get("admin", "false").lower() == "true":
        
        # 기존 비밀번호의 해시값 
        ADMIN_HASH = "c41b0bb392db368a44ce374151794850417b56c9786e3c482f825327c7153182"
        
        with st.sidebar:
            st.header("🐌 메뉴 / 관리")
            
            # 비밀번호 입력창
            password_input = st.text_input("🔐 관리자 접속", type="password", placeholder="비밀번호 입력")
            
            # 비밀번호 검증
            if password_input:
                if hashlib.sha256(password_input.encode()).hexdigest() == ADMIN_HASH:
                    is_admin = True
                    st.success("관리자 모드 ON 🚀")
                else:
                    st.error("비밀번호 불일치")

    
    # ---------------------------------------------------------
    # [추가] 일반 사용자 로그인 버튼 (사이드바 표시)
    # ---------------------------------------------------------
    current_user = show_login_button()
   

    # ---------------------------------------------------------
    # [2] 점검 모드 가동 로직 (관리자가 아니면 여기서 멈춤)
    # ---------------------------------------------------------
    if MAINTENANCE_MODE and not is_admin:
        st.title("🚧 시스템 정기 점검 중")
        st.subheader("현재 서비스 기능 개선 및 데이터 안정화 작업 중입니다.")
        st.info("관리자(개발자)는 사이드바에 비밀번호를 입력하면 접속 가능합니다.")
        st.markdown("---")
        st.write("잠시 후 다시 접속해 주세요! 🙇‍♂️")
        
        # 귀여운 공사 중 움짤 (선택 사항)
        st.image("https://media.giphy.com/media/v1.Y2lkPTc5MGI3NjExNHJueGZ3bmZ3bmZ3bmZ3bmZ3bmZ3bmZ3bmZ3bmZ3bmZ3bmZ3JmVwPXYxX2ludGVybmFsX2dpZl9ieV9pZCZjdD1n/3o7TKMGpxVf7caSBa0/giphy.gif", width=400)
        
        st.stop() # 🛑 여기서 코드 실행을 강제로 중단시킴 (아래 내용 안 보임)
    
    # ---------------------------------------------------------
    # 메인 타이틀
    # ---------------------------------------------------------
    if is_admin:
        st.title("💰 배당팽이 대시보드 (관리자 모드)")
    else:
        st.title("💰 배당팽이 월배당 계산기")

    # [logic.py 호출] 데이터 로드
    df_raw = logic.load_stock_data_from_csv()
    if df_raw.empty: st.stop()
    
    # ---------------------------------------------------------
    # [관리자 전용] 배당금 갱신 도구 (인증 성공 시에만 보임)
    # ---------------------------------------------------------
    if is_admin:
        with st.sidebar:
            st.markdown("---")
            st.subheader("🛠️ 배당금 갱신 도구")
            
            target_stock = st.selectbox("갱신할 종목 선택", df_raw['종목명'].unique())
            
            if target_stock:
                row = df_raw[df_raw['종목명'] == target_stock].iloc[0]
                cur_hist = row.get('배당기록', "")
                cur_div = row.get('연배당금', 0)
                cur_months = int(row.get('신규상장개월수', 0))

                st.caption(f"💰 연배당금: {cur_div}원")
                if cur_months > 0:
                    st.warning(f"⭐ 신규 상장 {cur_months}개월차")
                
                new_div = st.number_input("이번 달 확정 배당금", value=0, step=10)
                
                if st.button("계산 실행"):
                    new_total, new_hist = logic.update_dividend_rolling(cur_hist, new_div)
                    
                    st.success("완료! CSV에 복사하세요.")
                    st.code(new_hist, language="text")
                    
                    c1, c2 = st.columns(2)
                    c1.metric("수정 연배당금", new_total, delta=new_total-int(cur_div))
                    
                    if cur_months > 0:
                        c2.metric("개월수 수정필요", cur_months + 1, "CSV 수정!")
                        st.error(f"⚠️ 신규 종목! '신규상장개월수'를 **{cur_months + 1}**로 꼭 고치세요.")
                    else:
                        c2.metric("신규상장개월수", 0, "유지")

    # [logic.py 호출] 데이터 처리 (관리자면 필터링 해제)
    with st.spinner('⚙️ 배당 데이터베이스 엔진 가동 중...'):
        df = logic.load_and_process_data(df_raw, is_admin=is_admin)

    if is_admin:
        st.sidebar.success("✅ 관리자 모드 작동 중")
    
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

            # =========================================================
            # [추가된 코드] 포트폴리오 저장 버튼 (여기서부터 복사)
            # =========================================================
            st.write("") # 여백
            if st.button("💾 내 포트폴리오 저장하기", type="primary", use_container_width=True):
                # 1. 로그인 체크 (상단에서 정의한 current_user 활용)
                if not current_user:
                    st.toast("⚠️ 로그인이 필요한 기능입니다. 사이드바를 확인해주세요!")
                    st.warning("로그인을 하셔야 '나만의 포트폴리오'를 저장할 수 있습니다.")
                else:
                    try:
                        # 2. 저장할 데이터 포장 (JSON)
                        # 나중에 불러오기 쉽게 '구성(composition)' 위주로 저장합니다.
                        save_data = {
                            "total_money": total_invest,       # 총 투자금
                            "composition": weights,            # {종목명: 비중(%)} 딕셔너리
                            "summary": {                       # 요약 정보 (표시용)
                                "monthly_income": total_m,     # 월 수령액
                                "yield": avg_y                 # 평균 배당률
                            }
                        }
                        
                        # 3. Supabase로 발사! 🚀
                        supabase.table("portfolios").insert({
                            "user_id": current_user.id,
                            "user_email": current_user.email,
                            "ticker_data": save_data  # 위에서 만든 JSON 데이터
                        }).execute()
                        
                        st.success("짐 싸기 완료! 포트폴리오가 안전하게 저장되었습니다. 🧳")
                        st.balloons() # 축하 풍선 🎈
                        
                    except Exception as e:
                        st.error(f"저장 중 오류가 발생했습니다: {e}")
            # =========================================================
            # [끝] 여기까지 복사해서 붙여넣으세요
            # =========================================================

            if total_y_div > 20000000:
                st.warning(f"🚨 **주의:** 연간 예상 배당금이 **{total_y_div/10000:,.0f}만원**입니다. 금융소득종합과세 대상에 해당될 수 있습니다.")

            # 섹션 3: 상세 분석
            df_ana = pd.DataFrame(all_data)
            if not df_ana.empty:
                st.write("")
                tab_analysis, tab_simulation, tab_goal = st.tabs(["💎 자산 구성 분석", "💰 10년 뒤 자산 미리보기", "🎯 목표 배당 달성"])
                
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

                    # [탭 1 하단 추가] 경고 및 유의사항 (일관성 유지)
                    st.write("")
                    if total_y_div > 20000000:
                        st.warning(f"🚨 **주의:** 현재 구성하신 포트폴리오의 연간 배당금이 {total_y_div/10000:,.0f}만원을 초과하여 금융소득종합과세 대상이 될 수 있습니다.")

                    st.error("""**⚠️ 포트폴리오 분석 시 유의사항**
1. 과거의 데이터를 기반으로 한 단순 결과값이며,실제 투자 수익을 보장하지않습니다.
2. '달러 자산' 비율 실제 환노출 여부와 다를 수 있습니다 투자 전 확인이 필요합니다.
3. 실제 배당금 지급일과 금액은 운용사의 사정에 따라 변경될 수 있습니다.""")

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
                        apply_inflation = st.toggle("📉 물가상승률(2.5%) 반영", value=False)
                    
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

                    inflation_msg_money = ""
                    inflation_msg_monthly = ""
                    
                    if apply_inflation:
                        discount_rate = (1.025) ** years_sim 
                        pv_money = real_money / discount_rate
                        pv_monthly = monthly_pocket / discount_rate
                        inflation_msg_money = f"<br><span style='font-size:0.6em; color:#ff6b6b;'>(현재가치: 약 {pv_money/10000:,.0f}만원)</span>"
                        inflation_msg_monthly = f"<span style='font-size:0.7em; color:#ff6b6b;'>(현재가치: {pv_monthly/10000:,.1f}만원)</span>"

                    import random
                    analogy_items = [{"name": "스타벅스", "unit": "잔", "price": 4500, "emoji": "☕"}, {"name": "치킨", "unit": "마리", "price": 23000, "emoji": "🍗"}, {"name": "제주도 항공권", "unit": "장", "price": 60000, "emoji": "✈️"}, {"name": "특급호텔 숙박", "unit": "박", "price": 200000, "emoji": "🏨"}]
                    selected_item = random.choice(analogy_items)
                    item_count = int(monthly_pocket // selected_item['price'])

                    st.markdown(f"""<div style="background-color: #e7f3ff; border: 1.5px solid #d0e8ff; border-radius: 16px; padding: 25px; text-align: center; box-shadow: 0 4px 10px rgba(0,104,201,0.05);"><p style="color: #666; font-size: 0.95em; margin: 0 0 8px 0;">{years_sim}년 뒤 모이는 돈 (세후)</p><h2 style="color: #0068c9; font-size: 2.2em; margin: 0; font-weight: 800; line-height: 1.2;">약 {real_money/10000:,.0f}만원{inflation_msg_money}</h2><p style="color: #777; font-size: 0.9em; margin: 8px 0 0 0;">(투자원금 {final_principal/10000:,.0f}만원 / {tax_msg})</p><div style="height: 1px; background-color: #d0e8ff; margin: 25px auto; width: 85%;"></div><p style="color: #0068c9; font-weight: bold; font-size: 1.1em; margin: 0 0 12px 0;">📅 월 예상 배당금: {monthly_pocket/10000:,.1f}만원 {inflation_msg_monthly}</p><div style="background-color: rgba(255,255,255,0.5); padding: 15px; border-radius: 12px; display: inline-block; min-width: 80%;"><p style="color: #333; font-size: 1.1em; margin: 0; line-height: 1.6;">매달 <b>{selected_item['emoji']} {selected_item['name']} {item_count:,}{selected_item['unit']}</b><br>마음껏 즐기기 가능! 😋</p></div></div>""", unsafe_allow_html=True)

                    # [탭 2 전용] 연간 배당금 계산 및 경고
                    annual_div_income = monthly_div_final * 12
                    
                    if annual_div_income > 20000000:
                        st.warning(f"🚨 **주의:** {years_sim}년 뒤 연간 배당금이 2,000만원을 초과하여 금융소득종합과세 대상이 될 수 있습니다.")
                    
                    st.error("""**⚠️ 시뮬레이션 활용 시 유의사항**
1. 본 결과는 주가·환율 변동과 수수료 등을 제외하고, 현재 배당률로만 계산한 결과입니다.
2. ISA 계좌의 비과세 한도 및 세율은 세법 개정에 따라 달라질 수 있습니다.
3. 과거의 데이터를 기반으로 한 단순 시뮬레이션이며, 실제 투자 수익을 보장하지 않습니다.""")

                # [탭 3] 목표 배당 달성 (역산기)
                with tab_goal:
                    st.subheader("🎯 목표 배당금 역산기 (은퇴 시뮬레이터)")
                    st.write("원하는 월 배당금을 받기 위해 필요한 자산과 기간을 계산합니다.")
                    
                    col_g1, col_g2 = st.columns(2)
                    with col_g1:
                        target_monthly_goal = st.number_input("목표 월 배당금 (만원, 세후)", min_value=10, value=300, step=10) * 10000
                        use_start_money = st.checkbox("위에서 설정한 초기 자산을 포함하여 계산", value=True)
                        start_bal_goal = total_invest if use_start_money else 0
                        
                    with col_g2:
                        monthly_add_goal = st.number_input("매월 추가 적립 가능 금액 (만원)", min_value=0, value=150, step=10) * 10000
                        apply_inflation_goal = st.toggle("📈 목표치에 물가상승률 반영", value=False, help="미래의 300만원이 현재의 얼마 가치인지 고려하여 목표를 상향 조정합니다.")

                    tax_factor = 0.846 
                    required_asset_goal = (target_monthly_goal / tax_factor) / (avg_y / 100) * 12
                    
                    st.markdown("---")
                    
                    c_res1, c_res2 = st.columns(2)
                    with c_res1:
                        st.metric("목표 달성 필요 자산", f"{required_asset_goal/100000000:,.2f} 억원")
                        st.caption(f"평균 배당률 {avg_y:.2f}% 및 세금 15.4% 적용 시")
                    
                    with c_res2:
                        current_bal_goal = start_bal_goal
                        months_passed = 0
                        max_months = 600
                        
                        while current_bal_goal < required_asset_goal and months_passed < max_months:
                            div_reinvest = current_bal_goal * (avg_y / 100 / 12) * tax_factor
                            current_bal_goal += monthly_add_goal + div_reinvest
                            months_passed += 1
                        
                        if months_passed >= max_months:
                            st.error("⚠️ 현재 적립액으로는 50년 내 달성이 어렵습니다. 적립금을 늘려보세요!")
                        else:
                            years_goal = months_passed // 12
                            remain_months_goal = months_passed % 12
                            st.metric("목표 달성까지 소요 기간", f"{years_goal}년 {remain_months_goal}개월")
                    
                    if apply_inflation_goal:
                        discount_factor = (1.025) ** (months_passed / 12)
                        real_value = target_monthly_goal / discount_factor
                        st.warning(f"⚠️ **물가 반영 시:** {years_goal}년 뒤 {target_monthly_goal/10000:,.0f}만원의 실질 가치는 현재 기준 **약 {real_value/10000:,.1f}만원**입니다.")
                        
                    st.info(f"💡 **팁:** 매달 **20만원**을 더 적립하면 달성 기간이 어떻게 변하는지 확인해 보세요!")
                    
                    # [탭 3 전용] 목표 금액 기준 연간 배당금 계산
                    target_annual_income = target_monthly_goal * 12

                    if target_annual_income > 20000000:
                        st.warning(f"🚨 **현실적 조언:** 설정하신 목표(월 {target_monthly_goal/10000:,.0f}만원) 달성 시, 연 배당소득이 2,000만원을 넘어 **금융종합과세 대상**이 됩니다.")

                    st.error("""**⚠️ 시뮬레이션 활용 시 유의사항**
1. 본 결과는 주가·환율 변동과 수수료 등을 제외하고, 현재 배당률로만 계산한 결과입니다.
2. 실제 배당금은 운용사의 공시 및 환율 상황에 따라 매월 달라질 수 있습니다.
3. 과거의 데이터를 기반으로 한 단순 시뮬레이션이며, 실제 투자 수익을 보장하지 않습니다.""")
                     
    # ------------------------------------------
    # 섹션 4: 전체 데이터 테이블 출력
    # ------------------------------------------
    st.info("💡 **이동 안내:** '코드' 클릭 시 블로그 분석글로, '🔗정보' 클릭 시 네이버/야후 금융 정보로 이동합니다. (**⭐ 표시는 상장 1년 미만 종목입니다.**)")
    
    tab_all, tab_kor, tab_usa = st.tabs(["🌎 전체", "🇰🇷 국내", "🇺🇸 해외"])

    with tab_all:
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
                # [수정] admin 쿼리가 없어야 방문자 카운팅
                if st.query_params.get("admin", "false").lower() != "true":
                    if supabase:
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
                        st.session_state.display_count = "Local"
                else:
                    if supabase:
                        response = supabase.table("visit_counts").select("count").eq("id", 1).execute()
                        st.session_state.display_count = response.data[0]['count'] if response.data else "Admin"
                    else:
                        st.session_state.display_count = "Admin"
                st.session_state.visited = True
            except Exception:
                st.session_state.display_count = "확인 중"; st.session_state.visited = True

        display_num = st.session_state.get('display_count', '집계 중')
        st.write("") 
        st.markdown(f"""<div style="display: flex; justify-content: center; align-items: center; gap: 20px; padding: 25px; background: #f8f9fa; border-radius: 15px; border: 1px solid #eee; box-shadow: 0 2px 4px rgba(0,0,0,0.05); margin-bottom: 10px;"><div style="text-align: center;"><p style="margin: 0; font-size: 0.9em; color: #666; font-weight: 500;">누적 방문자</p><p style="margin: 0; font-size: 2.2em; font-weight: 800; color: #0068c9;">{display_num}</p></div><div style="width: 1px; height: 50px; background: #ddd;"></div><div style="text-align: left;"><p style="margin: 2px 0; font-size: 0.85em; color: #555;">🚀 <b>실시간 데이터</b> 연동 중</p><p style="margin: 2px 0; font-size: 0.85em; color: #555;">🛡️ <b>보안 비밀번호</b> 적용 완료</p></div></div>""", unsafe_allow_html=True)

    track_visitors()
    
    if is_admin and supabase:
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
