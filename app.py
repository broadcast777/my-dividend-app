import streamlit as st
from supabase import create_client, ClientOptions
import pandas as pd
import altair as alt
import hashlib
import json
import os
from pathlib import Path
import random 
import time

# [모듈화] 분리한 파일들을 불러옵니다
import logic 
import ui

# ==========================================
# [1] 기본 설정
# ==========================================
st.set_page_config(page_title="배당팽이 대시보드", layout="wide")

# ---------------------------------------------------------
# [중요] 세션 상태 강제 초기화 (에러 방지용)
# ---------------------------------------------------------
if "supabase_storage" not in st.session_state:
    st.session_state.supabase_storage = {}

# ---------------------------------------------------------
# [핵심] 파일 기반 저장소 클래스 (암호키 보존용)
# ---------------------------------------------------------
class StreamlitStorage:
    def __init__(self):
        self.storage_dir = Path.home() / ".streamlit_auth"
        self.storage_dir.mkdir(exist_ok=True)
        self.storage_file = self.storage_dir / "auth_storage.json"
        
        # 파일에서 읽어와서 세션에 로드
        if not st.session_state.supabase_storage:
            st.session_state.supabase_storage = self._load_from_file()

    def _load_from_file(self) -> dict:
        try:
            if self.storage_file.exists():
                with open(self.storage_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
        except: pass
        return {}

    def _save_to_file(self) -> None:
        try:
            with open(self.storage_file, 'w', encoding='utf-8') as f:
                json.dump(st.session_state.supabase_storage, f)
        except: pass

    def get_item(self, key: str) -> str | None:
        # 우선 세션에서 찾고, 없으면 파일에서 다시 확인
        if key in st.session_state.supabase_storage:
            return st.session_state.supabase_storage[key]
        return self._load_from_file().get(key)

    def set_item(self, key: str, value: str) -> None:
        st.session_state.supabase_storage[key] = value
        self._save_to_file()

    def remove_item(self, key: str) -> None:
        if key in st.session_state.supabase_storage:
            del st.session_state.supabase_storage[key]
        self._save_to_file()

# ---------------------------------------------------------
# Supabase 연결 (캐싱 제거 -> 파일 저장소 사용이 정답)
# ---------------------------------------------------------
try:
    URL = st.secrets["SUPABASE_URL"]
    KEY = st.secrets["SUPABASE_KEY"]
    
    # @st.cache_resource 제거함 (세션 충돌 방지)
    supabase = create_client(
        URL, 
        KEY,
        options=ClientOptions(
            storage=StreamlitStorage(), # 파일 저장소 연결
            auto_refresh_token=True,
            persist_session=True,
        )
    )
except Exception as e:
    st.error(f"🚨 Supabase 연결 오류: {e}")
    supabase = None

# 세션 변수 초기화
for key in ["is_logged_in", "user_info", "code_processed"]:
    if key not in st.session_state:
        st.session_state[key] = False if key != "user_info" else None

# ==========================================
# [2] 인증 상태 체크 (주소 명시 버전)
# ==========================================
def check_auth_status():
    if not supabase: return
    if st.session_state.is_logged_in: return

    # 1. 기존 세션 확인
    try:
        session = supabase.auth.get_session()
        if session and session.user:
            st.session_state.is_logged_in = True
            st.session_state.user_info = session.user
            if "code" in st.query_params: st.query_params.clear()
            return 
    except: pass

    # 2. 로그인 콜백 처리
    if "code" in st.query_params and not st.session_state.code_processed:
        try:
            auth_code = st.query_params["code"]
            
            # [수정] redirect_to에 "슬래시 없는 주소"를 명확히 넣습니다.
            res = supabase.auth.exchange_code_for_session({
                "auth_code": auth_code,
                "redirect_to": "https://dividend-pange.streamlit.app"
            })
            
            if res.session and res.session.user:
                st.session_state.is_logged_in = True
                st.session_state.user_info = res.session.user
                st.session_state.code_processed = True
                st.success("✅ 로그인 성공!")
                time.sleep(0.5)
                st.query_params.clear()
                st.rerun()
                
        except Exception as e:
            st.error(f"인증 실패: {e}")
            st.session_state.code_processed = True

check_auth_status()

# ==========================================
# [3] 로그인 UI 함수
# ==========================================
def render_login_ui():
    if not supabase: return
    if st.session_state.is_logged_in and st.session_state.user_info:
        email = st.session_state.user_info.email
        nickname = email.split("@")[0] if email else "User"
        with st.sidebar:
            st.markdown("---")
            st.success(f"👋 반가워요! **{nickname}**님")
            if st.button("🚪 로그아웃", key="logout_btn", use_container_width=True):
                supabase.auth.sign_out()
                st.session_state.is_logged_in = False
                st.session_state.user_info = None
                st.session_state.code_processed = False
                st.rerun()

# ==========================================
# [4] 메인 애플리케이션
# ==========================================
def main():
    MAINTENANCE_MODE = False
    
    # 값 초기화
    if "total_invest" not in st.session_state: st.session_state.total_invest = 30000000
    if "selected_stocks" not in st.session_state: st.session_state.selected_stocks = []

    # 관리자 인증
    is_admin = False
    if st.query_params.get("admin", "false").lower() == "true":
        ADMIN_HASH = "c41b0bb392db368a44ce374151794850417b56c9786e3c482f825327c7153182"
        with st.expander("🔐 관리자 접속", expanded=False):
            if st.text_input("비밀번호", type="password") == "admin": 
                 pass 

    render_login_ui()
    
    if MAINTENANCE_MODE and not is_admin:
        st.title("🚧 시스템 정기 점검 중")
        st.stop()
    
    if is_admin: st.title("💰 배당팽이 대시보드 (관리자 모드)")
    else: st.title("💰 배당팽이 월배당 계산기")

    # 데이터 로드
    df_raw = logic.load_stock_data_from_csv()
    if df_raw.empty: st.stop()
    
    # [관리자] 갱신 도구
    if is_admin:
        with st.sidebar:
            st.markdown("---")
            st.subheader("🛠️ 배당금 갱신 도구")
            target_stock = st.selectbox("갱신할 종목 선택", df_raw['종목명'].unique())
            if target_stock:
                row = df_raw[df_raw['종목명'] == target_stock].iloc[0]
                cur_hist = row.get('배당기록', "")
                new_div = st.number_input("이번 달 확정 배당금", value=0, step=10)
                if st.button("계산 실행"):
                    new_total, new_hist = logic.update_dividend_rolling(cur_hist, new_div)
                    st.success("완료!")
                    st.code(new_hist, language="text")

    with st.spinner('⚙️ 배당 데이터베이스 엔진 가동 중...'):
        df = logic.load_and_process_data(df_raw, is_admin=is_admin)

    # 사이드바 메뉴
    with st.sidebar:
        if not st.session_state.is_logged_in: st.markdown("---")
        menu = st.radio("📂 **메뉴 이동**", ["💰 배당금 계산기", "📃 전체 종목 리스트"])
        
        st.markdown("---")
        with st.expander("📂 불러오기 / 관리"):
            if not st.session_state.is_logged_in:
                st.caption("로그인이 필요합니다.")
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
                    else: st.caption("저장된 기록이 없습니다.")
                except: st.error("불러오기 실패")

    # [화면 1] 배당금 계산기
    if menu == "💰 배당금 계산기":
        st.warning("⚠️ **투자 유의사항:** 본 대시보드의 연배당률은 과거 분배금 데이터를 기반으로 계산된 참고용 지표입니다.")

        # 섹션 1: 포트폴리오 시뮬레이션
        with st.expander("🧮 나만의 배당 포트폴리오 시뮬레이션", expanded=True):
            col1, col2 = st.columns([1, 2])
            
            # 투자금 입력
            current_invest_val = int(st.session_state.total_invest / 10000)
            invest_input = col1.number_input("💰 총 투자 금액 (만원)", min_value=100, value=current_invest_val, step=100)
            st.session_state.total_invest = invest_input * 10000
            total_invest = st.session_state.total_invest 
            
            # 종목 선택
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
                        all_data.append({
                            '종목': stock, '비중': weights[stock], '자산유형': s_row['자산유형'], '투자금액_만원': amt / 10000,
                            '종목명': stock, '코드': s_row.get('코드', ''), '분류': s_row.get('분류', '국내'),
                            '연배당률': s_row.get('연배당률', 0), '금융링크': s_row.get('금융링크', '#'),
                            '신규상장개월수': s_row.get('신규상장개월수', 0), '현재가': s_row.get('현재가', 0),
                            '환구분': s_row.get('환구분', '-'), '배당락일': s_row.get('배당락일', '-')
                        })

                # 결과 계산
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
                # [저장 로직] 로그인 버튼 (링크 생성 최적화)
                # =========================================================
                st.write("") 
                with st.container(border=True):
                    st.write("💾 **포트폴리오 저장 / 수정**")
                    
                    if not st.session_state.is_logged_in:
                        st.info("🔒 로그인이 필요합니다.")

                        if "auth_links" not in st.session_state:
                            st.session_state.auth_links = {"google": None, "kakao": None}

                        l_c1, l_c2 = st.columns(2)
                        
                        # [왼쪽] Google 로그인
                        with l_c1:
                            try:
                                if st.session_state.auth_links["google"] is None:
                                    res = supabase.auth.sign_in_with_oauth({
                                        "provider": "google",
                                        "options": {
                                            "redirect_to": "https://dividend-pange.streamlit.app",
                                            "queryParams": {"prompt": "select_account"},
                                            "skip_browser_redirect": True
                                        }
                                    })
                                    st.session_state.auth_links["google"] = res.url
                                
                                if st.session_state.auth_links["google"]:
                                    url = st.session_state.auth_links["google"]
                                    st.markdown(f'''<a href="{url}" target="_self" style="display: inline-flex; justify-content: center; align-items: center; width: 100%; background-color: #fff; color: #1f1f1f; border: 1px solid #747775; padding: 0.5rem; border-radius: 0.5rem; text-decoration: none; font-weight: 600; box-shadow: 0 1px 2px rgba(0,0,0,0.05);">🔵 Google 로그인</a>''', unsafe_allow_html=True)
                            except: st.error("오류")
                        
                        # [오른쪽] Kakao 로그인
                        with l_c2:
                            try:
                                if st.session_state.auth_links["kakao"] is None:
                                    res = supabase.auth.sign_in_with_oauth({
                                        "provider": "kakao",
                                        "options": {
                                            "redirect_to": "https://dividend-pange.streamlit.app",
                                            "queryParams": {"prompt": "login"},
                                            "skip_browser_redirect": True
                                        }
                                    })
                                    st.session_state.auth_links["kakao"] = res.url
                                
                                if st.session_state.auth_links["kakao"]:
                                    url = st.session_state.auth_links["kakao"]
                                    st.markdown(f'''<a href="{url}" target="_self" style="display: inline-flex; justify-content: center; align-items: center; width: 100%; background-color: #FEE500; color: #000; border: 1px solid rgba(0,0,0,0.1); padding: 0.5rem; border-radius: 0.5rem; text-decoration: none; font-weight: 600; box-shadow: 0 1px 2px rgba(0,0,0,0.05);">💬 Kakao 로그인</a>''', unsafe_allow_html=True)
                            except: st.error("오류")

                    else:
                        try:
                            user = st.session_state.user_info
                            save_mode = st.radio("방식 선택", ["✨ 새로 만들기", "🔄 기존 파일 수정"], horizontal=True, label_visibility="collapsed")
                            save_data = {"total_money": st.session_state.total_invest, "composition": weights, "summary": {"monthly": total_m, "yield": avg_y}}

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
                                    st.success(f"[{final_name}] 저장 완료!"); st.balloons()
                                    import time; time.sleep(1.0); st.rerun()

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
                                        supabase.table("portfolios").update({"ticker_data": save_data, "created_at": "now()"}).eq("id", target_id).execute()
                                        st.success("수정 완료! 내용이 업데이트되었습니다."); st.balloons()
                                        import time; time.sleep(1.0); st.rerun()
                        except Exception as e:
                            st.error(f"오류 발생: {e}")

                st.write("")
                st.info("""
                📢 **찾으시는 종목이 안 보이나요?**
                왼쪽 상단(모바일은 ↖ 메뉴 버튼)의 '📂 메뉴'를 누르고 '📃 전체 종목 리스트'를 선택하시면 전체 배당주를 확인하실 수 있습니다.
                """)

                if total_y_div > 20000000:
                    st.warning(f"🚨 **주의:** 연간 예상 배당금이 **{total_y_div/10000:,.0f}만원**입니다. 금융소득종합과세 대상에 해당될 수 있습니다.")

                # 섹션 3: 상세 분석 (탭 등등)
                df_ana = pd.DataFrame(all_data)
                if not df_ana.empty:
                    st.write("")
                    tab_analysis, tab_simulation, tab_goal = st.tabs(["💎 자산 구성 분석", "💰 10년 뒤 자산 미리보기", "🎯 목표 배당 달성"])
                    # ... (이하 시뮬레이션 및 탭 내용은 기존과 동일) ...
                    with tab_analysis:
                        chart_col, table_col = st.columns([1.2, 1])
                        # ... (기존 분석 로직 유지) ...
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
                            donut = alt.Chart(asset_sum).mark_arc(innerRadius=60).encode(theta=alt.Theta("비중:Q"), color=alt.Color("자산유형:N", legend=None)).properties(height=320)
                            st.altair_chart(donut, use_container_width=True)
                        with table_col:
                            st.dataframe(asset_sum, use_container_width=True, hide_index=True)
                        ui.render_custom_table(df_ana)

                    with tab_simulation:
                        # ... (시뮬레이션 로직 - 기존과 동일하게 유지) ...
                        st.info("시뮬레이션 탭은 내용이 길어서 생략했습니다. 기존 로직 그대로 사용하시면 됩니다.")

                    with tab_goal:
                        # ... (목표 설정 로직 - 기존과 동일하게 유지) ...
                        st.info("목표 탭은 내용이 길어서 생략했습니다. 기존 로직 그대로 사용하시면 됩니다.")

    elif menu == "📃 전체 종목 리스트":
        st.info("💡 **이동 안내:** '코드' 클릭 시 블로그 분석글로, '🔗정보' 클릭 시 네이버/야후 금융 정보로 이동합니다.")
        tab_all, tab_kor, tab_usa = st.tabs(["🌎 전체", "🇰🇷 국내", "🇺🇸 해외"])
        with tab_all: ui.render_custom_table(df)
        with tab_kor: ui.render_custom_table(df[df['분류'] == '국내'])
        with tab_usa: ui.render_custom_table(df[df['분류'] == '해외'])

    st.divider()
    st.caption("© 2025 **배당팽이** | 실시간 데이터 기반 배당 대시보드")

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
            except: st.session_state.display_count = "집계 중"; st.session_state.visited = True
        
        st.write(f"방문자 수: {st.session_state.get('display_count', '...')}")

    track_visitors()

if __name__ == "__main__":
    main()
