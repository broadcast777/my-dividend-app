import streamlit as st
from supabase import create_client, ClientOptions
import pandas as pd
import altair as alt
import hashlib
import json
import os
from pathlib import Path
import random # [복구] 랜덤 비유를 위해 필요

# [모듈화] 분리한 파일들을 불러옵니다
import logic 
import ui

# ==========================================
# [1] 기본 설정
# ==========================================
st.set_page_config(page_title="배당팽이 대시보드", layout="wide")

# ---------------------------------------------------------
# [핵심] 새로고침해도 로그인이 풀리지 않게 잡아주는 저장소 클래스
# ---------------------------------------------------------
class StreamlitStorage:
    """Streamlit + 파일 하이브리드 저장소 (PKCE 보존용)"""
    
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
        except Exception as e:
            print(f"[Storage] 파일 로드 실패: {e}")
        return {}

    def _save_to_file(self) -> None:
        try:
            with open(self.storage_file, 'w', encoding='utf-8') as f:
                json.dump(st.session_state.supabase_storage, f)
        except Exception as e:
            print(f"[Storage] 파일 저장 실패: {e}")

    def get_item(self, key: str) -> str | None:
        if key in st.session_state.supabase_storage:
            return st.session_state.supabase_storage[key]
        file_data = self._load_from_file()
        return file_data.get(key)

    def set_item(self, key: str, value: str) -> None:
        st.session_state.supabase_storage[key] = value
        self._save_to_file()

    def remove_item(self, key: str) -> None:
        if key in st.session_state.supabase_storage:
            del st.session_state.supabase_storage[key]
        self._save_to_file()


# ---------------------------------------------------------
# 세션 상태 변수 초기화
# ---------------------------------------------------------
for key in ["is_logged_in", "user_info", "code_processed"]:
    if key not in st.session_state:
        st.session_state[key] = False if key != "user_info" else None


# ---------------------------------------------------------
# Supabase 클라이언트 연결
# ---------------------------------------------------------
try:
    URL = st.secrets["SUPABASE_URL"]
    KEY = st.secrets["SUPABASE_KEY"]
    
    supabase = create_client(
        URL, 
        KEY,
        options=ClientOptions(
            storage=StreamlitStorage(),
            auto_refresh_token=True,
            persist_session=True,
        )
    )
except Exception as e:
    st.error(f"🚨 Supabase 연결 오류: {e}")
    supabase = None


# ==========================================
# [2] 인증 상태 체크
# ==========================================
def check_auth_status():
    if not supabase: return

    # 1. 이미 로그인된 상태인지 확인
    try:
        session = supabase.auth.get_session()
        if session and session.user:
            st.session_state.is_logged_in = True
            st.session_state.user_info = session.user
            if "code" in st.query_params:
                st.query_params.clear()
            return 
    except Exception:
        pass

    # 2. 로그인 콜백 처리
    query_params = st.query_params
    if "code" in query_params and not st.session_state.get("code_processed", False):
        try:
            auth_code = query_params["code"]
            redirect_url = "https://dividend-pange.streamlit.app/"
            
            auth_response = supabase.auth.exchange_code_for_session({
                "auth_code": auth_code,
                "redirect_to": redirect_url
            })
            session = auth_response.session
            
            if session and session.user:
                st.session_state.is_logged_in = True
                st.session_state.user_info = session.user
            
            st.query_params.clear()
            st.session_state.code_processed = True
            st.success("✅ 로그인되었습니다!")
            st.rerun()
            
        except Exception:
            if not st.session_state.is_logged_in:
                st.error("로그인 시간이 만료되었습니다. 다시 시도해주세요.")
            st.session_state.code_processed = True
            st.query_params.clear()

check_auth_status()


# ==========================================
# [3] 로그인 UI 함수
# ==========================================
def render_login_ui():
    """로그인 상태일 때만 사이드바에 프로필 표시"""
    if not supabase: return

    is_logged_in = st.session_state.get("is_logged_in", False)
    user_info = st.session_state.get("user_info", None)
    
    if is_logged_in and user_info:
        email = user_info.email if user_info.email else "User"
        nickname = email.split("@")[0]
        
        with st.sidebar:
            st.markdown("---")
            st.success(f"👋 반가워요! **{nickname}**님")
            if st.button("🚪 로그아웃", key="logout_btn", use_container_width=True):
                supabase.auth.sign_out()
                st.session_state.is_logged_in = False
                st.session_state.user_info = None
                st.session_state.code_processed = False
                st.rerun()
    else:
        pass 


# ==========================================
# [4] 메인 애플리케이션
# ==========================================
def main():
    MAINTENANCE_MODE = False
    
    # [1] 값 초기화
    if "total_invest" not in st.session_state: 
        st.session_state.total_invest = 30000000
    if "selected_stocks" not in st.session_state: 
        st.session_state.selected_stocks = []

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

    # [3] 로그인 UI
    render_login_ui()
    
    # [4] 점검 모드 및 타이틀
    if MAINTENANCE_MODE and not is_admin:
        st.title("🚧 시스템 정기 점검 중")
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

    # 데이터 처리
    with st.spinner('⚙️ 배당 데이터베이스 엔진 가동 중...'):
        df = logic.load_and_process_data(df_raw, is_admin=is_admin)

    # ---------------------------------------------------------
    # 사이드바 메뉴 & 불러오기 (UI 개선: 토글 방식)
    # ---------------------------------------------------------
    with st.sidebar:
        if not st.session_state.is_logged_in:
            st.markdown("---")
        
        menu = st.radio("📂 **메뉴 이동**", ["💰 배당금 계산기", "📃 전체 종목 리스트"], label_visibility="visible")
        
        # [불러오기 및 관리 기능]
        st.markdown("---")
        with st.expander("📂 불러오기 / 관리"):
            if not st.session_state.is_logged_in:
                st.caption("로그인이 필요합니다.")
            else:
                try:
                    uid = st.session_state.user_info.id
                    resp = supabase.table("portfolios").select("*").eq("user_id", uid).order("created_at", desc=True).execute()
                    
                    if resp.data:
                        # 1. 목록 표시
                        opts = {}
                        for p in resp.data:
                            date_str = p['created_at'][5:10] # 월-일
                            time_str = p['created_at'][11:16] # 시:분
                            name = p.get('name') or '이름없음'
                            label = f"{name} ({date_str} {time_str})"
                            opts[label] = p

                        sel_name = st.selectbox("항목 선택", list(opts.keys()), label_visibility="collapsed")
                        
                        # 2. UI 깔끔하게 하기: '삭제 모드' 스위치
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
        st.warning("⚠️ **투자 유의사항:** 본 대시보드의 연배당률은 과거 분배금 데이터를 기반으로 계산된 참고용 지표입니다.")

        # 섹션 1: 포트폴리오 시뮬레이션
        with st.expander("🧮 나만의 배당 포트폴리오 시뮬레이션", expanded=True):
            col1, col2 = st.columns([1, 2])
            
            # 1. 투자금 입력
            current_invest_val = int(st.session_state.total_invest / 10000)
            invest_input = col1.number_input("💰 총 투자 금액 (만원)", min_value=100, value=current_invest_val, step=100)
            st.session_state.total_invest = invest_input * 10000
            total_invest = st.session_state.total_invest 
            
            # 2. 종목 선택
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
                            '종목': stock, 
                            '비중': weights[stock], 
                            '자산유형': s_row['자산유형'], 
                            '투자금액_만원': amt / 10000,
                            '종목명': stock,              
                            '코드': s_row.get('코드', ''),
                            '분류': s_row.get('분류', '국내'),
                            '연배당률': s_row.get('연배당률', 0),
                            '금융링크': s_row.get('금융링크', '#'),
                            '신규상장개월수': s_row.get('신규상장개월수', 0),
                            '현재가': s_row.get('현재가', 0),
                            '환구분': s_row.get('환구분', '-'),
                            '배당락일': s_row.get('배당락일', '-')
                        })

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
                # [저장 로직] 로그인 여부에 따라 버튼 자동 변경
                # =========================================================
                st.write("") 
                with st.container(border=True):
                    st.write("💾 **포트폴리오 저장 / 수정**")
                    
                    if not st.session_state.is_logged_in:
                        st.info("🔒 로그인이 필요합니다.")
                        l_c1, l_c2 = st.columns(2)
                        callback_url = "https://dividend-pange.streamlit.app/"
                        with l_c1:
                            if st.button("🔵 Google 로그인", key="save_google", use_container_width=True):
                                try:
                                    res = supabase.auth.sign_in_with_oauth({"provider": "google", "options": {"redirect_to": callback_url}})
                                    if res.url: st.markdown(f'<meta http-equiv="refresh" content="0;url={res.url}">', unsafe_allow_html=True)
                                except: pass
                        with l_c2:
                            if st.button("💬 Kakao 로그인", key="save_kakao", use_container_width=True):
                                try:
                                    # [1] redirect_to에 "슬래시(/)를 붙여서" 명시합니다.
                                    # 이유: Streamlit은 원래 슬래시 있는 주소가 '진짜 주소'입니다. 
                                    # 억지로 떼는 것보다 붙여주는 게 서버 충돌을 막습니다.
                                    res = supabase.auth.sign_in_with_oauth({
                                        "provider": "kakao",
                                        "options": {
                                            "redirect_to": "https://dividend-pange.streamlit.app/", 
                                            "queryParams": {
                                                "prompt": "login"
                                            }
                                        }
                                    })
                                    
                                    # [2] 이동 방식을 <meta> 태그에서 "자바스크립트"로 변경합니다.
                                    # 모바일에서 훨씬 강력하고 확실하게 이동시켜 줍니다.
                                    if res.url:
                                        st.write(f"""
                                            <script>
                                                window.top.location.href = "{res.url}";
                                            </script>
                                        """, unsafe_allow_html=True)
                                        
                                except: pass
                    else:
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
                                        supabase.table("portfolios").update({
                                            "ticker_data": save_data,
                                            "created_at": "now()"
                                        }).eq("id", target_id).execute()
                                        st.success("수정 완료! 내용이 업데이트되었습니다."); st.balloons()
                                        import time; time.sleep(1.0); st.rerun()

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
    3. 실제 배당금 지급일과 금액은 운용사의 사정에 따라 변경될 수 있습니다.""")

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

                        # [복구] 스타벅스 비유 로직
                        analogy_items = [
                            {"name": "스타벅스", "unit": "잔", "price": 4500, "emoji": "☕"},
                            {"name": "치킨", "unit": "마리", "price": 23000, "emoji": "🍗"},
                            {"name": "제주도 항공권", "unit": "장", "price": 60000, "emoji": "✈️"},
                            {"name": "특급호텔 숙박", "unit": "박", "price": 200000, "emoji": "🏨"}
                        ]
                        selected_item = random.choice(analogy_items)
                        item_count = int(monthly_pocket // selected_item['price'])

                        st.markdown(f"""<div style="background-color: #e7f3ff; border: 1.5px solid #d0e8ff; border-radius: 16px; padding: 25px; text-align: center; box-shadow: 0 4px 10px rgba(0,104,201,0.05);"><p style="color: #666; font-size: 0.95em; margin: 0 0 8px 0;">{years_sim}년 뒤 모이는 돈 (세후)</p><h2 style="color: #0068c9; font-size: 2.2em; margin: 0; font-weight: 800; line-height: 1.2;">약 {real_money/10000:,.0f}만원{inflation_msg_money}</h2><p style="color: #777; font-size: 0.9em; margin: 8px 0 0 0;">(투자원금 {final_principal/10000:,.0f}만원 / {tax_msg})</p><div style="height: 1px; background-color: #d0e8ff; margin: 25px auto; width: 85%;"></div><p style="color: #0068c9; font-weight: bold; font-size: 1.1em; margin: 0 0 12px 0;">📅 월 예상 배당금: {monthly_pocket/10000:,.1f}만원 {inflation_msg_monthly}</p><div style="background-color: rgba(255,255,255,0.5); padding: 15px; border-radius: 12px; display: inline-block; min-width: 80%;"><p style="color: #333; font-size: 1.1em; margin: 0; line-height: 1.6;">매달 <b>{selected_item['emoji']} {selected_item['name']} {item_count:,}{selected_item['unit']}</b><br>마음껏 즐기기 가능! 😋</p></div></div>""", unsafe_allow_html=True)
                        
                        # [복구] 시뮬레이션 경고문
                        annual_div_income = monthly_div_final * 12
                        if annual_div_income > 20000000:
                            st.warning(f"🚨 **주의:** {years_sim}년 뒤 연간 배당금이 2,000만원을 초과하여 금융소득종합과세 대상이 될 수 있습니다.")
                        
                        st.error("""**⚠️ 시뮬레이션 활용 시 유의사항**
                        
    1. 본 결과는 주가·환율 변동과 수수료 등을 제외하고, 현재 배당률로만 계산한 결과입니다.
    2. ISA 계좌의 비과세 한도 및 세율은 세법 개정에 따라 달라질 수 있습니다.
    3. 과거의 데이터를 기반으로 한 단순 시뮬레이션이며, 실제 투자 수익을 보장하지 않습니다.""")

                    with tab_goal:
                        st.subheader("🎯 목표 배당금 역산기 (은퇴 시뮬레이터)")
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
                                st.error("⚠️ 현재 적립액으로는 50년 내 달성이 어렵습니다.")
                            else:
                                st.metric("목표 달성까지 소요 기간", f"{months_passed // 12}년 {months_passed % 12}개월")

                        if apply_inflation_goal:
                            discount_factor = (1.025) ** (months_passed / 12)
                            real_value = target_monthly_goal / discount_factor
                            st.warning(f"⚠️ **물가 반영 시:** {months_passed // 12}년 뒤 {target_monthly_goal/10000:,.0f}만원의 실질 가치는 현재 기준 **약 {real_value/10000:,.1f}만원**입니다.")
                        
                        # [복구] 목표 탭 경고문
                        target_annual_income = target_monthly_goal * 12
                        if target_annual_income > 20000000:
                            st.warning(f"🚨 **현실적 조언:** 설정하신 목표(월 {target_monthly_goal/10000:,.0f}만원) 달성 시, 연 배당소득이 2,000만원을 넘어 **금융종합과세 대상**이 됩니다.")

                        st.error("""**⚠️ 시뮬레이션 활용 시 유의사항**
                        
    1. 본 결과는 주가·환율 변동과 수수료 등을 제외하고, 현재 배당률로만 계산한 결과입니다.
    2. 실제 배당금은 운용사의 공시 및 환율 상황에 따라 매월 달라질 수 있습니다.
    3. 과거의 데이터를 기반으로 한 단순 시뮬레이션이며, 실제 투자 수익을 보장하지 않습니다.""")

    # =================================================================================
    # [화면 2] 전체 종목 리스트
    # =================================================================================
    elif menu == "📃 전체 종목 리스트":
        st.info("💡 **이동 안내:** '코드' 클릭 시 블로그 분석글로, '🔗정보' 클릭 시 네이버/야후 금융 정보로 이동합니다. (**⭐ 표시는 상장 1년 미만 종목입니다.**)")
        
        tab_all, tab_kor, tab_usa = st.tabs(["🌎 전체", "🇰🇷 국내", "🇺🇸 해외"])
        with tab_all: ui.render_custom_table(df)
        with tab_kor: ui.render_custom_table(df[df['분류'] == '국내'])
        with tab_usa: ui.render_custom_table(df[df['분류'] == '해외'])

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
