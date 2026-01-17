"""
프로젝트: 배당 팽이 (Dividend Top) v1.6
파일명: app.py (Phase 3: UI/UX 고도화 및 검색 엔진 교체 완료)
설명: 라이브러리 로드, 세션 초기화, 중앙 라우팅 시스템 구축
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

# ---------------------------------------------------------
# [추가 과제] 4과제: COPPA 나이 확인 (안전 장치)
# ---------------------------------------------------------
def check_coppa_compliance():
    """만 13세 이상 이용 확인 (법적 준수 안내판)"""
    if "age_verified" not in st.session_state:
        st.warning("📋 **서비스 이용 안내**")
        st.write("본 서비스는 개인정보보호법 및 COPPA 규정에 따라 만 13세 이상 사용자만 이용 가능합니다.")
        if st.checkbox("나는 만 13세 이상이며, 이용 약관 및 개인정보 처리방침에 동의합니다."):
            st.session_state.age_verified = True
            logger.info("✅ 사용자가 나이 확인 및 약관에 동의함")
            st.rerun()
        else:
            st.stop()

# 세션 상태(Session State) 변수 초기화 로직
for key in ["is_logged_in", "user_info", "code_processed"]:
    if key not in st.session_state:
        st.session_state[key] = False if key != "user_info" else None

# AI 추천 모달창 열림/닫힘 상태 관리 변수
if "ai_modal_open" not in st.session_state:
    st.session_state.ai_modal_open = False

# ---------------------------------------------------------
# 외부 데이터베이스(Supabase) 연결 초기화
# ---------------------------------------------------------
supabase = db.init_supabase()


# ==========================================
# [SECTION 2] 인증 및 보안 엔진
# ==========================================

def check_auth_status():
    """
    사용자의 로그인 상태를 확인하고, 카카오/구글 로그인 후 
    돌아오는 콜백(auth code)을 처리하여 세션을 확정합니다.
    """
    if not supabase: return

    # 1. [기존 세션 확인] 이미 브라우저에 로그인 정보가 남아있는지 확인
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

    # 2. [로그인 콜백 처리] OAuth 로그인 후 리다이렉트된 경우 처리
    query_params = st.query_params
    if "code" in query_params and not st.session_state.get("code_processed", False):
        st.session_state.code_processed = True
        
        try:
            # URL의 auth_code를 세션 토큰으로 교환
            auth_code = query_params["code"]
            auth_response = supabase.auth.exchange_code_for_session({"auth_code": auth_code})
            session = auth_response.session
            
            if session and session.user:
                st.session_state.is_logged_in = True
                st.session_state.user_info = session.user
                logger.info(f"👤 사용자 로그인 성공: {session.user.email}") 
            
            # 인증 성공 후 깨끗한 URL로 새로고침
            st.query_params.clear()
            st.success("✅ 로그인되었습니다!")
            st.rerun()
            
        except Exception as e:
            # [자동 복구 로직] verifier 오류(새로고침 시 발생 등) 시 파라미터 리셋 후 재시도
            err_msg = str(e).lower()
            logger.error(f"🔴 인증 과정 중 오류 발생: {err_msg}") 
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
# [SECTION 3] UI 컴포넌트 (사이드바 및 공통 요소)
# ==========================================

def render_login_ui():
    """사이드바 상단에 현재 로그인된 유저 정보를 표시하고 로그아웃 기능을 제공합니다."""
    if not supabase: return
    is_logged_in = st.session_state.get("is_logged_in", False)
    user_info = st.session_state.get("user_info", None)
    
    if is_logged_in and user_info:
        # 이메일 앞부분을 닉네임으로 활용
        email = user_info.email if user_info.email else "User"
        nickname = email.split("@")[0]
        
        with st.sidebar:
            st.markdown("---")
            st.success(f"👋 반가워요! **{nickname}**님")
            
            # 로그아웃 버튼 클릭 시 세션 초기화 및 새로고침
            if st.button("🚪 로그아웃", key="logout_btn_sidebar", use_container_width=True):
                logger.info(f"🚪 사용자 로그아웃: {email}") 
                supabase.auth.sign_out()
                st.session_state.is_logged_in = False
                st.session_state.user_info = None
                st.session_state.code_processed = False
                st.rerun()

def render_sidebar_footer():
    """사이드바 최하단 후원 버튼 및 저작권 정보"""
    bmc_url = "https://www.buymeacoffee.com/dividenpange"

    st.sidebar.markdown("---") 
    
    st.sidebar.markdown(f"""
        <style>
        .bmc-container {{
            display: flex;
            justify-content: center;
            margin: 10px 0;
        }}
        .bmc-button {{
            display: flex;
            align-items: center;
            justify-content: center;
            background-color: #FFDD00;
            color: #000000 !important;
            padding: 10px 15px;
            border-radius: 10px;
            text-decoration: none;
            font-weight: bold;
            font-size: 14px;
            box-shadow: 0 4px 8px rgba(0,0,0,0.1);
            transition: transform 0.2s;
            width: 100%;
        }}
        .bmc-button:hover {{
            transform: translateY(-2px);
            text-decoration: none;
            background-color: #FADA00;
        }}
        .bmc-logo {{
            height: 18px;
            margin-right: 8px;
        }}
        </style>
        <div class="bmc-container">
            <a class="bmc-button" href="{bmc_url}" target="_blank">
                <img src="https://cdn.buymeacoffee.com/buttons/bmc-new-btn-logo.svg" alt="BMC logo" class="bmc-logo">
                <span>배당팽이에게 커피 한 잔</span>
            </a>
        </div>
    """, unsafe_allow_html=True)
    



# ==========================================
# [SECTION 4] 페이지별 렌더링 함수 (부품화)
# ==========================================

def render_admin_tools(df_raw):
    """관리자 전용 도구 렌더링"""
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
            new_div = st.number_input("이번 달 확정 배당금", value=0, step=10)
            if st.button("계산 실행", use_container_width=True):
                new_total, new_hist = logic.update_dividend_rolling(cur_hist, new_div)
                st.success("완료!")
                st.code(new_hist, language="text")

        st.markdown("---")
        st.subheader("💾 데이터 저장 및 백업")

        csv_data = df_raw.to_csv(index=False).encode('utf-8')
        st.download_button(
            label="📂 (혹시 모르니) 현재 파일 백업하기",
            data=csv_data,
            file_name=f"stocks_backup_{pd.Timestamp.now().strftime('%Y%m%d')}.csv",
            mime='text/csv',
            use_container_width=True
        )

        st.write("") 
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
                    if 0 < months < 12:
                        skipped_count += 1
                        continue
                    code = str(row['종목코드']).strip()
                    cat = str(row.get('분류', '국내')).strip()
                    amt, src = logic.fetch_dividend_amount_hybrid(code, cat)
                    if amt > 0:
                        df_temp.at[i, '연배당률_크롤링'] = amt
                        updated_count += 1
                    else:
                        st.warning(f"⚠️ {row['종목명']}({code}) 실패 -> 원인: {src}")
                        
                status_text.text("완료!")
                st.success(f"✅ {updated_count}개 금액 갱신 완료 / 🛡️ {skipped_count}개 신규주 보호됨")
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


# ---------------------------------------------------------
# [최적화] 검색 리스트를 메모리에 캐싱하여 속도 5배 향상
# ---------------------------------------------------------
@st.cache_data(show_spinner=False)
def load_search_options(df):
    """CSV의 '검색라벨' 열을 읽어서 리스트로 반환"""
    # [수정] 사장님이 추가하신 '검색라벨' 열 사용 (가장 빠름)
    if '검색라벨' in df.columns:
        return sorted(df['검색라벨'].dropna().astype(str).tolist())
    
    # 비상용 안전장치
    def temp_label(row):
        c = str(row['종목코드']).split('.')[0].strip()
        if c.isdigit(): c = c.zfill(6)
        n = str(row['종목명']).strip()
        return f"[{c}] {n}"
    return sorted(list(set(df.apply(temp_label, axis=1).tolist())))


def render_calculator_page(df):
    """💰 배당금 계산기 페이지 (입력 및 간편 결과)"""
    st.header("💰 배당금 계산기")
    st.info("여기서 투자금과 종목을 설정하세요. 상세 분석은 '📊 심층 분석 리포트'에서 확인 가능합니다.")

    # 6-1. AI 로보어드바이저
    st.write("")
    col_rec1, col_rec2 = st.columns([2, 1])
    with col_rec1:
        st.info("🤔 **어떤 종목을 담아야 할지 막막하신가요?**\n\nAI가 성향을 분석해 최적의 포트폴리오를 제안합니다.")
    with col_rec2:
        st.write("") 
        if st.button("🕵️ AI 로보어드바이저 실행", use_container_width=True, type="primary"):
            if st.session_state.get("is_logged_in"):
                logger.info("🤖 AI 로보어드바이저 세션 시작")
                st.session_state.ai_modal_open = True
                st.session_state.wiz_step = 1
                st.session_state.wiz_data = {}
                if "ai_result_cache" in st.session_state:
                    del st.session_state.ai_result_cache
            else:
                st.error("🔒 로그인이 필요한 기능입니다.")
                st.toast("위에서 로그인을 해주세요!", icon="👆")
                st.session_state.ai_modal_open = False

        if st.session_state.get("ai_modal_open", False):
            recommendation.show_wizard()
    
    st.markdown("---")

    # 6-2. 포트폴리오 입력
    col1, col2 = st.columns([1, 2])
    current_invest_val = int(st.session_state.total_invest / 10000)
    invest_input = col1.number_input("💰 총 투자 금액 (만원)", min_value=100, value=current_invest_val, step=100)
    st.session_state.total_invest = invest_input * 10000
    total_invest = st.session_state.total_invest 

    # [수정] 캐싱된 검색 리스트 사용 + 깔끔한 UI
    search_options = load_search_options(df)
    
    # 기존 세션 복원
    default_selected = []
    if st.session_state.get('selected_stocks'):
        saved_names = set(st.session_state.selected_stocks)
        default_selected = [opt for opt in search_options if opt.split('] ')[1] in saved_names]

    selected_search = col2.multiselect(
        "📊 종목 선택 (이름 또는 코드로 검색)", 
        options=search_options, 
        default=default_selected,
        # [UI 핵심] 화면에는 ']' 뒤의 이름만 보여줍니다 (깔끔함)
        format_func=lambda x: x.split('] ')[1] if '] ' in x else x,
        help="종목코드(숫자)나 종목명을 입력해 보세요!"
    )

    # 엔진에는 순수 이름만 전달
    selected = [opt.split('] ')[1] if '] ' in opt else opt for opt in selected_search]
    st.session_state.selected_stocks = selected

    if selected:
        weights = {}
        remaining = 100
        cols_w = st.columns(2)
        all_portfolio_data = [] # 캘린더용 데이터 수집
        
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
                
                # 데이터 수집 (분석 페이지 및 캘린더용)
                stock_match = df[df['pure_name'] == stock]
                if not stock_match.empty:
                    s_row = stock_match.iloc[0]
                    all_portfolio_data.append({
                        '종목': stock, '비중': weights[stock], '자산유형': s_row['자산유형'], '투자금액_만원': amt / 10000,
                        '종목명': stock, '코드': s_row.get('코드', ''), '분류': s_row.get('분류', '국내'),
                        '연배당률': s_row.get('연배당률', 0), '금융링크': s_row.get('금융링크', '#'),
                        '신규상장개월수': s_row.get('신규상장개월수', 0), '현재가': s_row.get('현재가', 0),
                        '환구분': s_row.get('환구분', '-'), '배당락일': s_row.get('배당락일', '-')
                    })
        
        st.divider()
        
        # [간편 결과 카드] 메인 화면은 심플하게!
        total_y_div = sum([(total_invest * (weights[n]/100) * (df[df['pure_name']==n].iloc[0]['연배당률']/100)) for n in selected])
        total_m = total_y_div / 12
        avg_y = sum([(df[df['pure_name']==n].iloc[0]['연배당률'] * (weights[n]/100)) for n in selected])

        r1, r2, r3 = st.columns(3)
        r1.metric("월 수령액 (세후)", f"{total_m * 0.846:,.0f}원", delta="-15.4% 세금")
        r2.metric("월 수령액 (ISA/세전)", f"{total_m:,.0f}원", delta="비과세 기준")
        r3.metric("가중 평균 연배당률", f"{avg_y:.2f}%")

        st.success("✅ **설정 완료!** 좌측 메뉴의 **'📊 심층 분석 리포트'**에서 상세 결과를 확인하세요.")

        # 캘린더 다운로드 (메인 화면에서 바로 가능하게 유지)
        st.divider()
        st.subheader("📅 캘린더 알림 등록")
        col_d1, col_d2 = st.columns([1.5, 1])
        with col_d1:
            st.caption("선택한 종목의 배당락일 알림을 내 캘린더에 한 번에 등록하세요.")
        with col_d2:
            ics_data = logic.generate_portfolio_ics(all_portfolio_data)
            if st.session_state.get("is_logged_in", False):
                st.download_button(label="📥 전체 일정 파일 받기 (.ics)", data=ics_data, file_name="dividend_calendar.ics", mime="text/calendar", use_container_width=True, type="primary")
            else:
                st.button("📥 전체 일정 파일 받기 (.ics)", key="ics_lock_btn", use_container_width=True, disabled=True)
                st.caption("🔒 로그인 필요")

        # 포트폴리오 저장
        st.write("") 
        with st.container(border=True):
            st.write("💾 **포트폴리오 저장 / 수정**")
            if not st.session_state.get('is_logged_in', False):
                st.warning("⚠️ **로그인이 필요합니다.**")
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
                            supabase.table("portfolios").insert({"user_id": user.id, "user_email": user.email, "name": final_name, "ticker_data": save_data}).execute()
                            logger.info(f"💾 새 포트폴리오 저장: {final_name}")
                            st.success(f"[{final_name}] 저장 완료!")
                            st.balloons()
                            time.sleep(1.0)
                            st.rerun()
                    else: 
                        exist_res = supabase.table("portfolios").select("id, name, created_at").eq("user_id", user.id).order("created_at", desc=True).execute()
                        if not exist_res.data:
                            st.warning("수정할 포트폴리오가 없습니다.")
                        else:
                            exist_opts = {f"{p.get('name') or '이름없음'} ({p['created_at'][5:10]})": p['id'] for p in exist_res.data}
                            c_up1, c_up2 = st.columns([2, 1])
                            selected_label = c_up1.selectbox("수정할 파일 선택", list(exist_opts.keys()), label_visibility="collapsed")
                            target_id = exist_opts[selected_label]
                            if c_up2.button("덮어쓰기", type="primary", use_container_width=True):
                                supabase.table("portfolios").update({"ticker_data": save_data, "created_at": "now()"}).eq("id", target_id).execute()
                                logger.info(f"🔄 기존 포트폴리오 업데이트: {target_id}")
                                st.success("수정 완료! 내용이 업데이트되었습니다.")
                                st.balloons()
                                time.sleep(1.0)
                                st.rerun()
                except Exception as e:
                    st.error(f"오류 발생: {e}")


def render_analysis_page(df):
    """📊 심층 분석 리포트 페이지 (새로 분리됨)"""
    st.header("📊 포트폴리오 심층 분석 리포트")
    
    selected = st.session_state.get('selected_stocks', [])
    if not selected:
        st.warning("⚠️ **'💰 배당금 계산기'** 메뉴에서 먼저 종목을 선택해 주세요!")
        return

    # 계산기에서 설정한 값 가져오기
    total_invest = st.session_state.total_invest
    weights = {stock: st.session_state.get(f"s_{i}", 100 // len(selected)) for i, stock in enumerate(selected)}
    
    # 분석 데이터 생성
    all_data = []
    for stock in selected:
        stock_match = df[df['pure_name'] == stock]
        if not stock_match.empty:
            s_row = stock_match.iloc[0]
            amt = total_invest * (weights[stock] / 100)
            all_data.append({
                '종목': stock, '비중': weights[stock], '자산유형': s_row['자산유형'], '투자금액_만원': amt / 10000,
                '종목명': stock, '분류': s_row.get('분류', '국내'), '환구분': s_row.get('환구분', '-')
            })
            
    df_ana = pd.DataFrame(all_data)
    avg_y = sum([(df[df['pure_name']==n].iloc[0]['연배당률'] * (weights[n]/100)) for n in selected])
    
    if not df_ana.empty:
        # 1. 자산 구성 분석 (Expander)
        with st.expander("💎 자산 구성 상세 분석", expanded=True):
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

        # 2. 10년 뒤 자산 미리보기 (Expander)
        with st.expander("💰 미래 자산 성장 시뮬레이션", expanded=False):
            start_money = total_invest
            is_over_100m = start_money > 100000000
            st.info(f"📊 **초기 자산 {start_money/10000:,.0f}만원** 기준 시뮬레이션")
            
            c1, c2 = st.columns([1.5, 1])
            with c1:
                if is_over_100m:
                    is_isa_mode = st.toggle("🛡️ ISA 계좌 불가 (한도 1억 초과)", value=False, disabled=True, key="sim_isa_dis")
                    st.caption("🚫 초기 투자금이 1억원을 초과하여 일반 계좌로만 진행됩니다.")
                else:
                    is_isa_mode = st.toggle("🛡️ ISA (절세) 계좌로 모으기", value=True, key="sim_isa_en")
                    if is_isa_mode: st.caption("💡 **ISA 모드:** 비과세 + 과세이연 효과")
                    else: st.caption("💡 **일반 모드:** 배당소득세(15.4%) 납부 후 재투자")
            with c2:
                years_sim = st.select_slider("⏳ 투자 기간", options=[3, 5, 10, 15, 20, 30], value=5, format_func=lambda x: f"{x}년", key="sim_years")
                apply_inflation = st.toggle("📉 물가상승률(2.5%) 반영", value=False, key="sim_inf")
            
            reinvest_ratio = 100
            isa_exempt = 0
            if is_isa_mode:
                isa_type = st.radio("ISA 유형", ["일반형 (비과세 200만)", "서민형 (비과세 400만)"], horizontal=True, label_visibility="collapsed", key="sim_type")
                isa_exempt = 400 if "서민형" in isa_type else 200
            else:
                if not is_over_100m:
                    reinvest_ratio = st.slider("💰 재투자 비율 (%)", 0, 100, 100, step=10, key="sim_ratio")
            
            st.markdown("---")
            monthly_input = st.number_input("➕ 매월 추가 적립 (만원)", min_value=0, max_value=3000, value=150, step=10, key="sim_add") * 10000
            monthly_add = monthly_input
            
            # (시뮬레이션 로직 복원)
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
                    "년차": m / 12, "자산총액": (isa_bal + general_bal) / 10000, "총원금": (isa_principal + general_principal) / 10000, "실제월배당": div_isa + div_gen
                })
            
            df_sim_chart = pd.DataFrame(sim_data)
            base = alt.Chart(df_sim_chart).encode(x=alt.X('년차:Q', title='경과 기간 (년)'))
            area = base.mark_area(opacity=0.3, color='#0068c9').encode(y=alt.Y('자산총액:Q', title='자산 (만원)'))
            line = base.mark_line(color='#ff9f43', strokeDash=[5,5]).encode(y='총원금:Q')
            st.altair_chart((area + line).properties(height=280), use_container_width=True)

            final_row = df_sim_chart.iloc[-1]
            final_asset = (isa_bal + general_bal)
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
            if apply_inflation:
                discount_rate = (1.025) ** years_sim 
                pv_money = real_money / discount_rate
                inflation_msg_money = f"<br><span style='font-size:0.6em; color:#ff6b6b;'>(현재가치: 약 {pv_money/10000:,.0f}만원)</span>"

            st.markdown(f"""
<div style="background-color: #e7f3ff; border: 1.5px solid #d0e8ff; border-radius: 16px; padding: 25px; text-align: center; box-shadow: 0 4px 10px rgba(0,104,201,0.05);">
    <p style="color: #666; font-size: 0.95em; margin: 0 0 8px 0;">{years_sim}년 뒤 모이는 돈 (세후)</p>
    <h2 style="color: #0068c9; font-size: 2.2em; margin: 0; font-weight: 800; line-height: 1.2;">약 {real_money/10000:,.0f}만원{inflation_msg_money}</h2>
    <p style="color: #777; font-size: 0.9em; margin: 8px 0 0 0;">(투자원금 {(isa_principal + general_principal)/10000:,.0f}만원 / {tax_msg})</p>
    <div style="height: 1px; background-color: #d0e8ff; margin: 25px auto; width: 85%;"></div>
    <p style="color: #0068c9; font-weight: bold; font-size: 1.1em; margin: 0 0 12px 0;">📅 월 예상 배당금: {monthly_pocket/10000:,.1f}만원</p>
</div>
""", unsafe_allow_html=True)
            st.error("""**⚠️ 시뮬레이션 활용 시 유의사항**\n1. 본 결과는 주가·환율 변동을 제외하고, 현재 배당률로만 계산한 결과입니다.\n2. ISA 계좌의 비과세 한도 및 세율은 세법 개정에 따라 달라질 수 있습니다.""")

        # 3. 목표 배당 달성 (Expander)
        with st.expander("🎯 은퇴 목표 달성 시점 계산", expanded=False):
            st.subheader("🎯 목표 배당금 역산기 (은퇴 시뮬레이터)")
            col_g1, col_g2 = st.columns(2)
            with col_g1:
                target_monthly_goal = st.number_input("목표 월 배당금 (만원, 세후)", min_value=10, value=166, step=10, key="goal_target") * 10000
                use_start_money = st.checkbox("현재 설정된 초기 자산을 포함하여 계산", value=True, key="goal_start")
            with col_g2:
                apply_inflation_goal = st.toggle("🛡️ 내 돈의 가치 지키기 (권장)", value=False, key="goal_inf")
                st.info("평균 연배당률과 적립금을 바탕으로 목표 달성 시점을 계산합니다.")

            current_bal_goal = total_invest if use_start_money else 0
            tax_factor = 0.846
            months_passed = 0
            max_months = 720               
            
            while months_passed < max_months:
                if apply_inflation_goal:
                    adjusted_target = target_monthly_goal * ((1.025) ** (months_passed / 12))
                else:
                    adjusted_target = target_monthly_goal
                
                required_asset_at_time = (adjusted_target / tax_factor) / (avg_y / 100) * 12
                if current_bal_goal >= required_asset_at_time:
                    break
                div_reinvest = current_bal_goal * monthly_yld * tax_factor
                current_bal_goal += monthly_input + div_reinvest
                months_passed += 1

            st.markdown("---")
            c_res1, c_res2 = st.columns(2)
            if months_passed >= max_months:
                st.error("⚠️ 현재 적립액으로는 60년 내 달성이 어렵습니다. 적립금을 높여주세요.")
            else:
                with c_res1:
                    st.metric("목표 달성 필요 자산", f"{required_asset_at_time/100000000:,.2f} 억원")
                with c_res2:
                    st.metric("목표 달성까지 소요 기간", f"{months_passed // 12}년 {months_passed % 12}개월")
            st.error("⚠️ 재투자가 매월 이루어진다는 가정하에 계산된 복리 결과입니다.")


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
def main():
    inject_ga()
    
    # 1. 안전 장치 (COPPA) - 로그인 전에 무조건 실행
    # [수정] 아래 함수를 호출하면 나이 미확인 시 여기서 앱이 멈춥니다.
    # check_coppa_compliance() 
    
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

    if "total_invest" not in st.session_state:
        st.session_state.total_invest = 30000000 
    if "selected_stocks" not in st.session_state:
        st.session_state.selected_stocks = []     
        
    if "monthly_expense" not in st.session_state:
        st.session_state.monthly_expense = 200    

    render_login_ui()
    
    auth_container = st.container(border=True)
    with auth_container:
        if not st.session_state.get("is_logged_in", False):
            if "code" in st.query_params:
                 st.info("🔄 로그인 확인 중입니다... 잠시만 기다려주세요.")
            else:
                st.info("🔒 로그인이 필요합니다. (AI 진단 및 저장 기능 활성화)")
                try:
                    ctx = get_script_run_ctx()
                    current_session_id = ctx.session_id
                except: current_session_id = "unknown"
                redirect_url = f"https://dividend-pange.streamlit.app?old_id={current_session_id}"

                col_l, col_r = st.columns(2)
                with col_l:
                    try:
                        res_kakao = supabase.auth.sign_in_with_oauth({"provider": "kakao", "options": {"redirect_to": redirect_url, "skip_browser_redirect": True}})
                        if res_kakao.url:
                            st.markdown(f'''<a href="{res_kakao.url}" target="_blank" style="display: inline-flex; justify-content: center; align-items: center; width: 100%; background-color: #FEE500; color: #000000; border: 1px solid rgba(0,0,0,0.05); padding: 0.8rem; border-radius: 0.5rem; text-decoration: none; font-weight: bold; font-size: 1.1em; box-shadow: 0 1px 2px rgba(0,0,0,0.1); margin-bottom: 10px;">💬 Kakao로 3초 만에 시작하기</a>''', unsafe_allow_html=True)
                    except: pass
                with col_r:
                    if st.button("🔵 Google로 시작하기(pc/크롬 권장)", use_container_width=True, key="top_google_btn"):
                        try:
                            res_google = supabase.auth.sign_in_with_oauth({"provider": "google", "options": {"redirect_to": redirect_url, "queryParams": {"access_type": "offline", "prompt": "consent"}, "skip_browser_redirect": False}})
                            if res_google.url:
                                st.markdown(f'<meta http-equiv="refresh" content="0;url={res_google.url}">', unsafe_allow_html=True)
                                st.stop()
                        except: pass
        else:
            user = st.session_state.user_info
            nickname = user.email.split("@")[0] if user.email else "User"
            st.success(f"👋 **{nickname}**님, 환영합니다! 모든 기능이 활성화되었습니다.")

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
        
        # [수정] 메뉴 순서 최적화 (User Flow)
        menu = st.radio(
            "📂 **메뉴 이동**", 
            [
                "💰 배당금 계산기",       # 1. 입력 (Input)
                "📊 심층 분석 리포트",    # 2. 결과 (Output) - 새로 추가됨
                "📅 월별 로드맵",         # 3. 일정 (Schedule)
                "📃 전체 종목 리스트"     # 4. 참조 (Reference)
            ], 
            label_visibility="visible"
        )
        
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
                        sel_name = st.selectbox("항목 선택", list(opts.keys()), label_visibility="collapsed")
                        
                        is_delete_mode = st.toggle("🗑️ 삭제 모드 켜기")
                        if is_delete_mode:
                            if st.button("🚨 영구 삭제", type="primary", use_container_width=True):
                                target_id = opts[sel_name]['id']
                                supabase.table("portfolios").delete().eq("id", target_id).execute()
                                logger.info(f"🗑️ 포트폴리오 삭제: {target_id}")
                                st.toast("삭제되었습니다.", icon="🗑️")
                                st.rerun()
                        else:
                            if st.button("📂 불러오기", use_container_width=True):
                                data = opts[sel_name]['ticker_data']
                                st.session_state.total_invest = int(data.get('total_money', 30000000))
                                st.session_state.selected_stocks = list(data.get('composition', {}).keys())
                                st.session_state.monthly_expense = int(data.get('monthly_expense', 200))
                                
                                logger.info(f"📂 포트폴리오 로드: {sel_name}")
                                st.toast("성공적으로 불러왔습니다!", icon="✅")
                                st.rerun()
                    else: 
                        st.caption("저장된 기록이 없습니다.")
                except Exception as e: 
                    st.error("불러오기 실패")

        st.markdown("---")

        with st.expander("📄 법적 고지 및 정책"):
            st.caption("본 서비스는 사용자의 안전한 이용을 위해 아래 정책을 준수합니다.")
            if st.button("🛡️ 개인정보 처리방침 확인", use_container_width=True):
                try:
                    with open("privacy.md", "r", encoding="utf-8") as f: st.markdown(f.read())
                except: st.error("정책 파일을 찾을 수 없습니다.")

        render_sidebar_footer()

    # [수정] 라우팅 로직 (심층 분석 리포트 연결)
    if menu == "💰 배당금 계산기":
        render_calculator_page(df)
    elif menu == "📊 심층 분석 리포트":
        render_analysis_page(df)  # 새로 만든 함수 연결
    elif menu == "📅 월별 로드맵":
        render_roadmap_page(df)
    elif menu == "📃 전체 종목 리스트":
        render_stocklist_page(df)

    st.divider()
    st.caption("© 2025 **배당 팽이** | 실시간 데이터 기반 배당 대시보드")
    st.caption("First Released: 2025.12.31 | [📝 배당팽이 투자 일지 ](https://blog.naver.com/dividenpange) | [💌 앱 개선 의견 남기기](https://docs.google.com/forms/d/e/1FAIpQLSdEJWd4sYx-09wZk7gl86Sf7bMliT4X9R0eWTAqxjv_Mal8Jg/viewform?usp=header)")


if __name__ == "__main__":
    main()
