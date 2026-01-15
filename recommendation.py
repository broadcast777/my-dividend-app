import streamlit as st
import time
import random
import pandas as pd

# -----------------------------------------------------------
# [1] 스마트 필터링 엔진 (로직)
# -----------------------------------------------------------
def get_smart_recommendation(df, user_choices):
    target_yield = user_choices.get('target_yield', 7.0)
    style = user_choices.get('style', 'balance')
    wanted_count = user_choices.get('count', 5)
    
    pool = df[df['연배당률'] > 0].copy()
    
    keywords = []
    
    if style == 'growth':
        keywords = ['테크', '나스닥', 'S&P', '미국', '플러스','성장']
    elif style == 'safe':
        keywords = ['채권', '국채', '금', '달러', '리츠', 'CD']
    else:
        keywords = ['커버드콜', '고배당', '배당', '타겟', '프리미엄']
        
    mask = pool['pure_name'].str.contains('|'.join(keywords))
    candidates = pool[mask].copy()
    
    if len(candidates) < 3:
        candidates = pool.copy()

    candidates['diff'] = abs(candidates['연배당률'] - target_yield)
    candidates = candidates.sort_values('diff')
    
    top_candidates = candidates.head(15)['pure_name'].tolist()
    
    if len(top_candidates) >= wanted_count:
        final_picks = random.sample(top_candidates, wanted_count)
    else:
        final_picks = top_candidates
        
    theme_title = ""
    if style == 'growth':
        theme_title = f"🚀 목표 {target_yield}%: 성장주 중심 ({len(final_picks)}종목)"
    elif style == 'safe':
        theme_title = f"🛡️ 목표 {target_yield}%: 안전자산 위주 ({len(final_picks)}종목)"
    else:
        theme_title = f"💰 목표 {target_yield}%: 현금흐름 추구 ({len(final_picks)}종목)"
        
    return theme_title, final_picks

# -----------------------------------------------------------
# [2] 화면 전환 도우미
# -----------------------------------------------------------
def go_next_step(next_step_num, key=None, value=None):
    st.session_state.wiz_step = next_step_num
    if key is not None:
        st.session_state.wiz_data[key] = value

def reset_wizard():
    st.session_state.wiz_step = 1
    st.session_state.wiz_data = {}

# -----------------------------------------------------------
# [3] UI 위자드
# -----------------------------------------------------------
@st.dialog("🕵️ AI 포트폴리오 설계", width="small")
def show_wizard():
    # 1. 안전하게 데이터 꺼내기
    df = st.session_state.get('shared_df')
    if df is None:
        st.error("데이터 오류! 새로고침 해주세요.")
        return

    # 2. 상태 초기화
    if "wiz_step" not in st.session_state:
        st.session_state.wiz_step = 1
    if "wiz_data" not in st.session_state:
        st.session_state.wiz_data = {}

    step = st.session_state.wiz_step

    # --- [STEP 1] 연령대 ---
    if step == 1:
        st.subheader("Q1. 연령대가 어떻게 되시나요?")
        st.write("")
        col1, col2, col3 = st.columns(3)
        col1.button("🐣 2030", use_container_width=True, on_click=go_next_step, args=(2, 'age', '2030'))
        col2.button("🦁 4050", use_container_width=True, on_click=go_next_step, args=(2, 'age', '4050'))
        col3.button("🐢 60+", use_container_width=True, on_click=go_next_step, args=(2, 'age', '60plus'))

    # --- [STEP 2] 투자 목적 ---
    elif step == 2:
        st.subheader("Q2. 어떤 투자를 원하세요?")
        st.write("")
        st.button("📈 성장 추구 (주가 상승 + 배당)", use_container_width=True, on_click=go_next_step, args=(3, 'style', 'growth'))
        st.button("💰 현금 흐름 (월 배당금 극대화)", use_container_width=True, on_click=go_next_step, args=(3, 'style', 'flow'))
        st.button("🛡️ 안정성 (원금 방어 최우선)", use_container_width=True, on_click=go_next_step, args=(3, 'style', 'safe'))

    # --- [STEP 3] 목표 설정 ---
    elif step == 3:
        st.subheader("Q3. 구체적인 목표를 정해주세요")
        st.write("")
        target = st.slider("💰 목표 연배당률 (%)", 3.0, 20.0, 7.0, 0.5, format="%f%%")
        count = st.slider("📊 포트폴리오 종목 개수", 3, 7, 5)
        st.write("")
        
        def save_and_go():
            st.session_state.wiz_data['target_yield'] = target
            st.session_state.wiz_data['count'] = count
            st.session_state.wiz_step = 4

        st.button("🚀 결과 확인하기", type="primary", use_container_width=True, on_click=save_and_go)

    # --- [STEP 4] 결과 및 담기 ---
    elif step == 4:
        with st.spinner("데이터 분석 중..."):
            time.sleep(0.5) 
            title, picks = get_smart_recommendation(df, st.session_state.wiz_data)
        
        user_name = st.session_state.get("user_id", st.session_state.get("user_email", "회원님"))
        if "@" in user_name: user_name = user_name.split("@")[0]

        st.success(f"**{title}**")
        st.write(f"**{user_name}** 님의 조건에 딱 맞는 종목들입니다.")
        
        st.write("📋 **추천 리스트**")
        for stock in picks:
            row = df[df['pure_name'] == stock]
            if not row.empty:
                rate = row.iloc[0]['연배당률']
                st.text(f"- {stock} ({rate:.2f}%)")
            else:
                st.text(f"- {stock}")
        
        st.markdown("---")
        st.warning("""
        ⚠️ **투자 유의사항 **
        * 본 결과는 과거 데이터를 기반으로 한 단순 시뮬레이션이며, 종목의 매수/매도 추천이 아닙니다.
        * 모든 투자의 책임은 투자자 본인에게 있습니다.
        * '안정성'을 추구하는 포트폴리오라 할지라도 시장 변동에 따라 원금 손실이 발생할 수 있습니다.
        """)
        
        col_a, col_b = st.columns(2)
        col_a.button("🔄 다시 하기", on_click=reset_wizard)
        
        def finish():
            st.session_state.selected_stocks = picks
            st.session_state.wiz_step = 1

        if col_b.button("✅ 장바구니 담기", type="primary", on_click=finish):
            st.rerun()
