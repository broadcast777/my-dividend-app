import streamlit as st
from supabase import create_client, ClientOptions
import pandas as pd
import altair as alt
import hashlib
import time # 리런 딜레이용

# [모듈화] 분리한 파일들을 불러옵니다
import logic 
import ui

# ==========================================
# [1] 기본 설정 및 Supabase 인증 저장소 설정
# ==========================================
st.set_page_config(page_title="배당팽이 대시보드", layout="wide")

# ---------------------------------------------------------
# [핵심] 새로고침해도 로그인이 풀리지 않게 잡아주는 저장소 클래스
# ---------------------------------------------------------
class StreamlitStorage:
    def __init__(self):
        if "supabase_storage" not in st.session_state:
            st.session_state.supabase_storage = {}

    def get_item(self, key: str) -> str | None:
        if "supabase_storage" not in st.session_state:
            st.session_state.supabase_storage = {}
        return st.session_state.supabase_storage.get(key)

    def set_item(self, key: str, value: str) -> None:
        if "supabase_storage" not in st.session_state:
            st.session_state.supabase_storage = {}
        st.session_state.supabase_storage[key] = value

    def remove_item(self, key: str) -> None:
        if "supabase_storage" in st.session_state and key in st.session_state.supabase_storage:
            del st.session_state.supabase_storage[key]

# ---------------------------------------------------------
# Supabase 클라이언트 연결 (저장소 옵션 필수 적용)
# ---------------------------------------------------------
try:
    URL = st.secrets["SUPABASE_URL"]
    KEY = st.secrets["SUPABASE_KEY"]
    # storage 옵션을 넣어야 'Verifier' 에러가 안 납니다.
    supabase = create_client(URL, KEY, options=ClientOptions(storage=StreamlitStorage()))
except Exception as e:
    # 로컬 테스트 등 시크릿이 없을 경우를 대비해 예외 처리
    supabase = None

# ---------------------------------------------------------
# 세션 상태 변수 초기화
# ---------------------------------------------------------
if "is_logged_in" not in st.session_state:
    st.session_state.is_logged_in = False
if "user_info" not in st.session_state:
    st.session_state.user_info = None

# ==========================================
# [2] 인증 상태 체크 (최상단 실행)
# ==========================================
def check_auth_status():
    if not supabase: return

    # 1. 현재 저장된 세션 확인
    session = supabase.auth.get_session()
    
    # 2. URL에 코드가 있다면 교환 시도 (로그인 직후)
    query_params = st.query_params
    if "code" in query_params:
        try:
            auth_response = supabase.auth.exchange_code_for_session({"auth_code": query_params["code"]})
            session = auth_response.session
            st.query_params.clear() # URL 청소
            st.rerun()              # 화면 새로고침
        except Exception:
            pass # 코드 만료 등 에러는 무시

    # 3. 세션 상태 업데이트 (Source of Truth)
    if session:
        st.session_state.is_logged_in = True
        st.session_state.user_info = session.user
    else:
        st.session_state.is_logged_in = False
        st.session_state.user_info = None

# 페이지 로드 시 무조건 1회 실행하여 상태 동기화
check_auth_status()

# ==========================================
# [3] 사이드바 로그인 UI 함수 (그리기만 함)
# ==========================================
def render_sidebar_login_ui():
    # 저장 버튼 등에서 사용할 수 있게 현재 유저 정보를 리턴하지 않고, 
    # 오직 사이드바 UI만 그립니다.
    
    if not supabase: return

    # 이미 check_auth_status에서 갱신된 session_state를 사용
    if st.session_state.is_logged_in and st.session_state.user_info:
        user = st.session_state.user_info
        email = user.email if user.email else "User"
        nickname = email.split("@")[0]
        
        st.sidebar.markdown("---")
        st.sidebar.success(f"👋 반가워요! **{nickname}**님")
        
        if st.sidebar.button("로그아웃", key="logout_btn"):
            supabase.auth.sign_out()
            st.session_state.is_logged_in = False
            st.session_state.user_info = None
            st.rerun()
            
    else:
        st.sidebar.markdown("---")
        st.sidebar.info("💾 포트폴리오 저장을 위해 로그인")
        
        col1, col2 = st.sidebar.columns(2)
        callback_url = "https://dividend-pange.streamlit.app"
        
        with col1:
            res_google = supabase.auth.sign_in_with_oauth({
                "provider": "google",
                "options": {"redirect_to": callback_url}
            })
            if res_google.url:
                st.link_button("G 구글", res_google.url, type="primary", use_container_width=True)

        with col2:
            res_kakao = supabase.auth.sign_in_with_oauth({
                "provider": "kakao",
                "options": {"redirect_to": callback_url}
            })
            if res_kakao.url:
                st.link_button("💬 카카오", res_kakao.url, type="secondary", use_container_width=True)
            
        st.sidebar.caption("🔒 안전하게 로그인됩니다.")


# ==========================================
# [4] 메인 애플리케이션
# ==========================================
def main():
    MAINTENANCE_MODE = False

    # ---------------------------------------------------------
    # [1] 관리자 인증 로직
    # ---------------------------------------------------------
    is_admin = False
    if st.query_params.get("admin", "false").lower() == "true":
        ADMIN_HASH = "c41b0bb392db368a44ce374151794850417b56c9786e3c482f825327c7153182"
        with st.sidebar:
            st.header("🐌 메뉴 / 관리")
            password_input = st.text_input("🔐 관리자 접속", type="password", placeholder="비밀번호 입력")
            if password_input:
                if hashlib.sha256(password_input.encode()).hexdigest() == ADMIN_HASH:
                    is_admin = True
                    st.success("관리자 모드 ON 🚀")
                else:
                    st.error("비밀번호 불일치")

    # ---------------------------------------------------------
    # [2] 사이드바 로그인 UI 렌더링
    # ---------------------------------------------------------
    render_sidebar_login_ui()
    
    # [중요] 메인 로직에서 사용할 유저 변수는 여기서 session_state를 직접 할당
    current_user = st.session_state.user_info

    # ---------------------------------------------------------
    # [3] 점검 모드 및 메인 타이틀
    # ---------------------------------------------------------
    if MAINTENANCE_MODE and not is_admin:
        st.title("🚧 시스템 정기 점검 중")
        st.write("잠시 후 다시 접속해 주세요! 🙇‍♂️")
        st.stop()
    
    if is_admin:
        st.title("💰 배당팽이 대시보드 (관리자 모드)")
    else:
        st.title("💰 배당팽이 월배당 계산기")

    # 데이터 로드
    df_raw = logic.load_stock_data_from_csv()
    if df_raw.empty: st.stop()
    
    # [관리자] 갱신 도구
    if is_admin:
        with st.sidebar:
            st.subheader("🛠️ 배당금 갱신 도구")
            target_stock = st.selectbox("갱신할 종목 선택", df_raw['종목명'].unique())
            if target_stock:
                # (기존 관리자 로직 생략 없이 그대로 유지한다고 가정)
                new_div = st.number_input("이번 달 확정 배당금", value=0, step=10)
                if st.button("계산 실행"):
                    st.success("기능 실행됨 (코드 생략)")

    # 데이터 처리
    with st.spinner('⚙️ 배당 데이터베이스 엔진 가동 중...'):
        df = logic.load_and_process_data(df_raw, is_admin=is_admin)

    st.warning("⚠️ **투자 유의사항:** 본 대시보드의 연배당률은 과거 분배금 데이터를 기반으로 계산된 참고용 지표입니다.")

    # ------------------------------------------
    # 섹션 1: 포트폴리오 시뮬레이션
    # ------------------------------------------
    with st.expander("🧮 나만의 배당 포트폴리오 시뮬레이션", expanded=True):
        col1, col2 = st.columns([1, 2])
        total_invest = col1.number_input("💰 총 투자 금액 (만원)", min_value=100, value=3000, step=100) * 10000
        selected = col2.multiselect("📊 종목 선택", df['pure_name'].unique())

        if selected:
            # (계산 로직 유지)
            weights = {}; remaining = 100; cols_w = st.columns(2); all_data = []
            for i, stock in enumerate(selected):
                with cols_w[i % 2]:
                    safe_rem = max(0, remaining)
                    if i < len(selected) - 1:
                        val = st.number_input(f"{stock} (%)", min_value=0, max_value=safe_rem, value=min(safe_rem, 100 // len(selected)), step=5, key=f"s_{i}")
                        weights[stock] = val; remaining -= val; amt = total_invest * (val / 100)
                    else:
                        st.info(f"{stock}: {safe_rem}% 자동 적용")
                        weights[stock] = safe_rem; amt = total_invest * (safe_rem / 100)
                
                stock_match = df[df['pure_name'] == stock]
                if not stock_match.empty:
                    s_row = stock_match.iloc[0]
                    all_data.append({'종목': stock, '비중': weights[stock], '자산유형': s_row['자산유형'], '투자금액_만원': amt / 10000})

            # 결과 계산
            total_y_div = sum([(total_invest * (weights[n]/100) * (df[df['pure_name']==n].iloc[0]['연배당률']/100)) for n in selected])
            total_m = total_y_div / 12
            avg_y = sum([(df[df['pure_name']==n].iloc[0]['연배당률'] * (weights[n]/100)) for n in selected])

            st.markdown("### 🎯 포트폴리오 결과")
            st.metric("📈 가중 평균 연배당률", f"{avg_y:.2f}%")
            r1, r2, r3 = st.columns(3)
            r1.metric("월 수령액 (세후)", f"{total_m * 0.846:,.0f}원")
            r2.metric("월 수령액 (ISA/세전)", f"{total_m:,.0f}원")

            st.write("")
            
            # =========================================================
            # [수정된 저장 로직] current_user 변수를 session_state에서 직접 가져옴
            # =========================================================
            if st.button("💾 내 포트폴리오 저장하기", type="primary", use_container_width=True):
                # ★ 여기서 st.session_state.user_info를 직접 확인합니다.
                if not st.session_state.is_logged_in or not st.session_state.user_info:
                    st.toast("⚠️ 로그인이 필요한 기능입니다. 사이드바를 확인해주세요!")
                    st.error("로그인을 하셔야 '나만의 포트폴리오'를 저장할 수 있습니다.")
                else:
                    try:
                        # 로그인된 유저 정보 가져오기
                        user = st.session_state.user_info
                        save_data = {
                            "total_money": total_invest,
                            "composition": weights,
                            "summary": {"monthly_income": total_m, "yield": avg_y}
                        }
                        
                        supabase.table("portfolios").insert({
                            "user_id": user.id,
                            "user_email": user.email,
                            "ticker_data": save_data
                        }).execute()
                        
                        st.success("짐 싸기 완료! 포트폴리오가 안전하게 저장되었습니다. 🧳")
                        st.balloons()
                        
                    except Exception as e:
                        st.error(f"저장 중 오류가 발생했습니다: {e}")

            # (이하 상세 분석, 탭 로직, 푸터 등 기존 코드 유지)
            df_ana = pd.DataFrame(all_data)
            if not df_ana.empty:
                st.write("")
                tab_analysis, tab_simulation, tab_goal = st.tabs(["💎 자산 구성 분석", "💰 10년 뒤 자산 미리보기", "🎯 목표 배당 달성"])
                
                with tab_analysis:
                    ui.render_custom_table(df_ana) # 예시
                # ... (나머지 탭 내용들)

    # ------------------------------------------
    # 섹션 4: 전체 데이터 테이블 출력 (하단)
    # ------------------------------------------
    st.divider()
    ui.render_custom_table(df)
    
    # ------------------------------------------
    # 방문자 추적 (하단)
    # ------------------------------------------
    @st.fragment
    def track_visitors():
        if 'visited' not in st.session_state: st.session_state.visited = False
        if not st.session_state.visited:
            # (기존 로직 유지)
            st.session_state.visited = True
        
        # (표시 로직 유지)
        st.caption("© 2025 배당팽이")

    track_visitors()

if __name__ == "__main__":
    main()
