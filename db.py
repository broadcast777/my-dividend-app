import streamlit as st
import pandas as pd
import altair as alt
import hashlib
import time
import random
from streamlit.runtime.scriptrunner import get_script_run_ctx
# [추가] 날짜 계산 및 URL 인코딩용 라이브러리
from datetime import datetime, timedelta
import urllib.parse

# [모듈화] 분리한 파일들을 불러옵니다
import logic 
import ui
import db

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

# ---------------------------------------------------------
# Supabase 연결
# ---------------------------------------------------------
supabase = db.init_supabase()

# ==========================================
# [2] 인증 상태 체크 (URL 릴레이 로직 포함)
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
# [캘린더 기능] 안전 매수일 계산 함수
# ==========================================
def calculate_safe_buy_date(ex_date_str):
    """
    배당락일(Ex-Date) 기준 'D-2 영업일'을 계산합니다.
    (주말/공휴일 변수를 고려하여 2일 정도 미리 알림을 주는 것이 안전함)
    """
    try:
        if not ex_date_str or ex_date_str == '-': return None, None
        
        # 1. 문자열 정리 및 날짜 객체 변환
        clean_str = ex_date_str.replace(".", "").replace("-", "").strip()
        ex_date = datetime.strptime(clean_str, "%Y%m%d")
        
        # 2. 여유 있게 '2일 전'으로 설정 (D-2)
        buy_date = ex_date - timedelta(days=2)
        
        # 3. 그 날이 주말(토=5, 일=6)이면 평일(금요일)이 나올 때까지 계속 뒤로 뺌
        while buy_date.weekday() >= 5:
            buy_date -= timedelta(days=1)
            
        # 4. 결과 반환 (구글용 코드, 화면용 텍스트)
        return buy_date.strftime("%Y%m%d"), buy_date.strftime("%Y.%m.%d")
    except:
        return None, None

def make_google_calendar_link(stock_name, date_str):
    """
    구글 캘린더 링크 생성 (D-2 안전일 기준)
    """
    try:
        # 안전 날짜 계산
        safe_date_code, safe_date_view = calculate_safe_buy_date(date_str)
        
        if not safe_date_code: return None

        # 제목 설정
        title = urllib.parse.quote(f"💰 {stock_name} 매수 추천일 (D-2)")
        
        # 내용 설정 (주의 문구 포함)
        desc_text = (
            f"[{stock_name} 배당 알림]\n\n"
            f"📅 데이터상 배당락일: {date_str}\n"
            f"✅ 안전 매수 추천일: {safe_date_view} (오늘)\n\n"
            f"⚠️ 주의: 위 날짜는 주말을 제외하고 계산된 날짜입니다.\n"
            f"혹시 '평일 공휴일(현충일, 크리스마스 등)'이 끼어 있다면,\n"
            f"그보다 하루 더 빨리 매수하셔야 안전합니다!"
        )
        details = urllib.parse.quote(desc_text)
        
        # 날짜 설정 (하루 종일)
        dates = f"{safe_date_code}/{safe_date_code}"
        
        return f"https://www.google.com/calendar/render?action=TEMPLATE&text={title}&dates={dates}&details={details}"
    except:
        return None

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

    # [로그인 상태바]
    if st.session_state.get("is_logged_in", False):
        user = st.session_state.user_info
        nickname = user.email.split("@")[0] if user.email else "User"
        st.info(f"👋 **{nickname}**님, 환영합니다! (로그인됨)")
    
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
    # 사이드바 메뉴 & 불러오기
    # ---------------------------------------------------------
    with st.sidebar:
        if not st.session_state.is_logged_in: st.markdown("---")
        menu = st.radio("📂 **메뉴 이동**", ["💰 배당금 계산기", "📃 전체 종목 리스트"], label_visibility="visible")
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
                    else:
                        st.caption("저장된 기록이 없습니다.")
                except Exception as e:
                    st.error("불러오기 실패")

    # =================================================================================
    # [화면 1] 배당금 계산기
    # =================================================================================
    if menu == "💰 배당금 계산기":
        st.warning("⚠️ **투자 유의사항:** 본 대시보드의 연배당률은 과거 분배금 데이터를 기반으로 계산된 참고용 지표입니다.")

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

                        # =================================================
                        # [추가] 📅 배당락일 알림 버튼 (로그인 분기 처리)
                        # =================================================
                        stock_match = df[df['pure_name'] == stock]
                        if not stock_match.empty:
                            s_row = stock_match.iloc[0]
                            ex_date = s_row.get('배당락일', '-')
                            
                            # 배당락일 정보가 있을 때만 버튼 표시
                            if ex_date and ex_date != '-':
                                # 안전 날짜 미리 계산해서 버튼 이름에 박아주기
                                _, safe_view = calculate_safe_buy_date(ex_date)
                                btn_label = f"📅 {safe_view} 매수 마감" if safe_view else "📅 알림 등록"

                                # 1. 로그인 상태 -> 진짜 링크 버튼
                                if st.session_state.get("is_logged_in", False):
                                    cal_link = make_google_calendar_link(stock, ex_date)
                                    if cal_link:
                                        st.link_button(btn_label, cal_link, use_container_width=True)
                                # 2. 비로그인 상태 -> 가짜 버튼 (토스트 메시지)
                                else:
                                    if st.button(btn_label, key=f"btn_cal_{i}", use_container_width=True):
                                        st.toast("🔒 로그인 후 캘린더에 '매수 마감일'을 등록할 수 있습니다!", icon="🔒")
                            else:
                                st.caption("📅 날짜 미정")
                    
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
                # [저장 로직] (URL 릴레이 방식)
                # =========================================================
                st.write("") 
                with st.container(border=True):
                    st.write("💾 **포트폴리오 저장 / 수정**")
                    
                    if not st.session_state.get('is_logged_in', False):
                        if "code" in st.query_params:
                             st.info("🔄 로그인 확인 중입니다... 잠시만 기다려주세요.")
                        else:
                            st.info("🔒 로그인이 필요합니다.")
                            st.caption("✅ **카카오 로그인을 추천합니다!** (네이버/카카오 앱에서도 바로 됩니다)")
                            
                            # 현재 세션 ID 가져오기 (old_id 전달용)
                            try:
                                ctx = get_script_run_ctx()
                                current_session_id = ctx.session_id
                            except:
                                current_session_id = "unknown"

                            # 1. 카카오 로그인
                            try:
                                res_kakao = supabase.auth.sign_in_with_oauth({
                                    "provider": "kakao",
                                    "options": {
                                        "redirect_to": f"https://dividend-pange.streamlit.app?old_id={current_session_id}",
                                        "skip_browser_redirect": True
                                    }
                                })
                                if res_kakao.url:
                                    btn_kakao = f'''
                                    <a href="{res_kakao.url}" target="_blank" style="
                                        display: inline-flex; justify-content: center; align-items: center; width: 100%;
                                        background-color: #FEE500; color: #000000; border: 1px solid rgba(0,0,0,0.05);
                                        padding: 0.8rem; border-radius: 0.5rem; text-decoration: none; font-weight: bold; font-size: 1.1em;
                                        box-shadow: 0 1px 2px rgba(0,0,0,0.1); margin-bottom: 10px;">
                                        💬 Kakao로 3초 만에 시작하기
                                    </a>
                                    '''
                                    st.markdown(btn_kakao, unsafe_allow_html=True)
                            except Exception as e:
                                st.error(f"Kakao 오류: {e}")

                            # 2. 구글 로그인
                            st.write("") 
                            st.markdown("---")
                            st.caption("🚨 **구글 로그인 안 되시나요?** (네이버/카카오 앱 보안 정책 때문입니다)")
                            st.caption("👉 화면 구석의 **[ ··· ]** 버튼 → **'다른 브라우저로 열기'**를 이용하시거나, 위쪽 **카카오 로그인**을 이용해 주세요.")
                            
                            if st.button("🔵 Google 로그인 (PC/크롬 추천)", key="save_google", use_container_width=True):
                                try:
                                    res = supabase.auth.sign_in_with_oauth({
                                        "provider": "google",
                                        "options": {
                                            "redirect_to": f"https://dividend-pange.streamlit.app?old_id={current_session_id}",
                                            "queryParams": {"access_type": "offline", "prompt": "consent"},
                                            "skip_browser_redirect": False
                                        }
                                    })
                                    if res.url:
                                        st.markdown(f'<meta http-equiv="refresh" content="0;url={res.url}">', unsafe_allow_html=True)
                                        st.stop()
                                except Exception as e:
                                    st.error(f"Google 오류: {e}")

                    else:
                        # [로그인 성공 시] 저장/수정 UI
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
                        # [랜덤 인카운터] 현실적인 체감을 위한 비유 아이템 목록 (업데이트)
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
                            # 돈이 너무 적어서(4500원 미만) 아무것도 못 사면 -> 제일 싼 거(스타벅스) 보여줌
                            selected_item = analogy_items[0]
                            item_count = 0
                            msg_count = f"{monthly_pocket / selected_item['price']:.1f}" # 예: 0.5잔
                        else:
                            # 살 수 있는 것 중에서만 랜덤 뽑기
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
                            if months_passed >= max_months: st.error("⚠️ 현재 적립액으로는 50년 내 달성이 어렵습니다.")
                            else: st.metric("목표 달성까지 소요 기간", f"{months_passed // 12}년 {months_passed % 12}개월")

                        if apply_inflation_goal:
                            discount_factor = (1.025) ** (months_passed / 12)
                            real_value = target_monthly_goal / discount_factor
                            st.warning(f"⚠️ **물가 반영 시:** {months_passed // 12}년 뒤 {target_monthly_goal/10000:,.0f}만원의 실질 가치는 현재 기준 **약 {real_value/10000:,.1f}만원**입니다.")
                        
                        target_annual_income = target_monthly_goal * 12
                        if target_annual_income > 20000000: st.warning(f"🚨 **현실적 조언:** 설정하신 목표(월 {target_monthly_goal/10000:,.0f}만원) 달성 시, 연 배당소득이 2,000만원을 넘어 **금융종합과세 대상**이 됩니다.")
                        st.error("""**⚠️ 시뮬레이션 활용 시 유의사항**
1. 본 결과는 주가·환율 변동과 수수료 등을 제외하고, 현재 배당률로만 계산한 결과입니다.
2. 실제 배당금은 운용사의 공시 및 환율 상황에 따라 매월 달라질 수 있습니다.
3. 과거의 데이터를 기반으로 한 단순 시뮬레이션이며, 실제 투자 수익을 보장하지 않습니다.""")

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
