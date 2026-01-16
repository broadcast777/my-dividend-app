"""
프로젝트: 배당 팽이 (Dividend Top) v1.5
파일명: recommendation.py
설명: AI 로보어드바이저 엔진 (정규식 필터링 & 자동 완화 로직 적용)
"""

import streamlit as st
import pandas as pd
import re  # [추가] 날짜 정밀 분석을 위한 정규식 모듈

# -----------------------------------------------------------
# [SECTION 1] 내부 헬퍼 함수 (엔진 부품)
# -----------------------------------------------------------

def _parse_day_category(date_str):
    """
    날짜 문자열을 분석하여 '초/중/말' 카테고리로 분류합니다.
    Args: date_str (예: '2024-04-15', '매월 15일', '4월 말')
    Returns: 'early' | 'mid' | 'end' | 'unknown'
    """
    s = str(date_str).strip()
    
    # 1. 명시적 키워드 우선 확인
    if any(k in s for k in ['말일', '마지막', '30일', '31일', '29일', '28일', '하순']):
        return 'end'
    if any(k in s for k in ['초', '1일', '5일']):
        return 'early'
    if any(k in s for k in ['중순']):
        return 'mid'
        
    # 2. 숫자 추출을 통한 날짜 판별 (정규식)
    # "2024-04-15" -> 15 추출, "매월 10일" -> 10 추출
    numbers = re.findall(r'\d+', s)
    if numbers:
        day = int(numbers[-1]) # 맨 마지막 숫자를 일(Day)로 간주
        if 1 <= day <= 10: return 'early'
        if 11 <= day <= 20: return 'mid'
        if 21 <= day <= 31: return 'end'
        
    return 'unknown'

def _check_timing_match(row_date, user_timing):
    """사용자가 원하는 시기(user_timing)와 종목의 배당일(row_date)이 일치하는지 판별"""
    if user_timing == 'mix': return True # 상관없음
    
    cat = _parse_day_category(row_date)
    
    if user_timing == 'mid':
        return cat == 'mid' # 11~20일
    elif user_timing == 'end':
        return cat == 'end' or cat == 'early' # 월말~월초 (월급날 전후)
    
    return True

# -----------------------------------------------------------
# [SECTION 2] 스마트 필터링 & 비중 최적화 엔진
# -----------------------------------------------------------

# recommendation.py 의 get_smart_recommendation 함수 전체를 이것으로 교체

def get_smart_recommendation(df, user_choices):
    """
    사용자 입력 분석 및 포트폴리오 최적화
    (개선: CC 쿼터제 + ★성장/안정 테마 의무 할당 + 개수별 가변 비중 시스템★)
    """
    
    # 1. 사용자 입력 추출
    target_yield = user_choices.get('target_yield', 7.0)
    style = user_choices.get('style', 'balance')
    wanted_count = user_choices.get('count', 3)
    timing = user_choices.get('timing', 'mix')
    
    # 2. 데이터 준비
    pool = df[df['연배당률'] > 0].copy()
    pool['temp_date_str'] = pool['배당락일'].fillna('').astype(str)
    
    # 3. 필터링 (스타일/시기)
    filtered_pool = pd.DataFrame()
    filter_stage = "strict" 
    
    # (A) 안정형 필터 (수익률 상한선)
    if style == 'safe':
        pool = pool[pool['연배당률'] <= 6.5]
        target_yield = min(target_yield, 6.0)
    
    # (B) 시기 필터
    mask_timing = pool['temp_date_str'].apply(lambda x: _check_timing_match(x, timing))
    first_try = pool[mask_timing].copy()
    
    if not first_try.empty and len(first_try) >= wanted_count:
        filtered_pool = first_try
    else:
        filtered_pool = pool.copy()
        filter_stage = "relaxed"
        
    if filtered_pool.empty: return "조건에 맞는 종목 없음", [], {}

    # 4. 키워드 정의
    growth_keywords = ['나스닥', 'nasdaq', 's&p', '미국', '테크', '성장', 'schd', 'qqq', 'spy', 'top10', 'magnificent', 'tech']
    safe_keywords = ['채권', '국채', 'treasury', '금', 'gold', '달러', 'bond', 'tlt', 'safe', '파킹', 'cd']
    cc_keywords = ['커버드', 'covered', 'call', 'jepi', 'qyld', 'tsly', 'play', 'high', 'premium']

    def has_keyword(row, keywords):
        text = (str(row['종목명']) + " " + str(row.get('pure_name', ''))).lower()
        return any(k.lower() in text for k in keywords)

    # 5. 점수 산정 (Scoring)
    filtered_pool['yield_diff'] = abs(filtered_pool['연배당률'] - target_yield)
    filtered_pool['score'] = 100 - (filtered_pool['yield_diff'] * 10)
    
    if style == 'growth':
        mask = filtered_pool.apply(lambda x: has_keyword(x, growth_keywords), axis=1)
        filtered_pool.loc[mask, 'score'] += 50 
    elif style == 'safe':
        # 안정형이면 채권/금 등 안전자산에 엄청난 가산점
        mask = filtered_pool.apply(lambda x: has_keyword(x, safe_keywords), axis=1)
        filtered_pool.loc[mask, 'score'] += 50
    elif style == 'flow':
        filtered_pool['score'] += filtered_pool['연배당률'] * 2 
        mask = filtered_pool.apply(lambda x: has_keyword(x, cc_keywords), axis=1)
        filtered_pool.loc[mask, 'score'] += 15

    filtered_pool = filtered_pool.sort_values('score', ascending=False)

    # -------------------------------------------------------
    # [교정 5] ★ 선발 로직 (테마별 대장주 의무화 + CC 쿼터제) ★
    # -------------------------------------------------------
    final_picks = []
    cc_count = 0
    MAX_CC = 2
    
    # (1) 의무 할당 (낙하산 인사)
    # 성장형 -> 성장주 1등 / 안정형 -> 안전자산 1등 무조건 선발
    priority_keywords = []
    if style == 'growth': priority_keywords = growth_keywords
    elif style == 'safe': priority_keywords = safe_keywords
    
    if priority_keywords:
        candidates = filtered_pool[filtered_pool.apply(lambda x: has_keyword(x, priority_keywords), axis=1)]
        if not candidates.empty:
            best_pick = candidates.iloc[0]
            final_picks.append(best_pick['pure_name'])
            if has_keyword(best_pick, cc_keywords): cc_count += 1

    # (2) 나머지 채우기
    for idx, row in filtered_pool.iterrows():
        if len(final_picks) >= wanted_count: break
        if row['pure_name'] in final_picks: continue
            
        is_cc = has_keyword(row, cc_keywords)
        if is_cc and cc_count >= MAX_CC: continue
            
        final_picks.append(row['pure_name'])
        if is_cc: cc_count += 1
        
    # (3) 모자라면 강제 채우기 (CC 제외 2차 방어선)
    if len(final_picks) < wanted_count:
        remain_pool = filtered_pool[~filtered_pool['pure_name'].isin(final_picks)].copy()
        if cc_count >= MAX_CC:
             mask_cc = remain_pool.apply(lambda x: has_keyword(x, cc_keywords), axis=1)
             remain_pool = remain_pool[~mask_cc]
        if not remain_pool.empty:
            final_picks.extend(remain_pool.head(wanted_count - len(final_picks))['pure_name'].tolist())

    selected_pool = filtered_pool[filtered_pool['pure_name'].isin(final_picks)].copy()

    # -------------------------------------------------------
    # [교정 6] ★ 비중 최적화 (가변 비중 시스템 적용) ★
    # -------------------------------------------------------
    if selected_pool.empty: return "종목 선정 실패", [], {}

    selected_pool['sort_cat'] = pd.Categorical(selected_pool['pure_name'], categories=final_picks, ordered=True)
    selected_pool = selected_pool.sort_values('sort_cat')

    # 기본 비중 계산
    yields = selected_pool['연배당률'].values
    inv_dist = 1 / (abs(yields - target_yield) + 0.5) 
    weights = (inv_dist / inv_dist.sum()) * 100
    
    # [가변 최소 비중 설정] 사장님 요청 로직 반영
    # 3개 -> 30%, 4개 -> 25%, 5개 -> 20%
    min_weight_map = {3: 30.0, 4: 25.0, 5: 20.0}
    # 혹시 모를 예외(6개 이상 등)를 위해 기본값 20.0 설정
    min_threshold = min_weight_map.get(len(final_picks), 20.0)

    # [대장주 비중 부스팅] 성장형 or 안정형일 때만 적용
    if style in ['growth', 'safe']:
        # 첫 번째 종목(대장주) 확인
        first_row = selected_pool.iloc[0]
        # 진짜 우리가 원하는 키워드를 가진 녀석인지 확인
        target_keys = growth_keywords if style == 'growth' else safe_keywords
        
        if has_keyword(first_row, target_keys):
             # 현재 비중이 최소컷보다 낮으면 강제로 끌어올림
             if weights[0] < min_threshold:
                 weights[0] = min_threshold
                 # 나머지 종목들은 남은 파이(100 - 최소컷)를 나눠가짐
                 if len(weights) > 1:
                     other_sum = weights[1:].sum()
                     if other_sum > 0:
                         weights[1:] = (weights[1:] / other_sum) * (100.0 - min_threshold)

    weights = weights.round().astype(int)
    
    # 100% 맞춤 보정
    diff = 100 - weights.sum()
    if len(weights) > 0:
        weights[0] += diff 
    
    pick_weights = dict(zip(selected_pool['pure_name'], weights))
    
    timing_badge = {"mid": "15일 배당", "end": "월말 배당", "mix": "맞춤"}
    prefix = "(날짜 유연) " if filter_stage == "relaxed" and timing != 'mix' else ""
    theme_title = f"{prefix}{timing_badge.get(timing, '맞춤')} 포트폴리오"
        
    return theme_title, final_picks, pick_weights


# -----------------------------------------------------------
# [SECTION 3] 화면 전환 도우미
# -----------------------------------------------------------

def go_next_step(next_step_num, key=None, value=None):
    """설계 마법사의 다음 단계로 이동하고 입력 데이터를 세션에 저장합니다."""
    st.session_state.wiz_step = next_step_num
    if key is not None:
        st.session_state.wiz_data[key] = value

def reset_wizard():
    """마법사 상태와 캐시된 데이터를 초기화합니다."""
    st.session_state.wiz_step = 1
    st.session_state.wiz_data = {}
    if "ai_result_cache" in st.session_state:
        del st.session_state.ai_result_cache


# -----------------------------------------------------------
# [SECTION 4] UI 위자드 (Step 1 ~ 5)
# -----------------------------------------------------------

@st.dialog("🕵️ AI 포트폴리오 설계", width="small")
def show_wizard():
    """다이얼로그 형태의 인터랙티브 설문 조사를 통해 포트폴리오를 설계합니다."""
    
    df = st.session_state.get('shared_df')
    if df is None:
        st.error("데이터 로딩 중입니다. 잠시 후 다시 시도해주세요.")
        return

    if "wiz_step" not in st.session_state: st.session_state.wiz_step = 1
    if "wiz_data" not in st.session_state: st.session_state.wiz_data = {}

    step = st.session_state.wiz_step

    # --- [STEP 1] 연령대 ---
    if step == 1:
        st.subheader("Q1. 연령대가 어떻게 되시나요?")
        c1, c2, c3 = st.columns(3)
        c1.button("🐣 2030", use_container_width=True, on_click=go_next_step, args=(2, 'age', '2030'))
        c2.button("🦁 4050", use_container_width=True, on_click=go_next_step, args=(2, 'age', '4050'))
        c3.button("🐢 60+", use_container_width=True, on_click=go_next_step, args=(2, 'age', '60plus'))

    # --- [STEP 2] 투자 스타일 ---
    elif step == 2:
        st.subheader("Q2. 어떤 투자를 원하세요?")
        st.button("📈 성장 추구 (주가 상승 + 배당)", use_container_width=True, on_click=go_next_step, args=(3, 'style', 'growth'))
        st.button("💰 현금 흐름 (월 배당금 극대화)", use_container_width=True, on_click=go_next_step, args=(3, 'style', 'flow'))
        st.button("🛡️ 안정성 (원금 방어 최우선)", use_container_width=True, on_click=go_next_step, args=(3, 'style', 'safe'))

    # --- [STEP 3] 배당 시기 ---
    elif step == 3:
        st.subheader("Q3. 선호하는 배당 날짜는요?")
        st.button("🗓️ 월중 (매월 15일 경)", use_container_width=True, on_click=go_next_step, args=(4, 'timing', 'mid'))
        st.button("🔚 월말/월초 (월급날 전후)", use_container_width=True, on_click=go_next_step, args=(4, 'timing', 'end'))
        st.button("🔄 상관없음 (섞어서 2주마다 받기)", use_container_width=True, on_click=go_next_step, args=(4, 'timing', 'mix'))

    # --- [STEP 4] 목표 배당률 ---
    elif step == 4:
        st.subheader("Q4. 구체적인 목표를 정해주세요")
        target = st.slider("💰 목표 연배당률 (%)", 3.0, 20.0, 7.0, 0.5)
        
        current_style = st.session_state.wiz_data.get('style')
        if current_style == 'safe':
            st.info("🛡️ **안정형 모드:** 자산 보호를 위해 배당률이 **6.5% 이하**인 종목 위주로 선정됩니다.")
        elif target >= 10.0:
            st.error(f"⚠️ **고배당 유의 ({target}%)**: 원금 손실 위험이 큰 커버드콜/초고배당주가 포함될 수 있습니다.")
        elif target >= 8.0:
            st.warning("💡 8% 이상은 중위험 종목이 포함될 수 있습니다.")
            
        count = st.slider("📊 종목 개수", 3, 5, 3)
        
        if st.button("🚀 결과 확인하기", type="primary", use_container_width=True):
            st.session_state.wiz_data['target_yield'] = target
            st.session_state.wiz_data['count'] = count
            st.session_state.wiz_step = 5
            st.rerun()

    # --- [STEP 5] 결과 ---
    elif step == 5:
        if "ai_result_cache" not in st.session_state:
            with st.spinner("최적 조합 계산 중..."):
                t_res, p_res, w_res = get_smart_recommendation(df, st.session_state.wiz_data)
                st.session_state.ai_result_cache = {"title": t_res, "picks": p_res, "weights": w_res}
        
        cached = st.session_state.ai_result_cache
        title, picks, weights = cached["title"], cached["picks"], cached["weights"]

        if not picks or title == "조건에 맞는 종목 없음":
            st.error("❌ 조건에 맞는 종목을 찾지 못했습니다.")
            st.caption("조건을 조금만 더 넓혀서 다시 시도해 보세요!")
            if st.button("처음으로 돌아가기", use_container_width=True):
                reset_wizard()
                st.rerun()
            return

        # 결과 출력
        st.success(f"**{title}**")
        if "(날짜 유연)" in title:
            st.caption("💡 선택하신 날짜에 맞는 종목이 부족하여, 날짜 조건을 조금 완화하여 추천했습니다.")
            
        for stock in picks:
            row_match = df[df['pure_name'] == stock]
            if not row_match.empty:
                row = row_match.iloc[0]
                w = weights.get(stock, 0)
                st.markdown(f"✅ **{stock}** (비중 **{w}%**)")
                st.caption(f"    └ 💰 연 {row['연배당률']:.2f}% | 📅 {row.get('배당락일', '-')}")

        st.write("") 
        st.warning("""
        ⚠️ **투자 유의사항**
        * 본 결과는 과거 데이터를 기반으로 한 단순 시뮬레이션이며, 종목의 매수/매도 추천이 아닙니다.
        * 모든 투자의 책임은 투자자 본인에게 있습니다.
        """)

        st.divider()
        c_a, c_b = st.columns(2)
        c_a.button("🔄 다시 하기", on_click=reset_wizard, use_container_width=True)
        
        if c_b.button("✅ 담기", type="primary", use_container_width=True):
            st.session_state.selected_stocks = picks
            st.session_state.ai_suggested_weights = weights
            st.session_state.ai_modal_open = False
            if "ai_result_cache" in st.session_state: del st.session_state.ai_result_cache
            
            # 세션 백업/복구 (Rerun 시 데이터 증발 방지)
            u_bk = st.session_state.get("user_info")
            l_bk = st.session_state.get("is_logged_in")
            st.toast("장바구니에 담았습니다! 🛒", icon="✅")
            st.session_state.user_info = u_bk
            st.session_state.is_logged_in = l_bk
            st.rerun()
