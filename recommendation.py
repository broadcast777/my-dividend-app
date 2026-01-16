import streamlit as st
import time
import random
import pandas as pd

# -----------------------------------------------------------
# [1] 스마트 필터링 & 비중 최적화 엔진 (V5.0)
# -----------------------------------------------------------
def get_smart_recommendation(df, user_choices):
    # 1. 사용자 입력 추출
    target_yield = user_choices.get('target_yield', 7.0)
    style = user_choices.get('style', 'balance')
    wanted_count = user_choices.get('count', 3)
    timing = user_choices.get('timing', 'mix')
    age = user_choices.get('age', '4050')
    
    # 2. 데이터 복사 (배당률 있는 것만)
    pool = df[df['연배당률'] > 0].copy()

    # -------------------------------------------------------
    # [수정/추가] ★ 배당 시기 엄격 필터링 (Hard Filter) ★
    # -------------------------------------------------------
    if '배당락일' in pool.columns:
        pool['배당락일'] = pool['배당락일'].fillna('').astype(str)
        
        if timing == 'mid': 
            # 중순(15일 전후)이 포함되지 않은 종목은 풀에서 즉시 제거
            pool = pool[pool['배당락일'].str.contains('15일|14일|16일|중순')]
            
        elif timing == 'end': 
            # 월말/월초가 포함되지 않은 종목은 풀에서 즉시 제거
            pool = pool[pool['배당락일'].str.contains('마지막|말일|30일|31일|28일|29일|초|하순')]
            
        # 'mix'는 필터 없이 그대로 진행

    # [중요] 필터링 후 종목이 하나도 없으면 에러 방지를 위해 빈 결과 리턴
    if pool.empty:
        return "조건에 맞는 종목 없음", [], {}
    # -------------------------------------------------------

    # [수익률 우선순위 점수] - 여기서부터는 기존 로직 그대로...
    if target_yield >= 10.0:
        pool['score'] = pool['연배당률'] * 5.0 
    else:
        pool['score'] = -abs(pool['연배당률'] - target_yield) * 3.0
    
    # [수익률 우선순위 점수]
    if target_yield >= 10.0:
        pool['score'] = pool['연배당률'] * 5.0 
    else:
        pool['score'] = -abs(pool['연배당률'] - target_yield) * 3.0

    # 키워드 매칭 함수 정의
    def has_keyword(row, keywords):
        text = (str(row['종목명']) + " " + str(row.get('pure_name', ''))).lower()
        return any(k.lower() in text for k in keywords)

    # 스타일별 가중치 (V4.0 로직 유지)
    if style == 'growth':
        mask = pool.apply(lambda x: has_keyword(x, ['나스닥', 'nasdaq', 'S&P', '미국', '테크', '성장', '다우존스']), axis=1)
        pool.loc[mask, 'score'] += 6
    elif style == 'flow':
        pool['score'] += pool['연배당률'] * 0.8
        flow_keys = ['커버드콜', 'covered', '타겟', 'premium', '월지급', '리츠', 'reit', '고배당', '우선주', 'pff', 'jepi']
        mask = pool.apply(lambda x: has_keyword(x, flow_keys), axis=1)
        pool.loc[mask, 'score'] += 6
    elif style == 'safe':
        safe_keys = ['채권', '국채', '금', 'gold', '달러', 'CD', 'KOFR', '단기', 'treasury', 'bond']
        mask_safe = pool.apply(lambda x: has_keyword(x, safe_keys), axis=1)
        pool.loc[mask_safe, 'score'] += 10

    # 점수 순 정렬 후 추출
    pool = pool.sort_values('score', ascending=False)
    selected_pool = pool.head(wanted_count).copy()
    final_picks = selected_pool['pure_name'].tolist()

    # [비중 최적화 로직]
    yields = selected_pool['연배당률'].values
    inv_dist = 1 / (abs(yields - target_yield) + 0.1) 
    weights = (inv_dist / inv_dist.sum()) * 100
    weights = weights.round().astype(int)
    weights[-1] = 100 - weights[:-1].sum() 
    
    pick_weights = dict(zip(final_picks, weights))
    
    timing_badge = {"mid": "15일 월중배당", "end": "월말/월초배당", "mix": "날짜 혼합"}
    theme_title = f"{timing_badge.get(timing, '맞춤')} 포트폴리오"
        
    return theme_title, final_picks, pick_weights

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
    if "ai_result_cache" in st.session_state:
        del st.session_state.ai_result_cache

# -----------------------------------------------------------
# [3] UI 위자드 (최종 완성본)
# -----------------------------------------------------------
@st.dialog("🕵️ AI 포트폴리오 설계", width="small")
def show_wizard():
    df = st.session_state.get('shared_df')
    if df is None:
        st.error("데이터 오류! 새로고침 해주세요.")
        return

    if "wiz_step" not in st.session_state:
        st.session_state.wiz_step = 1
    if "wiz_data" not in st.session_state:
        st.session_state.wiz_data = {}

    step = st.session_state.wiz_step

    if step == 1:
        st.subheader("Q1. 연령대가 어떻게 되시나요?")
        c1, c2, c3 = st.columns(3)
        c1.button("🐣 2030", use_container_width=True, on_click=go_next_step, args=(2, 'age', '2030'))
        c2.button("🦁 4050", use_container_width=True, on_click=go_next_step, args=(2, 'age', '4050'))
        c3.button("🐢 60+", use_container_width=True, on_click=go_next_step, args=(2, 'age', '60plus'))

    elif step == 2:
        st.subheader("Q2. 어떤 투자를 원하세요?")
        st.button("📈 성장 추구 (주가 상승 + 배당)", use_container_width=True, on_click=go_next_step, args=(3, 'style', 'growth'))
        st.button("💰 현금 흐름 (월 배당금 극대화)", use_container_width=True, on_click=go_next_step, args=(3, 'style', 'flow'))
        st.button("🛡️ 안정성 (원금 방어 최우선)", use_container_width=True, on_click=go_next_step, args=(3, 'style', 'safe'))

    elif step == 3:
        st.subheader("Q3. 선호하는 배당 날짜는요?")
        st.button("🗓️ 월중 (매월 15일 경)", use_container_width=True, on_click=go_next_step, args=(4, 'timing', 'mid'))
        st.button("🔚 월말/월초 (월급날 전후)", use_container_width=True, on_click=go_next_step, args=(4, 'timing', 'end'))
        st.button("🔄 상관없음 (섞어서 2주마다 받기)", use_container_width=True, on_click=go_next_step, args=(4, 'timing', 'mix'))

    elif step == 4:
        st.subheader("Q4. 구체적인 목표를 정해주세요")
        target = st.slider("💰 목표 연배당률 (%)", 3.0, 20.0, 7.0, 0.5)
        
        # [주의 멘트 로직]
        if target >= 10.0:
            st.error(f"⚠️ **고배당 투자 유의사항 ({target}%)**\n\n원금 손실 위험이 큰 '커버드콜' 종목 위주로 구성될 수 있습니다.")
        elif target >= 8.0:
            st.warning("💡 8% 이상은 중위험 종목이 포함될 수 있습니다.")
            
        count = st.slider("📊 종목 개수", 3, 5, 3)
        
        if st.button("🚀 결과 확인하기", type="primary", use_container_width=True):
            st.session_state.wiz_data['target_yield'] = target
            st.session_state.wiz_data['count'] = count
            st.session_state.wiz_step = 5
            st.rerun()

    elif step == 5:
        if "ai_result_cache" not in st.session_state:
            with st.spinner("최적 비중 계산 중..."):
                t_res, p_res, w_res = get_smart_recommendation(df, st.session_state.wiz_data)
                st.session_state.ai_result_cache = {"title": t_res, "picks": p_res, "weights": w_res}
        
        cached = st.session_state.ai_result_cache
        title, picks, weights = cached["title"], cached["picks"], cached["weights"]

        st.success(f"**{title}**")
        for stock in picks:
            row = df[df['pure_name'] == stock].iloc[0]
            w = weights.get(stock, 0)
            st.markdown(f"✅ **{stock}** (비중 **{w}%**)")
            st.caption(f"   └ 💰 연 {row['연배당률']:.2f}% | 📅 {row.get('배당락일', '-')}")

        st.divider()
        c_a, c_b = st.columns(2)
        c_a.button("🔄 다시 하기", on_click=reset_wizard, use_container_width=True)
        if c_b.button("✅ 담기", type="primary", use_container_width=True):
            st.session_state.selected_stocks = picks
            st.session_state.ai_suggested_weights = weights
            st.session_state.ai_modal_open = False
            st.rerun()
