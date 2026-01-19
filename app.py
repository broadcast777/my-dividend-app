"""
프로젝트: 배당 팽이 (Dividend Top) v2.4
파일명: app.py
설명: 모바일 UX 최적화 (상단 통합 헤더 신설 및 시뮬레이션 섹션 최우선 배치)
"""

import streamlit as st
import pandas as pd
import altair as alt
import hashlib
import time
import random
from streamlit.runtime.scriptrunner import get_script_run_ctx
from logger import logger
from analytics import inject_ga
import streamlit.components.v1 as components

# [필수] 날짜 및 URL 라이브러리
from datetime import datetime, timedelta
import urllib.parse

# [모듈화] 기능을 분리한 커스텀 파일들을 불러옵니다
import logic
import ui
import db
import recommendation
import timeline


# ==========================================
# [SECTION 1] 기본 페이지 설정 및 초기화
# ==========================================

# 앱의 타이틀과 가로 너비를 설정합니다
st.set_page_config(page_title="배당팽이 대시보드", layout="wide")

# 📡 [RFID 센서] 브라우저 저장소(localStorage)와 URL 동기화
components.html("""
<script>
    try {
        const ageVerified = localStorage.getItem('age_verified');
        const params = new URLSearchParams(window.parent.location.search);
        if (ageVerified === '1' && !params.has('age_verified')) {
            params.set('age_verified', '1');
            window.parent.location.search = params.toString();
        }
    } catch (e) { console.log("Sensor Error: ", e); }
</script>
""", height=0)

# [리팩토링 1] 세션 상태 초기화 함수
def init_session_state():
    """앱 전반에서 사용하는 모든 세션 변수를 안전하게 초기화합니다."""
    defaults = {
        "is_logged_in": False,
        "user_info": None,
        "code_processed": False,
        "ai_modal_open": False,
        "age_verified": False,
        "total_invest": 30000000, 
        "selected_stocks": [],
        "monthly_expense": 200, 
        "ai_result_cache": None,
        "show_ai_login": False
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value

# ---------------------------------------------------------
# [추가 과제] 4과제: COPPA 나이 확인
# ---------------------------------------------------------
def check_coppa_compliance():
    """만 13세 이상 이용 확인"""
    if (st.session_state.get("age_verified") or 
        st.query_params.get("age_verified") == "1" or 
        st.session_state.get("is_logged_in")):
        st.session_state.age_verified = True
        return

    with st.expander("📋 서비스 이용 안내 (필수)", expanded=True):
        st.warning("본 서비스는 만 13세 이상 사용자만 이용 가능합니다.")
        if st.checkbox("나는 만 13세 이상이며, 이용 약관 및 개인정보 처리방침에 동의합니다."):
            st.session_state.age_verified = True
            st.components.v1.html("<script>localStorage.setItem('age_verified','1');</script>", height=0)
            st.query_params["age_verified"] = "1"
            time.sleep(0.5)
            st.rerun()
        else:
            st.stop()

# 외부 데이터베이스(Supabase) 연결 초기화
supabase = db.init_supabase()


# ==========================================
# [SECTION 2] 인증 및 보안 엔진
# ==========================================

def check_auth_status():
    """로그인 상태 확인 및 콜백 처리"""
    if not supabase: return

    try:
        session = supabase.auth.get_session()
        if session and session.user:
            st.session_state.is_logged_in = True
            st.session_state.user_info = session.user
            for key in ["code", "old_id"]:
                if key in st.query_params: del st.query_params[key]
            return 
    except Exception:
        pass

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
                logger.info(f"👤 사용자 로그인 성공: {session.user.email}")
            
            if "code" in st.query_params: del st.query_params["code"]
            st.success("✅ 로그인되었습니다!")
            st.rerun()
        except Exception as e:
            logger.error(f"🚨 [Auth Error] 인증 프로세스 중 예외 발생: {str(e)}", exc_info=True)
            err_msg = str(e).lower()
            if "verifier" in err_msg or "non-empty" in err_msg:
                st.warning("🔄 보안 토큰 갱신 중... 잠시만 기다려주세요.")
                for key in ["code", "old_id"]:
                    if key in st.query_params: del st.query_params[key]
                time.sleep(1.0)
                st.rerun()
            else:
                st.error(f"🔴 인증 오류: {e}")
                if "code" in st.query_params: del st.query_params["code"]

check_auth_status()


# ==========================================
# [SECTION 3] UI 컴포넌트
# ==========================================

def render_login_ui():
    """사이드바 상단 로그인 정보"""
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
                logger.info(f"🚪 사용자 로그아웃: {email}")
                supabase.auth.sign_out()
                st.session_state.is_logged_in = False
                st.session_state.user_info = None
                st.session_state.code_processed = False
                st.rerun()

def render_sidebar_footer():
    """사이드바 하단 후원 버튼 (CSS 분리 적용됨)"""
    bmc_url = "https://www.buymeacoffee.com/dividenpange"
    st.sidebar.markdown("---") 
    st.sidebar.markdown(f"""
        <div class="bmc-container">
            <a class="bmc-button" href="{bmc_url}" target="_blank">
                <img src="https://cdn.buymeacoffee.com/buttons/bmc-new-btn-logo.svg" alt="BMC logo" class="bmc-logo">
                <span>배당팽이에게 커피 한 잔</span>
            </a>
        </div>
    """, unsafe_allow_html=True)


# ==========================================
# [SECTION 4] 페이지별 렌더링 함수
# ==========================================

def render_login_buttons(key_suffix="default"):
    """예쁜 디자인의 로그인 버튼 세트 (CSS 분리 적용됨)"""
    try:
        ctx = get_script_run_ctx()
        current_session_id = ctx.session_id
    except: current_session_id = "unknown"
    redirect_url = f"https://dividend-pange.streamlit.app?old_id={current_session_id}"

    # 상단 헤더용일 때는 문구 생략하고 버튼만 심플하게
    if key_suffix != "top_header":
        st.caption("🔒 기능을 사용하려면 로그인이 필요합니다.")
        
    col1, col2 = st.columns(2)
    with col1:
        try:
            res_kakao = supabase.auth.sign_in_with_oauth({"provider": "kakao", "options": {"redirect_to": redirect_url, "skip_browser_redirect": True}})
            if res_kakao.url:
                st.markdown(f'''<a href="{res_kakao.url}" target="_blank" class="kakao-login-btn">💬 카카오로 3초 만에 시작</a>''', unsafe_allow_html=True)
        except: st.error("Kakao 오류")
    with col2:
        if st.button("🔵 Google로 시작하기", key=f"btn_google_{key_suffix}", use_container_width=True):
            try:
                res_google = supabase.auth.sign_in_with_oauth({"provider": "google", "options": {"redirect_to": redirect_url, "queryParams": {"access_type": "offline", "prompt": "consent"}, "skip_browser_redirect": False}})
                if res_google.url:
                    st.markdown(f'<meta http-equiv="refresh" content="0;url={res_google.url}">', unsafe_allow_html=True)
                    st.stop()
            except: pass

def render_admin_tools(df_raw):
    """관리자 전용 도구"""
    with st.sidebar:
        st.markdown("---")
        st.subheader("🛠️ 배당금 갱신 도구")
        
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
            st.caption("👇 배당금 업데이트 모드 선택")
            new_div = st.number_input("이번 달 확정 배당금 (또는 월평균)", value=0, step=10)
            
            col_btn1, col_btn2 = st.columns(2)
            
            if col_btn1.button("💾 1개월 추가", use_container_width=True):
                new_total, new_hist = logic.update_dividend_rolling(cur_hist, new_div)
                df_raw.loc[df_raw['종목코드'] == code, '배당기록'] = new_hist
                df_raw.loc[df_raw['종목코드'] == code, '연배당금'] = new_total
                df_raw.loc[df_raw['종목코드'] == code, '연배당금_크롤링'] = new_total
                
                current_price = row.get('현재가', 0)
                if not current_price: current_price = logic._fetch_price_raw(st.session_state.get('broker'), code, category)
                if current_price > 0:
                    new_yield = round((new_total / current_price) * 100, 2)
                    df_raw.loc[df_raw['종목코드'] == code, '연배당률'] = new_yield
                    df_raw.loc[df_raw['종목코드'] == code, '연배당률_크롤링'] = new_yield
                    st.success(f"✅ 1개월 추가 완료 ({new_total}원 / {new_yield}%)")
                st.session_state.df_dirty = df_raw

            if col_btn2.button("⚡ 1년치 강제 적용", type="primary", use_container_width=True):
                new_total = new_div * 12
                new_hist = "|".join([str(new_div)] * 12)
                df_raw.loc[df_raw['종목코드'] == code, '배당기록'] = new_hist
                df_raw.loc[df_raw['종목코드'] == code, '연배당금'] = new_total
                df_raw.loc[df_raw['종목코드'] == code, '연배당금_크롤링'] = new_total
                
                current_price = row.get('현재가', 0)
                if not current_price: current_price = logic._fetch_price_raw(st.session_state.get('broker'), code, category)
                if current_price > 0:
                    new_yield = round((new_total / current_price) * 100, 2)
                    df_raw.loc[df_raw['종목코드'] == code, '연배당률'] = new_yield
                    df_raw.loc[df_raw['종목코드'] == code, '연배당률_크롤링'] = new_yield 
                    st.success(f"⚡ 1년치 강제 적용 완료! ({new_total}원 / {new_yield}%)")
                st.session_state.df_dirty = df_raw

        st.markdown("---")
        st.subheader("💾 데이터 저장 및 백업")
        
        csv_data = df_raw.to_csv(index=False).encode('utf-8')
        st.download_button("📂 (혹시 모르니) 현재 파일 백업하기", data=csv_data, file_name=f"stocks_backup_{pd.Timestamp.now().strftime('%Y%m%d')}.csv", mime='text/csv', use_container_width=True)

        st.write("") 
        with st.expander("⚡ 전체 종목 자동 업데이트 (신규 제외)"):
            st.caption("신규 상장 종목(⭐)과 배당률 2% 미만은 건너뜁니다.")
            if st.button("전체 자동 갱신 시작"):
                progress_bar = st.progress(0)
                status_text = st.empty()
                updated_count = 0
                skipped_count = 0
                fail_list = []
                total_stocks = len(df_raw)
                df_temp = df_raw.copy()
                
                for i, row in df_temp.iterrows():
                    progress_bar.progress((i + 1) / total_stocks)
                    status_text.text(f"검사 중: {row['종목명']}...")
                    try: months = int(row.get('신규상장개월수', 0))
                    except: months = 0
                    if 0 < months < 12:
                        skipped_count += 1
                        continue
                    
                    code = str(row['종목코드']).strip()
                    cat = str(row.get('분류', '국내')).strip()
                    y_val, src = logic.fetch_dividend_yield_hybrid(code, cat) 
                    
                    if y_val > 0:
                        df_temp.at[i, '연배당률_크롤링'] = y_val
                        updated_count += 1
                    else:
                        fail_msg = f"{row['종목명']}({code}) - {src}"
                        fail_list.append(fail_msg)
                        logger.error(f"업데이트 실패: {fail_msg}")
                    time.sleep(0.1)
                        
                progress_bar.empty()
                status_text.text("완료!")
                st.success(f"✅ {updated_count}개 갱신 성공 / 🛡️ {skipped_count}개 보호됨")
                if fail_list:
                    st.error(f"🚨 {len(fail_list)}개 업데이트 실패")
                    with st.expander("🔍 실패 원인 명단 보기"):
                        for f in fail_list: st.write(f"- {f}")
                st.session_state.df_dirty = df_temp

        st.markdown("---")
        st.info("💡 위에서 내용을 충분히 검토하셨나요?")
        confirm_save = st.checkbox("네, 덮어써도 좋습니다.")

        if confirm_save:
            if st.button("🚀 깃허브에 영구 저장 (Commit)", type="primary", use_container_width=True):
                with st.spinner("서버에 업로드 중..."):
                    target_df = st.session_state.get('df_dirty', df_raw)
                    success, msg = logic.save_to_github(target_df)
                    if success:
                        st.success(msg)
                        logger.info("💾 관리자가 깃허브 데이터 업데이트 완료")
                        st.balloons()
                        time.sleep(2)
                        st.rerun()
                    else:
                        st.error(msg)
        else:
            st.button("🚀 깃허브에 영구 저장", disabled=True, use_container_width=True)


# ==========================================
# [SECTION 5] 메인 애플리케이션 실행 엔진 (관제실)
# ==========================================

# 🚨 [추가된 함수] 삭제 확인 다이얼로그 (Dialog)
@st.dialog("⚠️ 정말 삭제하시겠습니까?")
def confirm_delete_dialog(target_names, opts, supabase):
    st.write(f"선택하신 **{len(target_names)}개**의 포트폴리오가 영구적으로 삭제됩니다.")
    st.warning("이 작업은 되돌릴 수 없습니다.")
    
    col_del1, col_del2 = st.columns(2)
    
    if col_del1.button("✅ 네, 삭제합니다", type="primary", use_container_width=True):
        try:
            target_ids = [opts[name]['id'] for name in target_names]
            # Supabase 'in' 쿼리로 일괄 삭제
            supabase.table("portfolios").delete().in_("id", target_ids).execute()
            
            logger.info(f"🗑️ 포트폴리오 일괄 삭제: {len(target_ids)}건")
            st.rerun()
        except Exception as e:
            st.error(f"삭제 중 오류 발생: {e}")
            
    if col_del2.button("취소", use_container_width=True):
        st.rerun()

# 💾 [추가된 함수] 덮어쓰기 확인 다이얼로그
@st.dialog("💾 기존 파일 덮어쓰기")
def confirm_overwrite_dialog(final_name, user_id, user_email, save_data, existing_id, supabase):
    """이미 같은 이름의 포트폴리오가 있을 때 띄우는 팝업"""
    st.write(f"이미 **'{final_name}'**이라는 이름의 포트폴리오가 존재합니다.")
    st.info("새로운 데이터로 덮어쓰시겠습니까?")
    
    col_ov1, col_ov2 = st.columns(2)
    
    if col_ov1.button("🎮 네, 덮어씁니다", type="primary", use_container_width=True):
        try:
            # 기존 ID를 찾아서 해당 데이터만 업데이트
            supabase.table("portfolios").update({
                "ticker_data": save_data, 
                "created_at": "now()" # 저장 시간 갱신
            }).eq("id", existing_id).execute()
            
            logger.info(f"🔄 기존 포트폴리오 덮어쓰기 완료: {final_name}")
            st.toast(f"'{final_name}' 파일을 성공적으로 갱신했습니다!", icon="✅")
            st.balloons()
            time.sleep(1.0)
            st.rerun()
        except Exception as e:
            st.error(f"저장 중 오류 발생: {e}")
            
    if col_ov2.button("아니요, 취소", use_container_width=True):
        st.rerun()


def render_calculator_page(df):
    """💰 배당금 계산기 페이지 렌더링"""
    
    # 📌 [수정됨] AI 로보어드바이저 안내 섹션을 여기서 제거했습니다.
    # (이미 최상단 헤더로 이동했으므로 중복 노출 방지)
    
    if st.session_state.get("ai_modal_open", False):
        recommendation.show_wizard()
    
    # 6-2. 포트폴리오 시뮬레이션
    all_data = []
    
    # 여기서부터 시뮬레이션 섹션이 바로 시작됩니다. (expander default=True)
    with st.expander("🧮 나만의 배당 포트폴리오 시뮬레이션", expanded=True):
        col1, col2 = st.columns([1, 2])
        current_invest_val = int(st.session_state.total_invest / 10000)
        invest_input = col1.number_input("💰 총 투자 금액 (만원)", min_value=100, value=current_invest_val, step=100)
        st.session_state.total_invest = invest_input * 10000
        total_invest = st.session_state.total_invest 

        code_col_name = next((c for c in df.columns if '코드' in c), '종목코드')
        name_col_name = next((c for c in df.columns if 'pure' in c or '명' in c), '종목명')

        # -------------------------------------------------------
        # [바코드(Dictionary) 매핑 시스템] (이전 수정사항 유지)
        # -------------------------------------------------------
        
        # 1. 라벨 생성 함수
        def clean_label(row):
            c = str(row.get(code_col_name, '')).strip()
            if '.' in c: c = c.split('.')[0]
            if c.isdigit() and len(c) < 6: c = c.zfill(6)
            n = str(row.get(name_col_name, '')).strip()
            return f"{n} ({c})"

        # 2. 바코드 사전 생성
        label_to_real_name = {}
        for _, row in df.iterrows():
            lbl = clean_label(row)
            label_to_real_name[lbl] = row['pure_name']

        search_options = sorted(list(label_to_real_name.keys()))
        
        # 3. 초기 선택값 세팅
        default_selected_labels = []
        if st.session_state.get('selected_stocks'):
            saved_stocks = st.session_state.selected_stocks
            for label, real_name in label_to_real_name.items():
                if real_name in saved_stocks:
                    default_selected_labels.append(label)

        # 4. UI 출력
        selected_search = col2.multiselect(
            "📊 종목 선택 (이름 또는 코드로 검색)", 
            options=search_options, 
            default=default_selected_labels, 
            help="종목코드(숫자)나 종목명을 입력해 보세요!"
        )

        # 5. 최종 추출
        selected = [label_to_real_name[opt] for opt in selected_search]
        st.session_state.selected_stocks = selected
        # -------------------------------------------------------

        if selected:
            # 🚨 [안전한 검사]
            has_foreign_stock = any(df[df['pure_name'] == s_name].iloc[0]['분류'] == '해외' for s_name in selected)
            
            if has_foreign_stock:
                st.warning("📢 **잠깐!** 선택하신 종목 중 '해외 상장 ETF'가 포함되어 있습니다. ISA/연금계좌 결과는 참고용으로만 봐주세요.")

            weights = {}
            remaining = 100
            cols_w = st.columns(2)
            
            for i, stock in enumerate(selected):
                with cols_w[i % 2]:
                    safe_rem = max(0, remaining)
                    ai_suggested = st.session_state.get('ai_suggested_weights', {})
                    default_w = ai_suggested.get(stock, 100 // len(selected))
                    
                    if i < len(selected) - 1:
                        val = st.number_input(f"{stock} (%)", min_value=0, max_value=safe_rem, value=min(safe_rem, default_w), step=5, key=f"s_{i}")
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
                        cal_link = s_row.get('캘린더링크') 
                        ex_date_view = s_row.get('배당락일', '-')
                        
                        if cal_link:
                            if len(selected) == 1:
                                btn_label = f"📅 {ex_date_view} (D-3 알림)"
                                if st.session_state.get("is_logged_in", False):
                                    st.link_button(btn_label, cal_link, use_container_width=True)
                                else:
                                    if st.button(btn_label, key=f"btn_cal_{i}", use_container_width=True):
                                        st.toast("🔒 로그인 후 캘린더에 등록할 수 있습니다!", icon="🔒")
                            else:
                                st.caption(f"🗓️ 배당락일: **{ex_date_view}**")
                        else:
                            st.caption(f"📅 날짜 미정 ({ex_date_view})")
                    
                    if not stock_match.empty:
                        s_row = stock_match.iloc[0]
                        all_data.append({
                            '종목': stock, '비중': weights[stock], '자산유형': s_row['자산유형'], '투자금액_만원': amt / 10000,
                            '종목명': stock, '코드': s_row.get('코드', ''), '분류': s_row.get('분류', '국내'),
                            '연배당률': s_row.get('연배당률', 0), '금융링크': s_row.get('금융링크', '#'),
                            '신규상장개월수': s_row.get('신규상장개월수', 0), '현재가': s_row.get('현재가', 0),
                            '환구분': s_row.get('환구분', '-'), '배당락일': s_row.get('배당락일', '-')
                        })
            
            timeline.display_sidebar_roadmap(df, weights, total_invest)
            
            if len(selected) > 1:
                st.markdown("""
                    <div style="padding: 12px; border-radius: 8px; background-color: #f0f7ff; border: 1px solid #d0e8ff; margin: 15px 0;">
                        <small style="color: #0068c9; font-weight: bold;">💡 안내</small><br>
                        <small style="color: #555;">종목이 많아 가독성을 위해 개별 버튼 대신 배당일만 표시합니다.<br>
                        모든 일정은 <b>화면 하단의 [📅 캘린더 일괄 등록]</b>에서 한 번에 저장하세요!</small>
                    </div>
                """, unsafe_allow_html=True)
            
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
            chart_compare = alt.Chart(c_data).mark_bar(cornerRadiusTopLeft=10, cornerRadiusTopRight=10).encode(
                x=alt.X('계좌 종류', sort=None, axis=alt.Axis(labelAngle=0, title=None)), 
                y=alt.Y('월 수령액', title=None), 
                color=alt.Color('계좌 종류', scale=alt.Scale(domain=['일반 계좌', 'ISA/연금계좌'], range=['#95a5a6', '#f1c40f']), legend=None), 
                tooltip=[alt.Tooltip('계좌 종류'), alt.Tooltip('월 수령액', format=',.0f')]
            ).properties(height=220)
            st.altair_chart(chart_compare, use_container_width=True)

            st.divider()
            ics_data = logic.generate_portfolio_ics(all_data)
            st.subheader("📅 캘린더 일괄 등록")
            col_d1, col_d2 = st.columns([1.5, 1])
            with col_d1:
                st.caption("매번 버튼을 누르기 귀찮으신가요?")
                st.caption("아래 버튼으로 **모든 종목의 알림**을 한 번에 내 폰/PC 캘린더에 넣으세요.")
            with col_d2:
                if st.session_state.get("is_logged_in", False):
                    st.download_button(label="📥 전체 일정 파일 받기 (.ics)", data=ics_data, file_name="dividend_calendar.ics", mime="text/calendar", use_container_width=True, type="primary")
                else:
                    if st.button("📥 전체 일정 파일 받기 (.ics)", key="ics_lock_btn", use_container_width=True):
                        st.error("🔒 로그인 회원 전용 기능입니다. 로그인을 완료해 주세요!")
                        st.toast("로그인이 필요합니다!", icon="🔒")

            with st.expander("❓ 다운로드 받은 파일은 어떻게 쓰나요? (사용법 보기)"):
                st.markdown("""
                **아주 간단합니다! 따라해 보세요.** 👇
                1. 위 **[전체 일정 파일 받기]** 버튼을 누르세요. (로그인 필요)
                2. 다운로드된 파일(`dividend_calendar.ics`)을 클릭(터치)해서 여세요.
                3. 스마트폰이나 PC에서 **"일정을 추가하시겠습니까?"** 라고 물어봅니다.
                4. **[추가]** 또는 **[저장]** 버튼만 누르면 끝!
                """)

            st.write("") 
            with st.container(border=True):
                st.write("💾 **포트폴리오 저장 / 수정**")
                if not st.session_state.get('is_logged_in', False):
                    st.warning("⚠️ **로그인이 필요합니다.**")
                    st.markdown("""나만의 포트폴리오를 저장하고 관리하시려면 페이지 최상단(맨 위)에 있는 로그인을 이용해 주세요.""")
                else:
                    try:
                        user = st.session_state.user_info
                        save_mode = st.radio("방식 선택", ["✨ 새로 만들기", "🔄 기존 파일 수정"], horizontal=True, label_visibility="collapsed")
                        save_data = {"total_money": st.session_state.total_invest, "composition": weights, "summary": {"monthly": total_m, "yield": avg_y}, "monthly_expense": st.session_state.monthly_expense}

                        if save_mode == "✨ 새로 만들기":
                            c_new1, c_new2 = st.columns([2, 1])
                            p_name = c_new1.text_input("새 이름 입력", placeholder="비워두면 자동 이름", label_visibility="collapsed")
                            
                            if c_new2.button("새로 저장", type="primary", use_container_width=True):
                                final_name = p_name.strip()
                                if not final_name:
                                    cnt_res = supabase.table("portfolios").select("id", count="exact").eq("user_id", user.id).execute()
                                    next_num = (cnt_res.count or 0) + 1
                                    final_name = f"포트폴리오 {next_num}"
                                
                                # 🚨 [안전장치 1] 중복 체크
                                check_res = supabase.table("portfolios").select("id").eq("user_id", user.id).eq("name", final_name).execute()
                                
                                if check_res.data:
                                    # 중복 발생 -> 팝업 신호 보내기
                                    st.session_state.show_overwrite_dialog = {
                                        "name": final_name,
                                        "id": check_res.data[0]['id'],
                                        "data": save_data
                                    }
                                else:
                                    # 중복 없음 -> 바로 저장
                                    supabase.table("portfolios").insert({"user_id": user.id, "user_email": user.email, "name": final_name, "ticker_data": save_data}).execute()
                                    logger.info(f"💾 새 포트폴리오 저장: {final_name}")
                                    st.success(f"[{final_name}] 저장 완료!")
                                    st.balloons()
                                    time.sleep(1.0)
                                    st.rerun()

                        else: # [🔄 기존 파일 수정 모드]
                            exist_res = supabase.table("portfolios").select("id, name, created_at").eq("user_id", user.id).order("created_at", desc=True).execute()
                            if not exist_res.data:
                                st.warning("수정할 포트폴리오가 없습니다. 새로 만들어주세요.")
                            else:
                                exist_opts = {f"{p.get('name') or '이름없음'} ({p['created_at'][5:10]})": p['id'] for p in exist_res.data}
                                c_up1, c_up2 = st.columns([2, 1])
                                selected_label = c_up1.selectbox("수정할 파일 선택", list(exist_opts.keys()), label_visibility="collapsed")
                                target_id = exist_opts[selected_label]
                                
                                # 선택된 이름 찾기 (팝업 표시용)
                                target_name = selected_label.split(" (")[0]

                                if c_up2.button("덮어쓰기", type="primary", use_container_width=True):
                                    # [안전장치 2] 기존 수정 시에도 팝업 띄우기 (일관성)
                                    st.session_state.show_overwrite_dialog = {
                                        "name": target_name,
                                        "id": target_id,
                                        "data": save_data
                                    }

                        # 🚨 [공통 안전 호출 구역] 다이얼로그 실행
                        if "show_overwrite_dialog" in st.session_state:
                            info = st.session_state.show_overwrite_dialog
                            del st.session_state.show_overwrite_dialog
                            confirm_overwrite_dialog(info["name"], user.id, user.email, info["data"], info["id"], supabase)

                    except Exception as e:
                        st.error(f"오류 발생: {e}")
            
            st.write("")
            st.info("""📢 **찾으시는 종목이 안 보이나요?**\n왼쪽 상단(모바일은 ↖ 메뉴 버튼)의 '📂 메뉴'를 누르고 '📃 전체 종목 리스트'를 선택하시면 전체 배당주를 확인하실 수 있습니다.""")
            if total_y_div > 20000000:
                st.warning(f"🚨 **주의:** 연간 예상 배당금이 **{total_y_div/10000:,.0f}만원**입니다. 금융소득종합과세 대상에 해당될 수 있습니다.")

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
            st.error("""**⚠️ 포트폴리오 분석 시 유의사항**\n1. 과거의 데이터를 기반으로 한 단순 결과값이며, 실제 투자 수익을 보장하지 않습니다.\n2. '달러 자산' 비율 실제 환노출 여부와 다를 수 있습니다 투자 전 확인이 필요합니다.\n3. 실제 배당금 지급일과 금액은 운용사의 사정에 따라 변경될 수 있습니다.""")

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
            else:
                if not is_over_100m:
                    st.caption("설정한 비율만큼만 재투자하고 나머지는 생활비로 씁니다.")
                    reinvest_ratio = st.slider("💰 재투자 비율 (%)", 0, 100, 100, step=10)
            
            st.markdown("---")
            monthly_input = st.number_input("➕ 매월 추가 적립 (만원)", min_value=0, max_value=3000, value=150, step=10) * 10000
            monthly_add = monthly_input
            
            if is_isa_mode and monthly_add > 1666666:
                st.warning("⚠️ **ISA 연간 한도 제한:** 월 납입금이 **약 166만원(연 2,000만원)**을 초과하면 초과분은 일반 계좌로 자동 계산됩니다.")
            
            months_sim = years_sim * 12
            monthly_yld = avg_y / 100 / 12
            
            ISA_YEARLY_CAP = 20000000
            ISA_TOTAL_CAP = 100000000
            
            if is_isa_mode:
                isa_bal = start_money if start_money <= ISA_TOTAL_CAP else ISA_TOTAL_CAP
                general_bal = max(0, start_money - ISA_TOTAL_CAP)
                isa_principal = isa_bal
                general_principal = general_bal
            else:
                isa_bal = 0
                general_bal = start_money
                isa_principal = 0
                general_principal = start_money

            total_tax_paid_general = 0
            sim_data = [{"년차": 0, "자산총액": (isa_bal + general_bal)/10000, "총원금": (isa_principal + general_principal)/10000, "실제월배당": 0}]
            
            year_tracker = 0
            yearly_contribution = 0

            for m in range(1, months_sim + 1):
                if m // 12 > year_tracker:
                    yearly_contribution = 0
                    year_tracker = m // 12
                
                if is_isa_mode:
                    remaining_isa_yearly = max(0, ISA_YEARLY_CAP - yearly_contribution)
                    remaining_isa_total = max(0, ISA_TOTAL_CAP - isa_principal)
                    
                    actual_isa_add = min(monthly_add, remaining_isa_yearly, remaining_isa_total)
                    actual_general_add = monthly_add - actual_isa_add
                    
                    isa_bal += actual_isa_add
                    isa_principal += actual_isa_add
                    yearly_contribution += actual_isa_add
                    
                    general_bal += actual_general_add
                    general_principal += actual_general_add
                else:
                    general_bal += monthly_add
                    general_principal += monthly_add

                div_isa = isa_bal * monthly_yld
                isa_bal += div_isa
                
                div_gen = general_bal * monthly_yld
                this_tax = div_gen * 0.154
                total_tax_paid_general += this_tax
                reinvest_gen = (div_gen - this_tax) * (reinvest_ratio / 100)
                general_bal += reinvest_gen
                
                sim_data.append({
                    "년차": m / 12, 
                    "자산총액": (isa_bal + general_bal) / 10000, 
                    "총원금": (isa_principal + general_principal) / 10000, 
                    "실제월배당": div_isa + div_gen
                })
            
            df_sim_chart = pd.DataFrame(sim_data)
            base = alt.Chart(df_sim_chart).encode(x=alt.X('년차:Q', title='경과 기간 (년)'))
            area = base.mark_area(opacity=0.3, color='#0068c9').encode(y=alt.Y('자산총액:Q', title='자산 (만원)'))
            line = base.mark_line(color='#ff9f43', strokeDash=[5,5]).encode(y='총원금:Q')
            st.altair_chart((area + line).properties(height=280), use_container_width=True)

            final_row = df_sim_chart.iloc[-1]
            final_asset = (isa_bal + general_bal)
            final_principal = (isa_principal + general_principal)
            profit_isa = isa_bal - isa_principal
            monthly_div_final = final_row['실제월배당']

            if is_isa_mode:
                taxable_isa = max(0, profit_isa - (isa_exempt * 10000))
                tax_isa = taxable_isa * 0.099
                real_money = final_asset - tax_isa
                tax_msg = f"예상 세금 {tax_isa/10000:,.0f}만원 (9.9% 분리과세)"
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

            analogy_items = [
                {"name": "스타벅스", "unit": "잔", "price": 4500, "emoji": "☕"},
                {"name": "뜨끈한 국밥", "unit": "그릇", "price": 10000, "emoji": "🍲"},
                {"name": "넷플릭스 구독", "unit": "개월", "price": 17000, "emoji": "📺"},
                {"name": "치킨", "unit": "마리", "price": 23000, "emoji": "🍗"},
                {"name": "제주도 항공권", "unit": "장", "price": 60000, "emoji": "✈️"},
                {"name": "특급호텔 숙박", "unit": "박", "price": 200000, "emoji": "🏨"},
                {"name": "최신 아이폰", "unit": "대", "price": 1500000, "emoji": "📱"}
            ]
            affordable_items = [item for item in analogy_items if monthly_pocket >= item['price']]
            if not affordable_items:
                selected_item = analogy_items[0]
                msg_count = f"{monthly_pocket / selected_item['price']:.1f}"
            else:
                selected_item = random.choice(affordable_items)
                item_count = int(monthly_pocket // selected_item['price'])
                msg_count = f"{item_count:,}"

            general_ratio_msg = ""
            if is_isa_mode and general_bal > 1:
                gen_val_manwon = general_bal / 10000
                general_ratio_msg = f"<div style='color: #6c757d; font-size: 0.85em; margin-top: 15px; border-top: 1px dashed #d0e8ff; padding-top: 10px;'>💡 최종 자산 중 <b>약 {gen_val_manwon:,.0f}만원</b>은 ISA 한도 초과로 인해<br>일반 계좌(15.4% 과세)로 운용된 결과입니다.</div>"

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
        </p>{general_ratio_msg}
    </div>
</div>
""", unsafe_allow_html=True)
            
            annual_div_income = monthly_div_final * 12
            if annual_div_income > 20000000: st.warning(f"🚨 **주의:** {years_sim}년 뒤 연간 배당금이 2,000만원을 초과하여 금융소득종합과세 대상이 될 수 있습니다.")
            st.error("""**⚠️ 시뮬레이션 활용 시 유의사항**\n1. 본 결과는 주가·환율 변동을 제외하고, 현재 배당률로만 계산한 단순 결과입니다.
                    2. 재투자가 매월 이루어진다는 가정하에 계산된 복리 결과입니다.""")
        with tab_goal:
            st.subheader("🎯 목표 배당금 역산기 (은퇴 시뮬레이터)")
            st.caption("내가 원하는 월급을 받기 위해 얼마를 더 모아야 할지 정밀하게 계산합니다.")

            # [정보 요약 박스] - 유지
            with st.container(border=True):
                col_info1, col_info2, col_info3 = st.columns(3)
                col_info1.metric("📊 평균 연배당률", f"{avg_y:.2f}%")
                col_info2.metric("💰 매월 추가적립", f"{monthly_input/10000:,.0f}만원")
                col_info3.metric("📦 선택 종목 수", f"{len(selected)}개")
                st.caption(f"🔎 **적용 종목:** {', '.join(selected)}")

            st.write("")

            # [입력창] - 물가상승 제거 및 간소화
            col_g1, col_g2 = st.columns(2)
            with col_g1:
                target_monthly_goal = st.number_input(
                    "목표 월 배당금 (만원, 세후)", 
                    min_value=10, value=166, step=10, 
                    key="target_monthly_goal_input"
                ) * 10000
                st.caption(f"💡 '세후' 월 141만원 설정 시 연간 세전 약 2,000만원 이내로 절세가 가능합니다.")
            
            with col_g2:
                st.write("") 
                st.write("") 
                use_start_money = st.checkbox(
                    "현재 설정된 초기 자산을 포함하여 계산", 
                    value=True, 
                    help="체크 해제 시 '0원'에서 시작하는 제로베이스 시뮬레이션이 진행됩니다.",
                    key="use_start_money_chk"
                )
                st.caption(f"보유: {total_invest/10000:,.0f}만원")

            # [계산 로직] - 물가상승(inflation) 제거됨
            current_bal_goal = total_invest if use_start_money else 0
            actual_start_bal = current_bal_goal 
            
            tax_factor = 0.846
            monthly_yld = avg_y / 100 / 12  
            months_passed = 0
            max_months = 720                
            
            # 목표 자산(고정값) 계산
            if avg_y > 0:
                required_asset_at_time = (target_monthly_goal / tax_factor) * 12 / (avg_y / 100)
            else:
                required_asset_at_time = 0
            
            # 시뮬레이션 루프
            while months_passed < max_months:
                if current_bal_goal >= required_asset_at_time:
                    break
                    
                div_reinvest = current_bal_goal * monthly_yld * tax_factor
                current_bal_goal += monthly_input + div_reinvest
                months_passed += 1

            st.markdown("---")

            # [결과 표시] - 진행률 및 초록색 차감 표시
            gap_money = max(0, required_asset_at_time - actual_start_bal)
            progress_rate = (actual_start_bal / required_asset_at_time) * 100 if required_asset_at_time > 0 else 0

            # 1. 진행률 바
            st.write(f"📊 **목표 달성 진행률: {min(progress_rate, 100):.1f}%**")
            st.progress(min(progress_rate / 100, 1.0))

            # 2. 3단 결과
            if months_passed >= max_months:
                st.error("⚠️ 현재 적립액으로는 60년 내 달성이 어렵습니다. 적립금을 높여주세요.")
            else:
                c_res1, c_res2, c_res3 = st.columns(3)
                with c_res1:
                    st.metric("최종 필요 자산", f"{required_asset_at_time/100000000:,.2f} 억원")
                    st.caption("목표 배당을 위한 몸집")
                
                with c_res2:
                    if gap_money > 0:
                        st.metric(
                            "앞으로 모을 금액", 
                            f"{gap_money/100000000:,.2f} 억원", 
                            delta=f"✅ {actual_start_bal/10000:,.0f}만원 보유 중", 
                            delta_color="normal"
                        )
                    else:
                        st.success("🎉 이미 목표 달성!")
                
                with c_res3:
                    st.metric("목표 달성까지 소요 기간", f"{months_passed // 12}년 {months_passed % 12}개월")
                    st.caption("월 복리 재투자 기준")

            # [하단 문구 정리]
            st.write("") 
            final_annual_income = target_monthly_goal * 12
            if (final_annual_income / tax_factor) > 20000000:
                st.warning(f"🚨 **현실적 조언:** 목표 달성 시 연간 배당소득(세전)이 2,000만원을 초과하여 **금융소득종합과세** 대상이 될 수 있습니다.")
                
            st.error("""
                    **⚠️ 시뮬레이션 활용 시 유의사항**
                    1. 본 결과는 주가·환율 변동을 제외하고, 현재 배당률로만 계산한 단순 결과입니다.
                    2. 재투자가 매월 이루어진다는 가정하에 계산된 복리 결과입니다.
                    """)

            
def render_roadmap_page(df):
    """📅 월별 로드맵 페이지 렌더링"""
    st.header("📅 나의 배당 월급 로드맵")
    st.info("💡 종목별 배당 주기를 반영한 데이터입니다. (로그인 없이 이용 가능)")

    selected = st.session_state.get('selected_stocks', [])
    if not selected:
        st.warning("⚠️ **'💰 배당금 계산기'** 메뉴에서 종목을 먼저 선택해 주세요!")
        st.stop()
    
    weights = {}
    remaining = 100
    for i, stock in enumerate(selected):
        if i < len(selected) - 1:
            val = st.session_state.get(f"s_{i}", 100 // len(selected))
            weights[stock] = val
            remaining -= val
        else:
            weights[stock] = max(0, remaining)

    timeline.render_toss_style_heatmap(df, weights, st.session_state.total_invest)

    if not st.session_state.get("is_logged_in", False):
        st.write("")
        with st.container(border=True):
            st.markdown("### 🔓 로그인이 필요한 기능")
            col_lock1, col_lock2 = st.columns(2)
            with col_lock1:
                st.write("✅ **내 폰으로 배당 알림 받기**")
                st.caption("전체 일정을 .ics 파일로 내려받아 캘린더에 1초 만에 등록하세요.")
            with col_lock2:
                st.write("✅ **설계한 포트폴리오 저장**")
                st.caption("매번 입력할 필요 없이 언제든 다시 불러올 수 있습니다.")
            st.info("👆 페이지 최상단의 로그인 버튼을 이용해 주세요!")


def render_stocklist_page(df):
    """📃 전체 종목 리스트 페이지 렌더링"""
    st.info("💡 **이동 안내:** '코드' 클릭 시 블로그 분석글로, '🔗정보' 클릭 시 네이버/야후 금융 정보로 이동합니다. (**⭐ 표시는 상장 1년 미만 종목입니다.**)")
    tab_all, tab_kor, tab_usa = st.tabs(["🌎 전체", "🇰🇷 국내", "🇺🇸 해외"])
    
    with tab_all: ui.render_custom_table(df)
    with tab_kor: ui.render_custom_table(df[df['분류'] == '국내'])
    with tab_usa: ui.render_custom_table(df[df['분류'] == '해외'])


# ==========================================
# [SECTION 5] 메인 애플리케이션 실행 엔진 (관제실)
# ==========================================

# 🚨 [추가된 함수] 삭제 확인 다이얼로그 (Dialog)
@st.dialog("⚠️ 정말 삭제하시겠습니까?")
def confirm_delete_dialog(target_names, opts, supabase):
    st.write(f"선택하신 **{len(target_names)}개**의 포트폴리오가 영구적으로 삭제됩니다.")
    st.warning("이 작업은 되돌릴 수 없습니다.")
    
    col_del1, col_del2 = st.columns(2)
    
    if col_del1.button("✅ 네, 삭제합니다", type="primary", use_container_width=True):
        try:
            target_ids = [opts[name]['id'] for name in target_names]
            # Supabase 'in' 쿼리로 일괄 삭제
            supabase.table("portfolios").delete().in_("id", target_ids).execute()
            
            logger.info(f"🗑️ 포트폴리오 일괄 삭제: {len(target_ids)}건")
            st.rerun()
        except Exception as e:
            st.error(f"삭제 중 오류 발생: {e}")
            
    if col_del2.button("취소", use_container_width=True):
        st.rerun()

# 💾 [추가된 함수] 덮어쓰기 확인 다이얼로그
@st.dialog("💾 기존 파일 덮어쓰기")
def confirm_overwrite_dialog(final_name, user_id, user_email, save_data, existing_id, supabase):
    """이미 같은 이름의 포트폴리오가 있을 때 띄우는 팝업"""
    st.write(f"이미 **'{final_name}'**이라는 이름의 포트폴리오가 존재합니다.")
    st.info("새로운 데이터로 덮어쓰시겠습니까?")
    
    col_ov1, col_ov2 = st.columns(2)
    
    if col_ov1.button("🎮 네, 덮어씁니다", type="primary", use_container_width=True):
        try:
            # 기존 ID를 찾아서 해당 데이터만 업데이트
            supabase.table("portfolios").update({
                "ticker_data": save_data, 
                "created_at": "now()" # 저장 시간 갱신
            }).eq("id", existing_id).execute()
            
            logger.info(f"🔄 기존 포트폴리오 덮어쓰기 완료: {final_name}")
            st.toast(f"'{final_name}' 파일을 성공적으로 갱신했습니다!", icon="✅")
            st.balloons()
            time.sleep(1.0)
            st.rerun()
        except Exception as e:
            st.error(f"저장 중 오류 발생: {e}")
            
    if col_ov2.button("아니요, 취소", use_container_width=True):
        st.rerun()

def main():
    inject_ga()
    
    # 1. 초기화 (세션 설정 + CSS 배전함 연결)
    init_session_state() 
    ui.load_css() 
    
    # 2. 안전 장치 (COPPA)
    #check_coppa_compliance() 
    
    logger.info("🚀 배당팽이 메인 엔진 가동")
    db.cleanup_old_tokens()

    # 2. 관리자 인증
    is_admin = False
    if st.query_params.get("admin", "false").lower() == "true":
        ADMIN_HASH = st.secrets["ADMIN_PASSWORD_HASH"]
        with st.expander("🔐 관리자 접속 (Admin)", expanded=False):
            password_input = st.text_input("비밀번호 입력", type="password")
            if password_input:
                if hashlib.sha256(password_input.encode()).hexdigest() == ADMIN_HASH:
                    is_admin = True
                    logger.info("🔑 관리자 모드 접속 성공")
                    st.success("관리자 모드 ON 🚀")
                else:
                    st.error("비밀번호 불일치")

    render_login_ui()
    
    # [수정] 3. 상단 통합 관제 구역 (로그인 & AI)
    # 로그인 여부에 따라 헤더 구성을 동적으로 변경하여 공간을 절약합니다.
    with st.container(border=True):
        col_auth, col_ai = st.columns([2, 1.2])
        
        with col_auth:
            if not st.session_state.get("is_logged_in", False):
                if "code" in st.query_params:
                     st.info("🔄 로그인 확인 중입니다...")
                else:
                    render_login_buttons(key_suffix="top_header")
            else:
                user = st.session_state.user_info
                nickname = user.email.split("@")[0] if user.email else "User"
                st.success(f"👋 **{nickname}**님, 환영합니다!")

        with col_ai:
            if st.button("🕵️ AI 로보어드바이저", use_container_width=True, type="primary"):
                if st.session_state.get("is_logged_in"):
                    st.session_state.ai_modal_open = True
                    st.session_state.wiz_step = 0
                    st.session_state.wiz_data = {}
                    if "ai_result_cache" in st.session_state:
                        del st.session_state.ai_result_cache
                else:
                    st.toast("🔒 로그인을 먼저 해주세요!", icon="👆")

    df_raw = logic.load_stock_data_from_csv()
    if df_raw.empty: 
        logger.error("❌ 데이터 로드 실패: CSV 파일이 비어있음")
        st.stop()

    if is_admin:
        render_admin_tools(df_raw)

    with st.spinner('⚙️ 배당 데이터베이스 엔진 가동 중...'):
        df = logic.load_and_process_data(df_raw, is_admin=is_admin)
        st.session_state['shared_df'] = df

    with st.sidebar:
        if not st.session_state.is_logged_in: st.markdown("---")
        
        menu = st.radio("📂 **메뉴 이동**", ["💰 배당금 계산기", "📅 월별 로드맵", "📃 전체 종목 리스트"], label_visibility="visible")
        
        st.markdown("---")
        
        expense_input = st.number_input(
            "💸 나의 월평균 지출 (만원)", 
            min_value=10, 
            value=st.session_state.monthly_expense, 
            step=10,
            help="이 수치는 배당 방어율 계산의 기준이 됩니다."
        )
        st.session_state.monthly_expense = expense_input

        st.markdown("---")

        with st.expander("📂 불러오기 / 관리", expanded=True):
            if not st.session_state.is_logged_in:
                st.caption("🔒 상단에서 로그인을 해주세요.")
            else:
                try:
                    uid = st.session_state.user_info.id
                    resp = supabase.table("portfolios").select("*").eq("user_id", uid).order("created_at", desc=True).execute()
                    if resp.data:
                        opts = {f"{p.get('name') or '이름없음'} ({p['created_at'][5:10]} {p['created_at'][11:16]})": p for p in resp.data}
                        
                        # [NEW] 삭제 모드 토글
                        is_delete_mode = st.toggle("🗑️ 포트폴리오 정리(삭제) 모드")

                        if is_delete_mode:
                            st.caption("삭제할 포트폴리오를 모두 선택하세요.")
                            # 다중 선택 박스
                            targets_to_delete = st.multiselect(
                                "삭제 목록 선택", 
                                options=list(opts.keys()),
                                placeholder="지울 항목들을 선택하세요",
                                label_visibility="collapsed"
                            )

                            if targets_to_delete:
                                if st.button(f"🚨 선택한 {len(targets_to_delete)}개 영구 삭제", type="primary", use_container_width=True):
                                    # 다이얼로그 호출
                                    confirm_delete_dialog(targets_to_delete, opts, supabase)
                            else:
                                st.button("🚨 삭제 버튼 (항목을 먼저 선택하세요)", disabled=True, use_container_width=True)

                        else:
                            # 기존 불러오기 모드
                            sel_name = st.selectbox("항목 선택", list(opts.keys()), label_visibility="collapsed")
                            
                            if st.button("📂 불러오기", use_container_width=True):
                                data = opts[sel_name]['ticker_data']
                                st.session_state.total_invest = int(data.get('total_money', 30000000))
                                st.session_state.selected_stocks = list(data.get('composition', {}).keys())
                                # 저장된 비중 불러오기 (없으면 무시)
                                saved_weights = data.get('composition', {})
                                st.session_state.ai_suggested_weights = saved_weights
                                st.session_state.monthly_expense = int(data.get('monthly_expense', 200))
                                
                                logger.info(f"📂 포트폴리오 로드: {sel_name}")
                                st.toast("성공적으로 불러왔습니다!", icon="✅")
                                time.sleep(0.5)
                                st.rerun()
                    else: 
                        st.caption("저장된 기록이 없습니다.")
                except Exception as e: 
                    st.error(f"불러오기 실패: {e}")

        st.markdown("---")

        with st.expander("📄 법적 고지 및 정책"):
            st.caption("본 서비스는 사용자의 안전한 이용을 위해 아래 정책을 준수합니다.")
            if st.button("🛡️ 개인정보 처리방침 확인", use_container_width=True):
                try:
                    with open("privacy.md", "r", encoding="utf-8") as f: st.markdown(f.read())
                except: st.error("정책 파일을 찾을 수 없습니다.")

        render_sidebar_footer()

    if menu == "💰 배당금 계산기":
        render_calculator_page(df)
    elif menu == "📅 월별 로드맵":
        render_roadmap_page(df)
    elif menu == "📃 전체 종목 리스트":
        render_stocklist_page(df)

    st.divider()
    st.caption("© 2025 **배당 팽이** | 실시간 데이터 기반 배당 대시보드")
    st.caption("First Released: 2025.12.31 | [📝 배당팽이 투자 일지 ](https://blog.naver.com/dividenpange) | [💌 앱 개선 의견 남기기](https://docs.google.com/forms/d/e/1FAIpQLSdEJWd4sYx-09wZk7gl86Sf7bMliT4X9R0eWTAqxjv_Mal8Jg/viewform?usp=header)")


if __name__ == "__main__":
    main()
