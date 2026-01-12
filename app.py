import streamlit as st
from supabase import create_client, ClientOptions
import pandas as pd
import altair as alt
import hashlib
import json
import os
from pathlib import Path
import random 

# [모듈화] 분리한 파일들을 불러옵니다
import logic 
import ui

# ==========================================
# [1] 기본 설정
# ==========================================
st.set_page_config(
    page_title="배당팽이", 
    page_icon="💰",
    layout="wide",
    initial_sidebar_state="collapsed" 
)

# ---------------------------------------------------------
# [스타일] 토스(Toss) 스타일 (모바일 최적화)
# ---------------------------------------------------------
st.markdown("""
<style>
    html, body, [class*="css"] {
        font-family: 'Pretendard', -apple-system, BlinkMacSystemFont, system-ui, Roboto, sans-serif;
        word-break: keep-all; 
    }
    header {visibility: hidden;}
    
    h1 {
        font-weight: 800 !important;
        letter-spacing: -1px !important;
        padding-top: 10px !important;
    }
    
    @media (max-width: 640px) {
        h1 { font-size: 26px !important; }
        .toss-main { font-size: 28px !important; }
        .toss-card { padding: 20px 15px !important; }
    }

    .toss-card {
        background-color: #ffffff;
        border-radius: 20px;
        padding: 30px 24px;
        box-shadow: 0 4px 20px rgba(0,0,0,0.05);
        border: 1px solid #f2f4f6;
        margin-bottom: 20px;
        text-align: center;
    }
    .toss-sub {
        color: #8b95a1;
        font-size: 15px;
        margin-bottom: 5px;
        font-weight: 500;
    }
    .toss-main {
        color: #333d4b;
        font-size: 36px;
        font-weight: 800;
        letter-spacing: -0.5px;
        margin-bottom: 12px;
    }
    .toss-badge {
        display: inline-block;
        background-color: #e8f3ff;
        color: #3182f6;
        padding: 6px 12px;
        border-radius: 8px;
        font-size: 13px;
        font-weight: 700;
    }
    
    .stButton>button {
        border-radius: 12px;
        height: 48px;
        font-weight: bold;
        border: none;
        box-shadow: none;
    }
</style>
""", unsafe_allow_html=True)

# ---------------------------------------------------------
# [인증 저장소]
# ---------------------------------------------------------
class StreamlitStorage:
    def __init__(self):
        self.storage_dir = Path.home() / ".streamlit_auth"
        self.storage_dir.mkdir(exist_ok=True)
        self.storage_file = self.storage_dir / "auth_storage.json"
        if "supabase_storage" not in st.session_state:
            st.session_state.supabase_storage = self._load_from_file()

    def _load_from_file(self) -> dict:
        try:
            if self.storage_file.exists():
                with open(self.storage_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
        except Exception: return {}
        return {}

    def _save_to_file(self) -> None:
        try:
            with open(self.storage_file, 'w', encoding='utf-8') as f:
                json.dump(st.session_state.supabase_storage, f)
        except Exception: pass

    def get_item(self, key: str) -> str | None:
        if key in st.session_state.supabase_storage:
            return st.session_state.supabase_storage[key]
        file_data = self._load_from_file()
        if key in file_data:
            st.session_state.supabase_storage[key] = file_data[key]
            return file_data[key]
        return None

    def set_item(self, key: str, value: str) -> None:
        st.session_state.supabase_storage[key] = value
        self._save_to_file()

    def remove_item(self, key: str) -> None:
        if key in st.session_state.supabase_storage:
            del st.session_state.supabase_storage[key]
        self._save_to_file()

# 세션 초기화
for key in ["is_logged_in", "user_info", "code_processed", "visited"]:
    if key not in st.session_state:
        st.session_state[key] = False if key != "user_info" else None

# Supabase 연결
try:
    URL = st.secrets["SUPABASE_URL"]
    KEY = st.secrets["SUPABASE_KEY"]
    supabase = create_client(
        URL, KEY,
        options=ClientOptions(storage=StreamlitStorage(), auto_refresh_token=True, persist_session=True)
    )
except Exception as e:
    st.error(f"🚨 연결 오류: {e}")
    supabase = None

# 인증 체크
def check_auth_status():
    if not supabase: return
    try:
        session = supabase.auth.get_session()
        if session and session.user:
            st.session_state.is_logged_in = True
            st.session_state.user_info = session.user
            if "code" in st.query_params: st.query_params.clear()
            return
    except: pass

    if "code" in st.query_params and not st.session_state.get("code_processed", False):
        try:
            auth_response = supabase.auth.exchange_code_for_session({
                "auth_code": st.query_params["code"],
                "redirect_to": "https://dividend-pange.streamlit.app/"
            })
            if auth_response.session:
                st.session_state.is_logged_in = True
                st.session_state.user_info = auth_response.session.user
            st.query_params.clear()
            st.session_state.code_processed = True
            st.rerun()
        except:
            st.session_state.code_processed = True
            st.query_params.clear()

check_auth_status()

# ==========================================
# [3] 로그인 UI 함수 (사이드바 상단 배치용)
# ==========================================
def render_auth_ui():
    if not supabase: return

    is_logged_in = st.session_state.get("is_logged_in", False)
    user_info = st.session_state.get("user_info", None)
    
    # [로그인 됨] -> 사이드바 상단에 표시 (가장 중요)
    if is_logged_in and user_info:
        email = user_info.email if user_info.email else "User"
        nickname = email.split("@")[0]
        
        with st.sidebar:
            st.markdown("---")
            st.success(f"👋 **{nickname}**님 안녕하세요!")
            if st.button("로그아웃", key="logout_btn", use_container_width=True):
                supabase.auth.sign_out()
                st.session_state.is_logged_in = False
                st.session_state.user_info = None
                st.session_state.code_processed = False
                st.rerun()
    
    # [로그인 안 됨] -> 메인 화면에서 버튼을 보여주므로 여기선 간단한 안내만
    else:
        # (메인 화면에 버튼이 있으므로 사이드바는 비워둠)
        pass

# ==========================================
# [4] 메인 애플리케이션
# ==========================================
def main():
    MAINTENANCE_MODE = False

    # 데이터 로드 (먼저 수행)
    df_raw = logic.load_stock_data_from_csv()
    if df_raw.empty: st.stop()
    df = logic.load_and_process_data(df_raw, is_admin=False) # Admin 여부는 아래에서 결정

    # ---------------------------------------------------------
    # [사이드바 구성 - 순서 재배치] 
    # 1. 로그인 정보 (가장 위)
    # 2. 메뉴 (중간)
    # 3. 관리자 모드 (가장 아래, 숨김 처리)
    # ---------------------------------------------------------
    
    # 1. 로그인 UI (사이드바 상단)
    render_auth_ui()
    
    # 2. 메뉴 UI (사이드바 중간)
    with st.sidebar:
        if not st.session_state.is_logged_in:
            st.info("👆 로그인하시면 더 많은 기능을 사용할 수 있습니다.")
        st.markdown("---")
        menu = st.radio("📂 **메뉴 이동**", ["💰 배당금 계산기", "📃 전체 종목 리스트"], label_visibility="visible")

    # 3. 관리자 모드 로직 (사이드바 맨 아래, 접이식으로 숨김)
    is_admin = False
    if st.query_params.get("admin", "false").lower() == "true":
        ADMIN_HASH = "c41b0bb392db368a44ce374151794850417b56c9786e3c482f825327c7153182"
        
        # ★ 핵심 변경: expander로 숨겨서 깔끔하게 만듦 ★
        with st.sidebar:
            st.markdown("---")
            with st.expander("🔐 관리자 설정 (Admin)", expanded=False):
                password_input = st.text_input("비밀번호", type="password")
                if password_input and hashlib.sha256(password_input.encode()).hexdigest() == ADMIN_HASH:
                    is_admin = True
                    st.success("인증됨 ✅")
                    
                    # 관리자 도구 표시
                    st.divider()
                    st.subheader("🛠️ 배당금 갱신")
                    target_stock = st.selectbox("종목 선택", df_raw['종목명'].unique())
                    if target_stock:
                        row = df_raw[df_raw['종목명'] == target_stock].iloc[0]
                        cur_hist = row.get('배당기록', "")
                        new_div = st.number_input("확정 배당금", step=10)
                        if st.button("갱신 실행"):
                            new_total, new_hist = logic.update_dividend_rolling(cur_hist, new_div)
                            st.success("완료! CSV 복사하세요.")
                            st.code(new_hist, language="text")
                elif password_input:
                    st.error("비밀번호 불일치")

    # ---------------------------------------------------------
    # [메인 로직 시작]
    # ---------------------------------------------------------
    
    # 점검 모드 (관리자는 제외)
    if MAINTENANCE_MODE and not is_admin:
        st.title("🚧 시스템 정기 점검 중")
        st.write("잠시 후 다시 접속해 주세요! 🙇‍♂️")
        st.stop()
        
    # 헤더 타이틀
    if is_admin:
        st.title("💰 배당팽이 대시보드 (관리자 모드)")
    
    # 공통 데이터 세션 관리
    if "total_invest" not in st.session_state: st.session_state.total_invest = 30000000
    if "selected_stocks" not in st.session_state: st.session_state.selected_stocks = []

    # =================================================================================
    # [화면 1] 배당금 계산기 (홈)
    # =================================================================================
    if menu == "💰 배당금 계산기":
        if not is_admin: # 관리자 타이틀과 중복 방지
            st.markdown("""
                <div style='margin-top: -20px; margin-bottom: 10px;'>
                    <h1 style='margin-bottom: 5px;'>💰 배당팽이 월배당 계산기</h1>
                    <p style='color: #8b95a1; font-size: 15px; line-height: 1.4;'>
                        매달 꽂히는 배당금을 미리 확인해보세요.
                    </p>
                </div>
            """, unsafe_allow_html=True)

        # 로그인 버튼 (로그인 안 된 경우 메인 상단에 표시)
        if not st.session_state.is_logged_in:
            with st.container():
                st.info("🔐 **로그인**하면 내 포트폴리오를 저장할 수 있어요.")
                col1, col2 = st.columns(2)
                cb_url = "https://dividend-pange.streamlit.app/"
                with col1:
                    if st.button("Google 로그인", key="btn_google_main", use_container_width=True):
                        try:
                            r = supabase.auth.sign_in_with_oauth({"provider":"google","options":{"redirect_to":cb_url}})
                            if r.url: st.markdown(f'<meta http-equiv="refresh" content="0;url={r.url}">', unsafe_allow_html=True)
                        except: pass
                with col2:
                    if st.button("Kakao 로그인", key="btn_kakao_main", use_container_width=True):
                        try:
                            r = supabase.auth.sign_in_with_oauth({"provider":"kakao","options":{"redirect_to":cb_url}})
                            if r.url: st.markdown(f'<meta http-equiv="refresh" content="0;url={r.url}">', unsafe_allow_html=True)
                        except: pass
                st.markdown("---")

        # 입력 영역
        st.markdown("### 1. 얼마를 투자하시나요?")
        invest_input = st.number_input("금액 입력 (단위: 만원)", min_value=100, value=int(st.session_state.total_invest/10000), step=100, label_visibility="collapsed")
        st.session_state.total_invest = invest_input * 10000
        st.caption(f"👉 **{st.session_state.total_invest/10000:,.0f}만원**을 투자합니다.")
        
        st.write("")
        st.markdown("### 2. 어떤 종목을 사시나요?")
        selected = st.multiselect("종목 검색 (여러 개 선택 가능)", df['pure_name'].unique(), default=st.session_state.selected_stocks, placeholder="종목명을 검색해보세요", label_visibility="collapsed")
        st.session_state.selected_stocks = selected

        if selected:
            weights = {}; all_data = []
            per_weight = 100 / len(selected)
            
            for stock in selected:
                weights[stock] = per_weight
                amt = st.session_state.total_invest * (per_weight / 100)
                match = df[df['pure_name'] == stock]
                if not match.empty:
                    row = match.iloc[0]
                    all_data.append({
                        '종목': stock, '비중': weights[stock], '자산유형': row['자산유형'], '투자금액_만원': amt/10000,
                        '종목명': stock, '코드': row.get('코드',''), '분류': row.get('분류','국내'),
                        '연배당률': row.get('연배당률',0), '금융링크': row.get('금융링크','#'),
                        '신규상장개월수': row.get('신규상장개월수',0), '현재가': row.get('현재가',0),
                        '환구분': row.get('환구분','-'), '배당락일': row.get('배당락일','-')
                    })

            total_y_div = sum([(st.session_state.total_invest * (weights[n]/100) * (df[df['pure_name']==n].iloc[0]['연배당률']/100)) for n in selected])
            total_m = total_y_div / 12
            avg_y = sum([(df[df['pure_name']==n].iloc[0]['연배당률'] * (weights[n]/100)) for n in selected])
            
            # 결과 카드
            st.write("")
            st.markdown("---")
            st.markdown("### 💸 예상 배당금 확인")
            
            st.markdown(f"""
            <div class="toss-card">
                <div class="toss-sub">매달 내 통장에 꽂히는 돈 (세후)</div>
                <div class="toss-main">{total_m * 0.846:,.0f}원</div>
                <div class="toss-badge">ISA 계좌라면 {total_m:,.0f}원 (+{total_m * 0.154:,.0f}원)</div>
                <div style="margin-top: 20px; font-size: 14px; color: #8b95a1;">
                    예상 연 배당률 <b>{avg_y:.2f}%</b>
                </div>
            </div>
            """, unsafe_allow_html=True)

            # 저장 버튼
            if st.button("내 포트폴리오 저장하기", type="primary", use_container_width=True):
                if not st.session_state.is_logged_in:
                    st.toast("👆 **상단의 로그인 버튼**을 먼저 눌러주세요!", icon="🔒")
                else:
                    try:
                        user = st.session_state.user_info
                        save_data = {
                            "total_money": st.session_state.total_invest, "composition": weights,
                            "summary": {"monthly_income": total_m, "yield": avg_y}
                        }
                        supabase.table("portfolios").insert({
                            "user_id": user.id, "user_email": user.email, "ticker_data": save_data
                        }).execute()
                        st.success("안전하게 저장되었습니다!")
                        st.balloons()
                    except Exception as e:
                        st.error(f"저장 실패: {e}")
                        
            st.info("👉 **상세 분석(차트, 달러비중)**은 사이드바 메뉴에서 확인하세요!")

    # =================================================================================
    # [화면 2] 상세 포트폴리오 분석 (메뉴 분리됨)
    # =================================================================================
    elif menu == "📊 상세 포트폴리오 분석":
        st.title("📊 상세 포트폴리오 분석")
        
        selected = st.session_state.selected_stocks
        total_invest = st.session_state.total_invest
        
        if not selected:
            st.warning("⚠️ 먼저 **'홈 (계산기)'** 메뉴에서 종목을 선택해주세요!")
            st.stop()
            
        weights = {}; all_data = []
        per_weight = 100 / len(selected)
        for stock in selected:
            weights[stock] = per_weight
            amt = total_invest * (per_weight / 100)
            match = df[df['pure_name'] == stock]
            if not match.empty:
                row = match.iloc[0]
                all_data.append({
                    '종목': stock, '비중': weights[stock], '자산유형': row['자산유형'], '투자금액_만원': amt/10000,
                    '종목명': stock, '코드': row.get('코드',''), '분류': row.get('분류','국내'),
                    '연배당률': row.get('연배당률',0), '금융링크': row.get('금융링크','#'),
                    '신규상장개월수': row.get('신규상장개월수',0), '현재가': row.get('현재가',0),
                    '환구분': row.get('환구분','-'), '배당락일': row.get('배당락일','-')
                })
        
        df_ana = pd.DataFrame(all_data)
        
        # 환노출 분석
        def classify_currency(row):
            try:
                bunryu = str(row.get('분류', ''))
                if bunryu == "해외" or "(해외)" in row['종목']: return "🇺🇸 달러 자산"
                return "🇰🇷 원화 자산"
            except: return "🇰🇷 원화 자산"
        
        df_ana['통화'] = df_ana.apply(classify_currency, axis=1)
        usd_ratio = df_ana[df_ana['통화'] == "🇺🇸 달러 자산"]['비중'].sum()
        
        c1, c2 = st.columns([1.2, 1])
        with c1:
            st.subheader("💎 자산 유형 비중")
            asset_sum = df_ana.groupby('자산유형').agg({'비중': 'sum', '투자금액_만원': 'sum', '종목': lambda x: ', '.join(x)}).reset_index()
            donut = alt.Chart(asset_sum).mark_arc(innerRadius=60).encode(
                theta=alt.Theta("비중:Q"), 
                color=alt.Color("자산유형:N", legend=alt.Legend(orient='bottom', title=None)), 
                tooltip=[alt.Tooltip("자산유형"), alt.Tooltip("비중", format=".1f"), alt.Tooltip("투자금액_만원", format=",d")]
            ).properties(height=300)
            st.altair_chart(donut, use_container_width=True)
            
        with c2:
            st.subheader("🌐 환율 노출도")
            st.write(f"달러 자산 비중: **{usd_ratio:.1f}%**")
            st.progress(usd_ratio / 100)
            if usd_ratio >= 50: st.caption("💡 포트폴리오의 절반 이상이 환율 변동에 영향을 받습니다.")
            else: st.caption("💡 원화 자산 중심의 안정적인 구성입니다.")
            st.divider()
            st.write("📋 **유형별 요약**")
            st.dataframe(asset_sum[['자산유형', '비중', '투자금액_만원']], hide_index=True, use_container_width=True)

        st.write("")
        st.subheader("📋 상세 포트폴리오")
        ui.render_custom_table(df_ana)

    # =================================================================================
    # [화면 3] 전체 종목 리스트 (별도 메뉴)
    # =================================================================================
    elif menu == "📃 전체 종목 리스트":
        st.title("📃 전체 배당주 리스트")
        st.caption("배당팽이 데이터베이스에 등록된 모든 종목입니다.")
        st.info("💡 **이동 안내:** '코드' 클릭 시 블로그 분석글로, '🔗정보' 클릭 시 네이버/야후 금융 정보로 이동합니다.")
        
        tab_all, tab_kor, tab_usa = st.tabs(["🌎 전체", "🇰🇷 국내", "🇺🇸 해외"])
        with tab_all: ui.render_custom_table(df)
        with tab_kor: ui.render_custom_table(df[df['분류'] == '국내'])
        with tab_usa: ui.render_custom_table(df[df['분류'] == '해외'])

    # ------------------------------------------
    # 하단 공통 푸터
    # ------------------------------------------
    st.divider()
    
    @st.fragment
    def track_visitors():
        if not st.session_state.get('visited', False) and supabase:
            try:
                if st.query_params.get("admin", "false").lower() != "true":
                    st.session_state.visited = True
                    # 방문 카운팅 로직 (필요시 활성화)
            except: pass
        
        st.caption("© 2025 **배당팽이** | 실시간 데이터 기반 배당 대시보드")
        st.caption("First Released: 2025.12.31 | [📝 배당팽이의 배당 투자 일지 구경가기](https://blog.naver.com/dividenpange)")

    track_visitors()

if __name__ == "__main__":
    main()
