import streamlit as st
import time
import random
import pandas as pd

# -----------------------------------------------------------
# [1] 스마트 필터링 엔진 (로직)
# -----------------------------------------------------------
def get_smart_recommendation(df, user_choices):
    """
    사용자의 연령, 스타일, 목표 수익률, *희망 개수*를 기반으로 
    최적의 종목을 선별합니다.
    """
    target_yield = user_choices.get('target_yield', 7.0)
    style = user_choices.get('style', 'balance')
    
    # [핵심] 사용자가 원하는 종목 개수 (기본값 5)
    wanted_count = user_choices.get('count', 5)
    
    # 1. 데이터 풀 준비 (배당률 0 초과인 것만)
    pool = df[df['연배당률'] > 0].copy()
    
    # 2. 스타일별 키워드 정의
    keywords = []
    sort_ascending = False # 기본은 배당률 높은 순
    
    if style == 'growth': # 성장 (주가 상승 + 기술주)
        keywords = ['테크', '나스닥', 'S&P', '미국', '플러스']
        sort_ascending = True # 너무 높지 않은 배당률 선호 (성장주 특성)
    elif style == 'safe': # 안정 (채권, 금, 리츠)
        keywords = ['채권', '국채', '금', '달러', '리츠', 'CD']
        sort_ascending = True 
    else: # 현금흐름 (고배당)
        keywords = ['커버드콜', '고배당', '배당', '타겟', '프리미엄']
        sort_ascending = False
        
    # 3. 1차 필터링: 키워드 매칭
    # (키워드가 이름에 하나라도 포함된 종목 추출)
    mask = pool['pure_name'].str.contains('|'.join(keywords))
    candidates = pool[mask].copy()
    
    # 만약 후보가 너무 적으면(3개 미만), 전체 풀을 사용 (안전장치)
    if len(candidates) < 3:
        candidates = pool.copy()

    # 4. 2차 필터링: 목표 배당률 매칭
    # 목표치와의 차이(절대값)가 작은 순서대로 정렬
    candidates['diff'] = abs(candidates['연배당률'] - target_yield)
    candidates = candidates.sort_values('diff')
    
    # 상위 15개 정도 후보군 확보
    top_candidates = candidates.head(15)['pure_name'].tolist()
    
    # 5. 최종 선별 (개수 반영 + 랜덤)
    # 후보가 원하는 개수보다 많으면 -> 랜덤 샘플링 (다양성)
    if len(top_candidates) >= wanted_count:
        final_picks = random.sample(top_candidates, wanted_count)
    else:
        # 부족하면 있는 거라도 다 줌
        final_picks = top_candidates
        
    # 테마 이름 짓기
    theme_title = ""
    if style == 'growth':
        theme_title = f"🚀 목표 {target_yield}%: 성장주 중심 ({len(final_picks)}종목)"
    elif style == 'safe':
        theme_title = f"🛡️ 목표 {target_yield}%: 안전자산 위주 ({len(final_picks)}종목)"
    else:
        theme_title = f"💰 목표 {target_yield}%: 강력한 현금흐름 ({len(final_picks)}종목)"
        
    return theme_title, final_picks

# -----------------------------------------------------------
# [2] UI 위자드 (3단계 질문 + 슬라이더)
# -----------------------------------------------------------
@st.dialog("🕵️ AI 포트폴리오 설계", width="small")
def show_wizard():

    # ▼▼▼ [수정 2] 여기서 데이터를 꺼냅니다 (추가된 코드) ▼▼▼
    df = st.session_state.get('shared_df')
    
    # 혹시라도 데이터가 없으면 에러 방지
    if df is None:
        st.error("데이터를 불러오지 못했습니다. 새로고침 해주세요.")
        return
    # ▲▲▲ [끝] ▲▲▲
    
    # 세션 상태 초기화
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
        if col1.button("🐣 2030", use_container_width=True):
            st.session_state.wiz_data['age'] = '2030'
            st.session_state.wiz_step = 2
            st.rerun()
        if col2.button("🦁 4050", use_container_width=True):
            st.session_state.wiz_data['age'] = '4050'
            st.session_state.wiz_step = 2
            st.rerun()
        if col3.button("🐢 60+", use_container_width=True):
            st.session_state.wiz_data['age'] = '60plus'
            st.session_state.wiz_step = 2
            st.rerun()

    # --- [STEP 2] 투자 목적 (스타일) ---
    elif step == 2:
        st.subheader("Q2. 어떤 투자를 원하세요?")
        st.write("")
        if st.button("📈 성장 추구 (주가 상승 + 배당)", use_container_width=True):
            st.session_state.wiz_data['style'] = 'growth'
            st.session_state.wiz_step = 3
            st.rerun()
        if st.button("💰 현금 흐름 (월 배당금 극대화)", use_container_width=True):
            st.session_state.wiz_data['style'] = 'flow'
            st.session_state.wiz_step = 3
            st.rerun()
        if st.button("🛡️ 안정성 (원금 방어 최우선)", use_container_width=True):
            st.session_state.wiz_data['style'] = 'safe'
            st.session_state.wiz_step = 3
            st.rerun()

    # --- [STEP 3] 목표 배당률 & 개수 (슬라이더 2개) ---
    elif step == 3:
        st.subheader("Q3. 구체적인 목표를 정해주세요")
        st.write("")
        
        # 1. 목표 수익률 슬라이더
        target = st.slider("💰 목표 연배당률 (%)", 3.0, 20.0, 7.0, 0.5, format="%f%%")
        st.session_state.wiz_data['target_yield'] = target
        
        st.write("") 
        
        # 2. [신규 기능] 종목 개수 슬라이더
        count = st.slider("📊 포트폴리오 종목 개수", 3, 7, 5)
        st.caption(f"선생님의 성향에 맞는 최적의 종목 {count}개를 선별합니다.")
        st.session_state.wiz_data['count'] = count
        
        st.write("")
        if st.button("🚀 결과 확인하기", type="primary", use_container_width=True):
            st.session_state.wiz_step = 4
            st.rerun()

    # --- [STEP 4] 결과 및 담기 ---
    elif step == 4:
        with st.spinner("데이터 분석 중..."):
            time.sleep(0.8)
            title, picks = get_smart_recommendation(df, st.session_state.wiz_data)

        # ▼▼▼ [수정된 부분] ▼▼▼
        # 로그인 아이디 가져오기 (없으면 기본값 '회원님')
        # ※ 주의: 로그인 코드에서 아이디를 저장한 변수명이 'user_id'가 맞는지 확인하세요!
        user_name = st.session_state.get("user_id", "회원님") 
        
        st.success(f"**{title}**")
        st.write(f"**{user_name}** 님의 조건에 딱 맞는 종목들입니다.")
        # ▲▲▲ [끝] ▲▲▲

        
        
        
        st.write("📋 **추천 리스트**")
        for stock in picks:
            # 리스트에 배당률 같이 표시
            row = df[df['pure_name'] == stock]
            if not row.empty:
                rate = row.iloc[0]['연배당률']
                st.text(f"- {stock} ({rate:.2f}%)")
            else:
                st.text(f"- {stock}")

        # ▼▼▼ [추가된 면책 조항] ▼▼▼
        st.markdown("---") # 구분선
        st.warning("""
        ⚠️ **투자 유의사항**
        * 본 결과는 과거 데이터를 기반으로 한 **단순 시뮬레이션**이며, **종목의 매수/매도 추천이 아닙니다.**
        * 모든 투자의 책임은 투자자 본인에게 있습니다.
        * **'안정성'**을 추구하는 포트폴리오라 할지라도 시장 변동에 따라 **원금 손실**이 발생할 수 있습니다.
        * 과거의 분배금이 미래의 수익을 보장하지 않으며, 운용사의 사정에 따라 언제든 **배당 지급이 중단**되거나 축소될 수 있습니다.
        """)
        # ▲▲▲ [끝] ▲▲▲
      
        st.divider()
        col_a, col_b = st.columns(2)
        
        if col_a.button("🔄 다시 하기"):
            st.session_state.wiz_step = 1
            st.rerun()
            
        if col_b.button("✅ 장바구니 담기", type="primary"):
            st.session_state.selected_stocks = picks
            st.toast("포트폴리오가 설정되었습니다! 🛒", icon="✅")
            time.sleep(1.5)
            st.session_state.wiz_step = 1 # 초기화
            st.rerun()
