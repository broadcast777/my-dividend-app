"""
프로젝트: 배당 팽이 (Dividend Top) v1.6.1
파일명: recommendation.py
설명: AI 로보어드바이저 엔진 (셔플 기능 + 리츠 1개 제한 + 쿼터제 + 안내문구 복구)
"""

import streamlit as st
import pandas as pd
import re
import random 

# -----------------------------------------------------------
# [SECTION 1] 내부 헬퍼 함수
# -----------------------------------------------------------

def _parse_day_category(date_str):
    s = str(date_str).strip()
    if any(k in s for k in ['말일', '마지막', '30일', '31일', '29일', '28일', '하순']): return 'end'
    if any(k in s for k in ['초', '1일', '5일']): return 'early'
    if any(k in s for k in ['중순']): return 'mid'
    numbers = re.findall(r'\d+', s)
    if numbers:
        day = int(numbers[-1])
        if 1 <= day <= 10: return 'early'
        if 11 <= day <= 20: return 'mid'
        if 21 <= day <= 31: return 'end'
    return 'unknown'

def _check_timing_match(row_date, user_timing):
    if user_timing == 'mix': return True
    cat = _parse_day_category(row_date)
    if user_timing == 'mid': return cat == 'mid'
    elif user_timing == 'end': return cat == 'end' or cat == 'early'
    return True

# -----------------------------------------------------------
# [SECTION 2] 스마트 필터링 & 비중 최적화 엔진
# -----------------------------------------------------------

def get_smart_recommendation(df, user_choices):
    """
    사용자 입력 분석 및 포트폴리오 최적화
    (업데이트: 랜덤 셔플 + 리츠 1개 제한)
    """
    
    # 1. 사용자 입력 추출
    target_yield = user_choices.get('target_yield', 7.0)
    style = user_choices.get('style', 'balance')
    wanted_count = user_choices.get('count', 3)
    timing = user_choices.get('timing', 'mix')
    
    # 2. 데이터 준비
    pool = df[df['연배당률'] > 0].copy()
    pool['temp_date_str'] = pool['배당락일'].fillna('').astype(str)
    
    # 3. 필터링
    filtered_pool = pd.DataFrame()
    filter_stage = "strict" 
    
    if style == 'safe':
        pool = pool[pool['연배당률'] <= 10.0]
        target_yield = min(target_yield, 6.0)
    
    mask_timing = pool['temp_date_str'].apply(lambda x: _check_timing_match(x, timing))
    first_try = pool[mask_timing].copy()
    
    if not first_try.empty and len(first_try) >= wanted_count:
        filtered_pool = first_try
    else:
        filtered_pool = pool.copy()
        filter_stage = "relaxed"
        
    if filtered_pool.empty: return "조건에 맞는 종목 없음", [], {}

    # 4. 키워드 정의
    growth_keywords = ['나스닥', 'nasdaq', 's&p', '테크', '성장', 'schd', 'qqq', 'spy', 'top10', 'magnificent', 'tech', '다우존스', 'dow', '배당성장', '플러스배당']
    safe_keywords = ['채권', '국채', 'treasury', '금', 'gold', '달러', 'bond', 'tlt', 'safe', '파킹', 'cd']
    cc_keywords = ['커버드', 'covered', 'call', 'jepi', 'qyld', 'tsly', 'play', 'high', 'premium']
    cash_keywords = ['shv', 'bil', 'sgov', 'cd', 'kofr', '파킹', '단기채', '초단기']
    bond_keywords = ['채권', '국채', 'treasury', 'bond', 'tlt'] 
    reit_keywords = ['리츠', 'reit', '부동산', 'infra', '인프라']

    def has_keyword(row, keywords):
        text = (str(row['종목명']) + " " + str(row.get('pure_name', ''))).lower()
        return any(k.lower() in text for k in keywords)

    # 5. 점수 산정 (Scoring + Random Shuffle)
    filtered_pool['yield_diff'] = abs(filtered_pool['연배당률'] - target_yield)
    filtered_pool['score'] = 100 - (filtered_pool['yield_diff'] * 10)
    
    # [가산점 로직]
    if style == 'growth':
        mask = filtered_pool.apply(lambda x: has_keyword(x, growth_keywords), axis=1)
        filtered_pool.loc[mask, 'score'] += 50 
        mask_fake = filtered_pool.apply(lambda x: has_keyword(x, safe_keywords), axis=1)
        filtered_pool.loc[mask_fake, 'score'] -= 30

    elif style == 'safe':
        mask = filtered_pool.apply(lambda x: has_keyword(x, safe_keywords), axis=1)
        filtered_pool.loc[mask, 'score'] += 100 

    elif style == 'flow':
        filtered_pool['score'] += filtered_pool['연배당률'] * 2 
        mask = filtered_pool.apply(lambda x: has_keyword(x, cc_keywords), axis=1)
        filtered_pool.loc[mask, 'score'] += 15
        mask_reit = filtered_pool.apply(lambda x: has_keyword(x, reit_keywords), axis=1)
        filtered_pool.loc[mask_reit, 'score'] += 10

    # [핵심] 랜덤 노이즈 추가 (셔플 효과)
    filtered_pool['random_luck'] = [random.uniform(0, 15) for _ in range(len(filtered_pool))]
    filtered_pool['score'] += filtered_pool['random_luck']

    filtered_pool = filtered_pool.sort_values('score', ascending=False)

    # -------------------------------------------------------
    # [교정 5] ★ 선발 로직 (쿼터제 적용)
    # -------------------------------------------------------
    final_picks = []
    
    cc_count = 0
    cash_count = 0 
    bond_count = 0 
    reit_count = 0 
    
    # [쿼터 설정]
    MAX_CC = 2
    MAX_CASH = 1
    MAX_BOND = 1
    MAX_REIT = 1 # 리츠 1개 제한
    
    # [1] 의무 선발
    if style == 'safe':
        safe_candidates = filtered_pool[filtered_pool.apply(lambda x: has_keyword(x, safe_keywords), axis=1)]
        if not safe_candidates.empty:
            best_safe = safe_candidates.iloc[0]
            final_picks.append(best_safe['pure_name'])
            if has_keyword(best_safe, cash_keywords): cash_count += 1
            elif has_keyword(best_safe, bond_keywords): bond_count += 1
            
        growth_candidates = filtered_pool[filtered_pool.apply(lambda x: has_keyword(x, growth_keywords), axis=1)]
        growth_candidates = growth_candidates[~growth_candidates['pure_name'].isin(final_picks)]
        if not growth_candidates.empty:
            best_growth = growth_candidates.iloc[0]
            final_picks.append(best_growth['pure_name'])
            if has_keyword(best_growth, cc_keywords): cc_count += 1

    elif style == 'growth':
        growth_candidates = filtered_pool[filtered_pool.apply(lambda x: has_keyword(x, growth_keywords), axis=1)]
        mask_safe = growth_candidates.apply(lambda x: has_keyword(x, safe_keywords), axis=1)
        growth_candidates = growth_candidates[~mask_safe]
        if not growth_candidates.empty:
            best_growth = growth_candidates.iloc[0]
            final_picks.append(best_growth['pure_name'])
            if has_keyword(best_growth, cc_keywords): cc_count += 1

    # [2] 나머지 채우기
    for idx, row in filtered_pool.iterrows():
        if len(final_picks) >= wanted_count: break
        if row['pure_name'] in final_picks: continue
            
        is_cc = has_keyword(row, cc_keywords)
        is_cash = has_keyword(row, cash_keywords)
        is_bond = has_keyword(row, bond_keywords) and not is_cash
        is_reit = has_keyword(row, reit_keywords)
        
        if is_cc and cc_count >= MAX_CC: continue
        if is_cash and cash_count >= MAX_CASH: continue
        if is_bond and bond_count >= MAX_BOND: continue 
        if is_reit and reit_count >= MAX_REIT: continue
            
        final_picks.append(row['pure_name'])
        
        if is_cc: cc_count += 1
        if is_cash: cash_count += 1
        if is_bond: bond_count += 1
        if is_reit: reit_count += 1
        
    # [3] 모자라면 채우기
    if len(final_picks) < wanted_count:
        remain_pool = filtered_pool[~filtered_pool['pure_name'].isin(final_picks)].copy()
        if cc_count >= MAX_CC:
             mask = remain_pool.apply(lambda x: has_keyword(x, cc_keywords), axis=1)
             remain_pool = remain_pool[~mask]
        if cash_count >= MAX_CASH:
             mask = remain_pool.apply(lambda x: has_keyword(x, cash_keywords), axis=1)
             remain_pool = remain_pool[~mask]
        if bond_count >= MAX_BOND:
             mask = remain_pool.apply(lambda x: has_keyword(x, bond_keywords) and not has_keyword(x, cash_keywords), axis=1)
             remain_pool = remain_pool[~mask]
        if reit_count >= MAX_REIT:
             mask = remain_pool.apply(lambda x: has_keyword(x, reit_keywords), axis=1)
             remain_pool = remain_pool[~mask]
             
        if not remain_pool.empty:
            final_picks.extend(remain_pool.head(wanted_count - len(final_picks))['pure_name'].tolist())

    selected_pool = filtered_pool[filtered_pool['pure_name'].isin(final_picks)].copy()

    # -------------------------------------------------------
    # [교정 6] ★ 비중 최적화
    # -------------------------------------------------------
    if selected_pool.empty: return "종목 선정 실패", [], {}

    selected_pool['sort_cat'] = pd.Categorical(selected_pool['pure_name'], categories=final_picks, ordered=True)
    selected_pool = selected_pool.sort_values('sort_cat')

    yields = selected_pool['연배당률'].values
    inv_dist = 1 / (abs(yields - target_yield) + 0.5) 
    weights = (inv_dist / inv_dist.sum()) * 100
    
    if style in ['safe', 'growth']:
        min_threshold = 40.0 if style == 'safe' else 30.0
        if weights[0] < min_threshold:
            weights[0] = min_threshold
            if len(weights) > 1:
                other_sum = weights[1:].sum()
                if other_sum > 0:
                    weights[1:] = (weights[1:] / other_sum) * (100.0 - min_threshold)

    weights = weights.round().astype(int)
    diff = 100 - weights.sum()
    if len(weights) > 0: weights[0] += diff 
    
    pick_weights = dict(zip(selected_pool['pure_name'], weights))
    
    timing_badge = {"mid": "15일 배당", "end": "월말 배당", "mix": "맞춤"}
    prefix = "(날짜 유연) " if filter_stage == "relaxed" and timing != 'mix' else ""
    theme_title = f"{prefix}{timing_badge.get(timing, '맞춤')} 포트폴리오"
        
    return theme_title, final_picks, pick_weights


# -----------------------------------------------------------
# [SECTION 3] 화면 전환 도우미
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
# [SECTION 4] UI 위자드
# -----------------------------------------------------------

@st.dialog("🕵️ AI 포트폴리오 설계", width="small")
def show_wizard():
    
    df = st.session_state.get('shared_df')
    if df is None:
        st.error("데이터 로딩 중입니다. 잠시 후 다시 시도해주세요.")
        return

    if "wiz_step" not in st.session_state: st.session_state.wiz_step = 1
    if "wiz_data" not in st.session_state: st.session_state.wiz_data = {}

    step = st.session_state.wiz_step

    # [STEP 1]
    if step == 1:
        st.subheader("Q1. 어떤 투자를 원하세요?")
        st.button("📈 성장 추구 (주가 상승 + 배당)", use_container_width=True, on_click=go_next_step, args=(2, 'style', 'growth'))
        st.button("💰 현금 흐름 (월 배당금 극대화)", use_container_width=True, on_click=go_next_step, args=(2, 'style', 'flow'))
        st.button("🛡️ 안정성 (원금 방어 최우선)", use_container_width=True, on_click=go_next_step, args=(2, 'style', 'safe'))

    # [STEP 2]
    elif step == 2:
        st.subheader("Q2. 선호하는 배당 날짜는요?")
        st.button("🗓️ 월중 (매월 15일 경)", use_container_width=True, on_click=go_next_step, args=(3, 'timing', 'mid'))
        st.button("🔚 월말/월초 (월급날 전후)", use_container_width=True, on_click=go_next_step, args=(3, 'timing', 'end'))
        st.button("🔄 상관없음 (섞어서 2주마다 받기)", use_container_width=True, on_click=go_next_step, args=(3, 'timing', 'mix'))

    # [STEP 3] - 안내 문구 복구 완료!
    elif step == 3:
        st.subheader("Q3. 구체적인 목표를 정해주세요")
        target = st.slider("💰 목표 연배당률 (%)", 3.0, 20.0, 7.0, 0.5)
        current_style = st.session_state.wiz_data.get('style')
        
        if current_style == 'safe':
            st.info("🛡️ **안정 추구:** 변동성이 낮은 채권 위주로 구성되나, **원금 손실 가능성은 여전히 존재**합니다.")
            if target > 5.0:
                st.warning(
                    "⚠️ **수익률 제한:** 안전 자산 비중이 높아 목표 수익률 달성이 어려울 수 있습니다.\n\n"
                    "💡 **Tip:** 더 높은 배당을 원하시면, 결과를 **[담기]** 한 뒤 리츠나 고배당주를 **직접 추가**해보세요."
                )
        elif current_style == 'growth':
            st.info("📈 **성장 집중:** 당장의 배당금보다 **미래 주가 상승**을 위한 종목(SCHD, 테크 등)이 의무 포함됩니다.")
            if target >= 7.0:
                st.warning(
                    f"⚠️ **배당률 괴리:** 성장주 비중(30%↑) 확보로 인해 **실제 배당률은 목표({target}%)보다 낮을 수 있습니다.**\n\n"
                    "💡 **Tip:** 부족한 현금 흐름은 결과를 **[담기]** 한 뒤, 커버드콜을 소량 **직접 추가**하여 보완할 수 있습니다."
                )
        else: # flow
            st.info("💰 **현금 흐름:** 매월 들어오는 **월 배당금**에 집중합니다.")
            if target >= 8.0:
                st.warning(
                    "⚠️ **리스크 관리:** 포트폴리오 균형을 위해 **고위험군(커버드콜)은 최대 2개**로 자동 제한됩니다.\n\n"
                    "💡 **Tip:** 더 공격적인 투자를 원하시면, 결과를 **[담기]** 한 뒤 메인 화면에서 종목을 **직접 추가**하실 수 있습니다."
                )
            
        count = st.slider("📊 종목 개수", 3, 5, 3)
        if st.button("🚀 결과 확인하기", type="primary", use_container_width=True):
            st.session_state.wiz_data['target_yield'] = target
            st.session_state.wiz_data['count'] = count
            st.session_state.wiz_step = 4
            st.rerun()

    # [STEP 4] 결과
    elif step == 4:
        if "ai_result_cache" not in st.session_state:
            with st.spinner("🎲 최적 조합 찾는 중..."):
                t_res, p_res, w_res = get_smart_recommendation(df, st.session_state.wiz_data)
                st.session_state.ai_result_cache = {"title": t_res, "picks": p_res, "weights": w_res}
        
        cached = st.session_state.ai_result_cache
        title, picks, weights = cached["title"], cached["picks"], cached["weights"]

        if not picks or title == "조건에 맞는 종목 없음":
            st.error("❌ 조건에 맞는 종목을 찾지 못했습니다.")
            st.button("처음으로 돌아가기", use_container_width=True, on_click=reset_wizard)
            return

        st.success(f"**{title}**")
        if "(날짜 유연)" in title: st.caption("💡 조건에 맞는 종목이 부족하여 날짜 범위를 조금 넓혔습니다.")
            
        for stock in picks:
            row_match = df[df['pure_name'] == stock]
            if not row_match.empty:
                row = row_match.iloc[0]
                w = weights.get(stock, 0)
                st.markdown(f"✅ **{stock}** (비중 **{w}%**)")
                st.caption(f"    └ 💰 연 {row['연배당률']:.2f}% | 📅 {row.get('배당락일', '-')}")

        st.write("") 
        st.warning("⚠️ **유의사항:** 본 결과는 시뮬레이션이며 투자 추천이 아닙니다.")

        st.divider()
        
        c1, c2 = st.columns(2)
        
        if c1.button("🎲 다른 조합", use_container_width=True):
            del st.session_state.ai_result_cache
            st.rerun()

        if c2.button("🔄 처음부터", on_click=reset_wizard, use_container_width=True):
            st.rerun()
            
        st.write("") 
        
        if st.button("✅ 이대로 담기", type="primary", use_container_width=True):
            st.session_state.selected_stocks = picks
            st.session_state.ai_suggested_weights = weights
            st.session_state.ai_modal_open = False
            if "ai_result_cache" in st.session_state: del st.session_state.ai_result_cache
            
            u_bk = st.session_state.get("user_info")
            l_bk = st.session_state.get("is_logged_in")
            st.toast("장바구니에 담았습니다! 🛒", icon="✅")
            st.session_state.user_info = u_bk
            st.session_state.is_logged_in = l_bk
            st.rerun()
