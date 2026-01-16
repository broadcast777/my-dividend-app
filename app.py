import streamlit as st
import pandas as pd
import altair as alt
import hashlib
import time
import random
from streamlit.runtime.scriptrunner import get_script_run_ctx
# [필수] 날짜 및 URL 라이브러리
from datetime import datetime, timedelta
import urllib.parse

# [모듈화] 분리한 파일들을 불러옵니다
import logic 
import ui
import db
import recommendation
# ==========================================
# [1] 기본 설정
# ==========================================
st.set_page_config(page_title="배당팽이 대시보드", layout="wide")

# ---------------------------------------------------------
# 세션 상태 변수 초기화
# ---------------------------------------------------------
for key in ["is_logged_in", "user_info", "code_processed"]:
    if key not in st.session_state:
        st.session_state[key] = False if key != "user_info" else None

if "ai_modal_open" not in st.session_state:
    st.session_state.ai_modal_open = False



# ---------------------------------------------------------
# Supabase 연결
# ---------------------------------------------------------
supabase = db.init_supabase()

# ==========================================
# [2] 인증 상태 체크 (자동 복구 로직 포함)
# ==========================================
def check_auth_status():
    if not supabase: return

    # 1. 이미 로그인된 상태인지 확인
    try:
        session = supabase.auth.get_session()
        if session and session.user:
            st.session_state.is_logged_in = True
            st.session_state.user_info = session.user
            if "code" in st.query_params or "old_id" in st.query_params:
                st.query_params.clear()
            return 
    except Exception:
        pass

    # 2. 로그인 콜백 처리
    query_params = st.query_params
    if "code" in query_params and not st.session_state.get("code_processed", False):
        st.session_state.code_processed = True
        
        try:
            auth_code = query_params["code"]
            auth_response = supabase.auth.exchange_code_for_session({"auth_code": auth_code})
            session = auth_response.session
            
            if session and session.user:
                st.session_state.is_logged_in = True
                st.session_state.user_info = session.user
            
            st.query_params.clear()
            st.success("✅ 로그인되었습니다!")
            st.rerun()
            
        except Exception as e:
            # 오류 자동 복구 (verifier 오류 시 리셋)
            err_msg = str(e).lower()
            if "verifier" in err_msg or "non-empty" in err_msg:
                st.warning("🔄 보안 토큰 갱신 중... 잠시만 기다려주세요.")
                st.query_params.clear()
                time.sleep(1.0)
                st.rerun()
            else:
                st.error(f"🔴 인증 오류: {e}")
                st.query_params.clear()

check_auth_status()

# ==========================================
# [3] 로그인 UI 함수 (사이드바용)
# ==========================================
def render_login_ui():
    if not supabase: return
    is_logged_in = st.session_state.get("is_logged_in", False)
    user_info = st.session_state.get("user_info", None)
    
    if is_logged_in and user_info:
        email = user_info.email if user_info.email else "User"
        nickname = email.split("@")[0]
        with st.sidebar:
            st.markdown("---")
            st.success(f"👋 반가워요! **{nickname}**님")
            if st.button("🚪 로그아웃", key="logout_btn_sidebar", use_container_width=True):
                supabase.auth.sign_out()
                st.session_state.is_logged_in = False
                st.session_state.user_info = None
                st.session_state.code_processed = False
                st.rerun()



# ==========================================
# [4] 메인 애플리케이션
# ==========================================
def main():
    # [청소기 가동] 앱 시작 시 24시간 지난 토큰 삭제
    db.cleanup_old_tokens()

    MAINTENANCE_MODE = False
    
    # [1] 값 초기화
    if "total_invest" not in st.session_state: st.session_state.total_invest = 30000000
    if "selected_stocks" not in st.session_state: st.session_state.selected_stocks = []

    # [2] 관리자 인증
    is_admin = False
    if st.query_params.get("admin", "false").lower() == "true":
        ADMIN_HASH = "c41b0bb392db368a44ce374151794850417b56c9786e3c482f825327c7153182"
        with st.expander("🔐 관리자 접속 (Admin)", expanded=False):
            password_input = st.text_input("비밀번호 입력", type="password")
            if password_input:
                if hashlib.sha256(password_input.encode()).hexdigest() == ADMIN_HASH:
                    is_admin = True
                    st.success("관리자 모드 ON 🚀")
                else:
                    st.error("비밀번호 불일치")

    render_login_ui()
    
    if MAINTENANCE_MODE and not is_admin:
        st.title("🚧 시스템 정기 점검 중")
        st.stop()
    
    if is_admin: st.title("💰 배당팽이 대시보드 (관리자 모드)")
    else: st.title("💰 배당팽이 월배당 계산기")



    # ---------------------------------------------------------
    # [최종 완성] 최상단 통합 로그인 센터 (성공 로직 100% 복구)
    # ---------------------------------------------------------
    auth_container = st.container(border=True)
    with auth_container:
        if not st.session_state.get("is_logged_in", False):
            # 1. 로그인 전 안내
            if "code" in st.query_params:
                 st.info("🔄 로그인 확인 중입니다... 잠시만 기다려주세요.")
            else:
                st.info("🔒 로그인이 필요합니다. (AI 진단 및 저장 기능 활성화)")
                
                # [성공 공식 1] 세션 ID 가져오기
                try:
                    ctx = get_script_run_ctx()
                    current_session_id = ctx.session_id
                except:
                    current_session_id = "unknown"

                # [성공 공식 2] 파라미터가 포함된 리다이렉트 주소 사용
                redirect_url = f"https://dividend-pange.streamlit.app?old_id={current_session_id}"

                col_l, col_r = st.columns(2)
                
                with col_l:
                    # --- 🟡 카카오 로그인 (선생님 원본 방식 복구) ---
                    try:
                        res_kakao = supabase.auth.sign_in_with_oauth({
                            "provider": "kakao",
                            "options": {
                                "redirect_to": redirect_url,
                                "skip_browser_redirect": True
                            }
                        })
                        if res_kakao.url:
                            # target="_blank"와 선생님의 원본 스타일 그대로 복구
                            btn_kakao_html = f'''
                            <a href="{res_kakao.url}" target="_blank" style="
                                display: inline-flex; justify-content: center; align-items: center; width: 100%;
                                background-color: #FEE500; color: #000000; border: 1px solid rgba(0,0,0,0.05);
                                padding: 0.8rem; border-radius: 0.5rem; text-decoration: none; font-weight: bold; font-size: 1.1em;
                                box-shadow: 0 1px 2px rgba(0,0,0,0.1); margin-bottom: 10px;">
                                💬 Kakao로 3초 만에 시작하기
                            </a>'''
                            st.markdown(btn_kakao_html, unsafe_allow_html=True)
                    except: pass

                with col_r:
                    # --- 🔵 구글 로그인 (선생님 원본 meta refresh 방식 복구) ---
                    if st.button("🔵 Google로 시작하기", use_container_width=True, key="top_google_btn"):
                        try:
                            res_google = supabase.auth.sign_in_with_oauth({
                                "provider": "google",
                                "options": {
                                    "redirect_to": redirect_url,
                                    "queryParams": {"access_type": "offline", "prompt": "consent"},
                                    "skip_browser_redirect": False
                                }
                            })
                            if res_google.url:
                                # 구글 로그인에 가장 확실했던 meta refresh 방식
                                st.markdown(f'<meta http-equiv="refresh" content="0;url={res_google.url}">', unsafe_allow_html=True)
                                st.stop()
                        except: pass
        else:
            # 2. 로그인 완료 후 상단 바
            user = st.session_state.user_info
            nickname = user.email.split("@")[0] if user.email else "User"
            c1, c2 = st.columns([3, 1])
            c1.success(f"👋 **{nickname}**님, 환영합니다! 모든 고급 기능이 활성화되었습니다.")
            if c2.button("🚪 로그아웃", use_container_width=True, key="top_logout_final"):
                supabase.auth.sign_out()
                st.session_state.is_logged_in = False
                st.rerun()

                
    # 데이터 로드
    df_raw = logic.load_stock_data_from_csv()
    if df_raw.empty: st.stop()


    # [관리자] 갱신 도구
    if is_admin:
        with st.sidebar:
            st.markdown("---")
            st.subheader("🛠️ 배당금 갱신 도구")
            
            # 1. 신규 종목 식별 로직 (⭐ 라벨링)
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
                
                # 2. 배당률 자동 조회 버튼
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

            # 4. [New] 안전 저장 시스템 (백업 + 저장)
            st.markdown("---")
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
                        
                        # [보호 장치] 신규 상장 종목(12개월 미만)은 크롤링 패스
                        if 0 < months < 12:
                            skipped_count += 1
                            continue
                        
                        # [핵심 변경] %가 아니라 '금액'을 긁어옵니다!
                        code = str(row['종목코드']).strip()
                        cat = str(row.get('분류', '국내')).strip()
                        
                        # logic.py에 새로 만든 함수 호출 (금액 긁어오기)
                        amt, src = logic.fetch_dividend_amount_hybrid(code, cat)
                        
                        if amt > 0:
                            # 긁어온 금액을 '연배당금_크롤링' 열에 저장 (새로운 저장소)
                            df_temp.at[i, '연배당금_크롤링'] = amt
                            updated_count += 1
                        else:
                            # [디버그 모드] 실패 시 원인을 화면에 출력 (나중에 지우면 됩니다)
                            st.warning(f"⚠️ {row['종목명']}({code}) 실패 -> 원인: {src}")
                            pass
                            
                    status_text.text("완료!")
                    st.success(f"✅ {updated_count}개 금액 갱신 완료 / 🛡️ {skipped_count}개 신규주 보호됨")
                    
                    # 변경된 데이터 임시 저장
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
    # ▼▼▼ [중요] 여기입니다! ▼▼▼
    # 'if is_admin:' 과 머리(시작점)를 똑같이 맞추세요!
    with st.spinner('⚙️ 배당 데이터베이스 엔진 가동 중...'):
        df = logic.load_and_process_data(df_raw, is_admin=is_admin)
        st.session_state['shared_df'] = df


    # ---------------------------------------------------------
    # 사이드바 메뉴 & 불러오기
    # ---------------------------------------------------------
    with st.sidebar:
        if not st.session_state.is_logged_in: st.markdown("---")
        menu = st.radio("📂 **메뉴 이동**", ["💰 배당금 계산기", "📃 전체 종목 리스트"], label_visibility="visible")
        st.markdown("---")
        with st.expander("📂 불러오기 / 관리"):
            if not st.session_state.is_logged_in:
                st.caption("🔒 상단에서 로그인을 해주세요.")
            else:
                try:
                    uid = st.session_state.user_info.id
                    resp = supabase.table("portfolios").select("*").eq("user_id", uid).order("created_at", desc=True).execute()
                    if resp.data:
                        opts = {}
                        for p in resp.data:
                            date_str = p['created_at'][5:10]
                            time_str = p['created_at'][11:16]
                            name = p.get('name') or '이름없음'
                            label = f"{name} ({date_str} {time_str})"
                            opts[label] = p
                        sel_name = st.selectbox("항목 선택", list(opts.keys()), label_visibility="collapsed")
                        is_delete_mode = st.toggle("🗑️ 삭제 모드 켜기")
                        if is_delete_mode:
                            if st.button("🚨 영구 삭제", type="primary", use_container_width=True):
                                target_id = opts[sel_name]['id']
                                supabase.table("portfolios").delete().eq("id", target_id).execute()
                                st.toast("삭제되었습니다.", icon="🗑️")
                                st.rerun()
                        else:
                            if st.button("📂 불러오기", use_container_width=True):
                                data = opts[sel_name]['ticker_data']
                                st.session_state.total_invest = int(data.get('total_money', 30000000))
                                st.session_state.selected_stocks = list(data.get('composition', {}).keys())
                                st.toast("성공적으로 불러왔습니다!", icon="✅")
                                st.rerun()
                    else:
                        st.caption("저장된 기록이 없습니다.")
                except Exception as e:
                    st.error("불러오기 실패")

    # =================================================================================
    # [화면 1] 배당금 계산기
    # =================================================================================
    if menu == "💰 배당금 계산기":
        
   
        # -----------------------------------------------------------------
        # [신규 기능] AI 로보어드바이저 (로그인 전용)
        # -----------------------------------------------------------------
        st.write("")
        col_rec1, col_rec2 = st.columns([2, 1])
        
        with col_rec1:
            st.info("🤔 **어떤 종목을 담아야 할지 막막하신가요?**\n\nAI가 성향을 분석해 최적의 포트폴리오를 제안합니다.")
            
        with col_rec2:
            st.write("") 
            # [수정] 버튼 클릭 시 로그인 여부에 따른 동선 가이드 강화
            if st.button("🕵️ AI 로보어드바이저 실행", use_container_width=True, type="primary"):
                if st.session_state.get("is_logged_in"):
                    st.session_state.ai_modal_open = True
                    st.session_state.wiz_step = 1 # 열 때 초기화
                    st.session_state.wiz_data = {}
                    
                    # [핵심 추가] 실행할 때마다 이전 캐시를 완전히 비우고 시작합니다.
                    if "ai_result_cache" in st.session_state:
                        del st.session_state.ai_result_cache
                        
                else:
                    st.error("🔒 로그인이 필요한 기능입니다. 페이지 최상단에서 로그인을 먼저 해주세요!")
                    st.toast("위에서 로그인을 해주세요!", icon="👆")
                    st.session_state.ai_modal_open = False

            # [중요] 팝업 호출
            if st.session_state.get("ai_modal_open", False):
                recommendation.show_wizard()
        
        st.markdown("---")

        
        # -----------------------------------------------------------------

        with st.expander("🧮 나만의 배당 포트폴리오 시뮬레이션", expanded=True):
            col1, col2 = st.columns([1, 2])
            current_invest_val = int(st.session_state.total_invest / 10000)
            invest_input = col1.number_input("💰 총 투자 금액 (만원)", min_value=100, value=current_invest_val, step=100)
            st.session_state.total_invest = invest_input * 10000
            total_invest = st.session_state.total_invest 
            
            selected = col2.multiselect("📊 종목 선택", df['pure_name'].unique(), default=st.session_state.selected_stocks)
            st.session_state.selected_stocks = selected

            if selected:
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
                        
                        # --- [수정 포인트] AI 추천 비중 연동 ---
                        # 1. AI가 제안한 비중 데이터가 있는지 확인합니다.
                        ai_suggested = st.session_state.get('ai_suggested_weights', {})
                        
                        # 2. 제안된 비중이 있으면 그걸 쓰고, 없으면 기존처럼 1/N로 계산합니다.
                        default_w = ai_suggested.get(stock, 100 // len(selected))
                        # ---------------------------------------
        
                        if i < len(selected) - 1:
                            # value 인자에 100 // len(selected) 대신 default_w를 넣습니다.
                            val = st.number_input(f"{stock} (%)", min_value=0, max_value=safe_rem, value=min(safe_rem, default_w), step=5, key=f"s_{i}")
                            weights[stock] = val
                            remaining -= val
                            amt = total_invest * (val / 100)
                        else:
                            # 마지막 종목은 자동으로 남은 비중(safe_rem)을 다 가져갑니다. (기존 유지)
                            st.info(f"{stock}: {safe_rem}% 자동 적용")
                            weights[stock] = safe_rem
                            amt = total_invest * (safe_rem / 100)
                        
                        st.caption(f"💰 투자금: **{amt/10000:,.0f}만원**")
                        # =================================================
                        # [캘린더 버튼] (Logic.py 연동 완료 버전)
                        # =================================================
                        stock_match = df[df['pure_name'] == stock]
                        if not stock_match.empty:
                            s_row = stock_match.iloc[0]
                            
                            # 1. Logic.py에서 미리 계산해둔 링크 가져오기
                            cal_link = s_row.get('캘린더링크') 
                            ex_date_view = s_row.get('배당락일', '-')


                            # 2. 버튼 라벨 결정 (D-3 반영)
                            ex_date_view = s_row.get('배당락일', '-')
                            
                            if cal_link:
                                # D-3 로직에 맞춰 멘트 변경
                                btn_label = f"📅 {ex_date_view} (D-3 알림)" 
                            else:
                                # 날짜가 없으면 달력 아이콘만 변경
                                btn_label = f"🗓️ {ex_date_view}"

                            # 3. 버튼 그리기
                            if cal_link:
                                if st.session_state.get("is_logged_in", False):
                                    # 로그인 상태 -> 바로 구글 캘린더로 이동
                                    st.link_button(btn_label, cal_link, use_container_width=True)
                                else:
                                    # 비로그인 상태 -> 로그인 유도 토스트
                                    if st.button(btn_label, key=f"btn_cal_{i}", use_container_width=True):
                                        st.toast("🔒 로그인 후 캘린더에 등록할 수 있습니다!", icon="🔒")
                            else:
                                # 링크가 없는 경우 (날짜 미정 등)
                                st.caption(f"📅 날짜 미정 ({ex_date_view})")
                        
                        # (데이터 수집 로직)
                        if not stock_match.empty:
                            s_row = stock_match.iloc[0]
                            all_data.append({
                                '종목': stock, '비중': weights[stock], '자산유형': s_row['자산유형'], '투자금액_만원': amt / 10000,
                                '종목명': stock, '코드': s_row.get('코드', ''), '분류': s_row.get('분류', '국내'),
                                '연배당률': s_row.get('연배당률', 0), '금융링크': s_row.get('금융링크', '#'),
                                '신규상장개월수': s_row.get('신규상장개월수', 0), '현재가': s_row.get('현재가', 0),
                                '환구분': s_row.get('환구분', '-'), '배당락일': s_row.get('배당락일', '-')
                            })

                total_y_div = sum([(total_invest * (weights[n]/100) * (df[df['pure_name']==n].iloc[0]['연배당률']/100)) for n in selected])
                total_m = total_y_div / 12
                avg_y = sum([(df[df['pure_name']==n].iloc[0]['연배당률'] * (weights[n]/100)) for n in selected])

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
                # [통합 캘린더 다운로드] (로그인 유도 로직 적용)
                # =========================================================
                st.divider()
                ics_data = logic.generate_portfolio_ics(all_data)

                st.subheader("📅 캘린더 일괄 등록")
                
                col_d1, col_d2 = st.columns([1.5, 1])
                with col_d1:
                    st.caption("매번 버튼을 누르기 귀찮으신가요?")
                    st.caption("아래 버튼으로 **모든 종목의 알림**을 한 번에 내 폰/PC 캘린더에 넣으세요.")
                
                with col_d2:
                    if st.session_state.get("is_logged_in", False):
                        # 1. 로그인 상태: 진짜 다운로드 버튼 표시
                        st.download_button(
                            label="📥 전체 일정 파일 받기 (.ics)",
                            data=ics_data,
                            file_name="dividend_calendar.ics",
                            mime="text/calendar",
                            use_container_width=True,
                            type="primary"
                        )
                    else:
                        # 2. 비로그인 상태: 가짜 버튼 (상단 유도)
                        if st.button("📥 전체 일정 파일 받기 (.ics)", key="ics_lock_btn", use_container_width=True):
                            st.error("🔒 로그인 회원 전용 기능입니다. 로그인을 완료해 주세요!")
                            st.toast("맨 위로 올라가서 로그인을 해주세요!", icon="👆")

                # [친절한 가이드]
                with st.expander("❓ 다운로드 받은 파일은 어떻게 쓰나요? (사용법 보기)"):
                    st.markdown("""
                    **아주 간단합니다! 따라해 보세요.** 👇
                    
                    1. 위 **[전체 일정 파일 받기]** 버튼을 누르세요. (로그인 필요)
                    2. 다운로드된 파일(`dividend_calendar.ics`)을 클릭(터치)해서 여세요.
                    3. 스마트폰이나 PC에서 **"일정을 추가하시겠습니까?"** 라고 물어봅니다.
                    4. **[추가]** 또는 **[저장]** 버튼만 누르면 끝!
                    
                    ---
                    💡 **팁:** - **아이폰/갤럭시:** 파일이 열리면서 자동으로 캘린더 앱이 켜집니다.
                    - **PC(컴퓨터):** 파일이 다운로드 폴더에 저장됩니다. 더블 클릭하면 아웃룩이나 기본 캘린더가 열립니다.
                    """)

                # =========================================================
                # [저장 로직] (UI 개선 완료: 버튼 일원화)
                # =========================================================
                st.write("") 
                with st.container(border=True):
                    st.write("💾 **포트폴리오 저장 / 수정**")
                    
                    if not st.session_state.get('is_logged_in', False):
                        # [안내만 표시] 복잡한 버튼 뭉치 제거
                        st.warning("⚠️ **로그인이 필요합니다.**")
                        st.markdown("""
                        
                        나만의 포트폴리오를 저장하고 관리하시려면 
                        페이지 최상단(맨 위)에 있는 로그인을 이용해 주세요.
                        
                        """)
                    else:
                        # [기능 표시] 로그인 된 유저에게만 노출
                        try:
                            user = st.session_state.user_info
                            save_mode = st.radio("방식 선택", ["✨ 새로 만들기", "🔄 기존 파일 수정"], horizontal=True, label_visibility="collapsed")
                            
                            save_data = {
                                "total_money": st.session_state.total_invest,
                                "composition": weights,
                                "summary": {"monthly": total_m, "yield": avg_y}
                            }

                            if save_mode == "✨ 새로 만들기":
                                c_new1, c_new2 = st.columns([2, 1])
                                p_name = c_new1.text_input("새 이름 입력", placeholder="비워두면 자동 이름", label_visibility="collapsed")
                                
                                if c_new2.button("새로 저장", type="primary", use_container_width=True):
                                    final_name = p_name.strip()
                                    if not final_name:
                                        cnt_res = supabase.table("portfolios").select("id", count="exact").eq("user_id", user.id).execute()
                                        next_num = (cnt_res.count or 0) + 1
                                        final_name = f"포트폴리오 {next_num}"
                                    
                                    supabase.table("portfolios").insert({
                                        "user_id": user.id, "user_email": user.email, "name": final_name, "ticker_data": save_data
                                    }).execute()
                                    
                                    st.success(f"[{final_name}] 저장 완료!")
                                    st.balloons()
                                    time.sleep(1.0)
                                    st.rerun()

                            else: 
                                exist_res = supabase.table("portfolios").select("id, name, created_at").eq("user_id", user.id).order("created_at", desc=True).execute()
                                if not exist_res.data:
                                    st.warning("수정할 포트폴리오가 없습니다. 새로 만들어주세요.")
                                else:
                                    exist_opts = {f"{p.get('name') or '이름없음'} ({p['created_at'][5:10]})": p['id'] for p in exist_res.data}
                                    c_up1, c_up2 = st.columns([2, 1])
                                    selected_label = c_up1.selectbox("수정할 파일 선택", list(exist_opts.keys()), label_visibility="collapsed")
                                    target_id = exist_opts[selected_label]
                                    
                                    if c_up2.button("덮어쓰기", type="primary", use_container_width=True):
                                        supabase.table("portfolios").update({
                                            "ticker_data": save_data,
                                            "created_at": "now()"
                                        }).eq("id", target_id).execute()
                                        st.success("수정 완료! 내용이 업데이트되었습니다.")
                                        st.balloons()
                                        time.sleep(1.0)
                                        st.rerun()

                        except Exception as e:
                            st.error(f"오류 발생: {e}")
                            
                st.write("")
                st.info("""
                📢 **찾으시는 종목이 안 보이나요?**
            
                왼쪽 상단(모바일은 ↖ 메뉴 버튼)의 '📂 메뉴'를 누르고 
                '📃 전체 종목 리스트'를 선택하시면 전체 배당주를 확인하실 수 있습니다.
                """)

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
                                bunryu = str(row.get('분류', ''))
                                exch = str(row.get('환구분', ''))
                                name = str(row.get('종목', ''))
                                if bunryu == "해외" or "(해외)" in name or "환노출" in exch: return "🇺🇸 달러 자산"
                                return "🇰🇷 원화 자산"
                            except: return "🇰🇷 원화 자산"
                        
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
                        
                        st.write("📋 **상세 포트폴리오**")
                        ui.render_custom_table(df_ana)
                        st.error("""**⚠️ 포트폴리오 분석 시 유의사항**
                        
1. 과거의 데이터를 기반으로 한 단순 결과값이며, 실제 투자 수익을 보장하지 않습니다.
2. '달러 자산' 비율 실제 환노출 여부와 다를 수 있습니다 투자 전 확인이 필요합니다.
3. 실제 배당금 지급일과 금액은 운용사의 사정에 따라 변경될 수 있습니다.
""")

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
                        
                        reinvest_ratio = 100
                        isa_exempt = 0
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
                        current_bal = start_money
                        total_principal = start_money
                        ISA_YEARLY_CAP = 20000000
                        ISA_TOTAL_CAP = 100000000
                        sim_data = [{"년차": 0, "자산총액": current_bal/10000, "총원금": total_principal/10000, "실제월배당": 0}]
                        yearly_contribution = 0
                        year_tracker = 0
                        total_tax_paid_general = 0

                        for m in range(1, months_sim + 1):
                            if m // 12 > year_tracker:
                                yearly_contribution = 0
                                year_tracker = m // 12
                            actual_add = monthly_add
                            if is_isa_mode:
                                remaining_yearly = max(0, ISA_YEARLY_CAP - yearly_contribution)
                                remaining_total = max(0, ISA_TOTAL_CAP - total_principal)
                                actual_add = min(monthly_add, remaining_yearly, remaining_total)
                            current_bal += actual_add
                            total_principal += actual_add
                            yearly_contribution += actual_add
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

                        # ========================================================
                        # [랜덤 인카운터] 현실적인 체감을 위한 비유 아이템 목록
                        # ========================================================
                        analogy_items = [
                            {"name": "스타벅스", "unit": "잔", "price": 4500, "emoji": "☕"},
                            {"name": "뜨끈한 국밥", "unit": "그릇", "price": 10000, "emoji": "🍲"},
                            {"name": "넷플릭스 구독", "unit": "개월", "price": 17000, "emoji": "📺"},
                            {"name": "치킨", "unit": "마리", "price": 23000, "emoji": "🍗"},
                            {"name": "제주도 항공권", "unit": "장", "price": 60000, "emoji": "✈️"},
                            {"name": "특급호텔 숙박", "unit": "박", "price": 200000, "emoji": "🏨"},
                            {"name": "최신 아이폰", "unit": "대", "price": 1500000, "emoji": "📱"}
                        ]

                        # [스마트 로직] 내 돈으로 '1개 이상' 살 수 있는 것만 추려내기
                        affordable_items = [item for item in analogy_items if monthly_pocket >= item['price']]

                        if not affordable_items:
                            selected_item = analogy_items[0]
                            item_count = 0
                            msg_count = f"{monthly_pocket / selected_item['price']:.1f}"
                        else:
                            selected_item = random.choice(affordable_items)
                            item_count = int(monthly_pocket // selected_item['price'])
                            msg_count = f"{item_count:,}"

                        st.markdown(f"""
                            <div style="background-color: #e7f3ff; border: 1.5px solid #d0e8ff; border-radius: 16px; padding: 25px; text-align: center; box-shadow: 0 4px 10px rgba(0,104,201,0.05);">
                                <p style="color: #666; font-size: 0.95em; margin: 0 0 8px 0;">{years_sim}년 뒤 모이는 돈 (세후)</p>
                                <h2 style="color: #0068c9; font-size: 2.2em; margin: 0; font-weight: 800; line-height: 1.2;">약 {real_money/10000:,.0f}만원{inflation_msg_money}</h2>
                                <p style="color: #777; font-size: 0.9em; margin: 8px 0 0 0;">(투자원금 {final_principal/10000:,.0f}만원 / {tax_msg})</p>
                                <div style="height: 1px; background-color: #d0e8ff; margin: 25px auto; width: 85%;"></div>
                                <p style="color: #0068c9; font-weight: bold; font-size: 1.1em; margin: 0 0 12px 0;">📅 월 예상 배당금: {monthly_pocket/10000:,.1f}만원 {inflation_msg_monthly}</p>
                                <div style="background-color: rgba(255,255,255,0.5); padding: 15px; border-radius: 12px; display: inline-block; min-width: 80%;">
                                    <p style="color: #333; font-size: 1.1em; margin: 0; line-height: 1.6;">
                                        매달 <b>{selected_item['emoji']} {selected_item['name']} {msg_count}{selected_item['unit']}</b><br>
                                        마음껏 즐기기 가능! 😋
                                    </p>
                                </div>
                            </div>
                        """, unsafe_allow_html=True)
                        
                        annual_div_income = monthly_div_final * 12
                        if annual_div_income > 20000000: st.warning(f"🚨 **주의:** {years_sim}년 뒤 연간 배당금이 2,000만원을 초과하여 금융소득종합과세 대상이 될 수 있습니다.")
                        st.error("""**⚠️ 시뮬레이션 활용 시 유의사항**
                        
1. 본 결과는 주가·환율 변동을 제외하고, 현재 배당률로만 계산한 결과입니다.
2. ISA 계좌의 비과세 한도 및 세율은 세법 개정에 따라 달라질 수 있습니다.
3. 과거의 데이터를 기반으로 한 단순 시뮬레이션이며, 실제 투자 수익을 보장하지 않습니다.
""")
                        with tab_goal:
                            st.subheader("🎯 목표 배당금 역산기 (은퇴 시뮬레이터)")
                            st.caption("내가 원하는 월급을 받기 위해 얼마를 더 모아야 할지 정밀하게 계산합니다.")
                            
                            col_g1, col_g2 = st.columns(2)
                            with col_g1:
                                # 선생님의 목표인 '금융종합과세 회피(연 1,999만원)'를 고려한 가이드 추가
                                target_monthly_goal = st.number_input("목표 월 배당금 (만원, 세후)", min_value=10, value=166, step=10) * 10000
                                st.caption(f"💡 월 166.5만원 설정 시 연간 약 1,998만원으로 절세가 가능합니다.")
                                
                                use_start_money = st.checkbox("위에서 설정한 초기 자산을 포함하여 계산", value=True)
                                start_bal_goal = total_invest if use_start_money else 0
                                
                            with col_g2:
                                monthly_add_goal = st.number_input("매월 추가 적립 가능 금액 (만원)", min_value=0, value=150, step=10) * 10000
                                apply_inflation_goal = st.toggle("📈 목표치에 물가상승률 반영", value=False, help="미래의 가치가 현재의 얼마인지 고려하여 목표를 상향 조정합니다.")
                        
                            # 계산 로직 (수치 정밀도 유지)
                            tax_factor = 0.846
                            # 필요한 총 자산 = (목표 월배당 / 세후 비율) / (연배당률 / 12개월)
                            required_asset_goal = (target_monthly_goal / tax_factor) / (avg_y / 100) * 12
                            
                            st.markdown("---")
                            c_res1, c_res2 = st.columns(2)
                            with c_res1:
                                st.metric("목표 달성 필요 자산", f"{required_asset_goal/100000000:,.2f} 억원")
                                st.caption(f"평균 배당률 {avg_y:.2f}% 및 배당세 15.4% 가정")
                                
                            with c_res2:
                                current_bal_goal = start_bal_goal
                                months_passed = 0
                                max_months = 600 # 50년 제한
                                
                                # 
                                # 시뮬레이션 루프
                                while current_bal_goal < required_asset_goal and months_passed < max_months:
                                    div_reinvest = current_bal_goal * (avg_y / 100 / 12) * tax_factor
                                    current_bal_goal += monthly_add_goal + div_reinvest
                                    months_passed += 1
                                    
                                if months_passed >= max_months:
                                    st.error("⚠️ 현재 적립액으로는 50년 내 달성이 어렵습니다. 적립액을 높여주세요.")
                                else:
                                    st.metric("목표 달성까지 소요 기간", f"{months_passed // 12}년 {months_passed % 12}개월")
                        
                            # 결과 분석 메시지
                            if apply_inflation_goal and months_passed < max_months:
                                discount_factor = (1.025) ** (months_passed / 12)
                                real_value = target_monthly_goal / discount_factor
                                st.warning(f"⚠️ **물가 반영 시:** {months_passed // 12}년 뒤 {target_monthly_goal/10000:,.0f}만원의 실질 가치는 현재 기준 **약 {real_value/10000:,.1f}만원**입니다.")
                            
                            target_annual_income = target_monthly_goal * 12
                            # 연 2,000만원 초과 여부 체크 (선생님의 핵심 관심사)
                            if (target_annual_income / tax_factor) > 20000000:
                                st.warning(f"🚨 **현실적 조언:** 목표 달성 시 연간 배당소득(세전)이 2,000만원을 초과하여 **금융소득종합과세** 대상이 될 수 있습니다.")
                            elif (target_annual_income / tax_factor) > 19000000:
                                st.success(f"✅ **절세 전략:** 현재 목표는 금융소득종합과세 기준선 이내에서 최적화되어 있습니다.")
                        
                            st.error("""**⚠️ 시뮬레이션 활용 시 유의사항**
                            
                        1. 본 결과는 주가·환율 변동을 제외하고, 현재 배당률로만 계산한 단순 결과입니다.
                        2. 재투자가 매월 칼같이 이루어진다는 가정하에 계산된 복리 결과입니다.
                        3. 실제 투자 시에는 배당 삭감이나 주가 하락의 리스크를 반드시 고려해야 합니다.
                        """)

    elif menu == "📃 전체 종목 리스트":
        st.info("💡 **이동 안내:** '코드' 클릭 시 블로그 분석글로, '🔗정보' 클릭 시 네이버/야후 금융 정보로 이동합니다. (**⭐ 표시는 상장 1년 미만 종목입니다.**)")
        tab_all, tab_kor, tab_usa = st.tabs(["🌎 전체", "🇰🇷 국내", "🇺🇸 해외"])
        with tab_all: ui.render_custom_table(df)
        with tab_kor: ui.render_custom_table(df[df['분류'] == '국내'])
        with tab_usa: ui.render_custom_table(df[df['분류'] == '해외'])

    st.divider()
    st.caption("© 2025 **배당팽이** | 실시간 데이터 기반 배당 대시보드")
    st.caption("First Released: 2025.12.31 | [📝 배당팽이의 배당 투자 일지 구경가기](https://blog.naver.com/dividenpange)")

    @st.fragment
    def track_visitors():
        if 'visited' not in st.session_state: st.session_state.visited = False
        if not st.session_state.visited:
            try:
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
                        else: st.session_state.display_count = "Local"
                else:
                    if supabase:
                        response = supabase.table("visit_counts").select("count").eq("id", 1).execute()
                        st.session_state.display_count = response.data[0]['count'] if response.data else "Admin"
                    else: st.session_state.display_count = "Admin"
                st.session_state.visited = True
            except Exception:
                st.session_state.display_count = "확인 중"
                st.session_state.visited = True

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
