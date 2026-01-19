"""
프로젝트: 배당 팽이 (Dividend Top) v2.3
파일명: recommendation.py
설명: AI 로보어드바이저 엔진 (국내/해외 선택 옵션 및 안내 가이드 강화)
"""

import streamlit as st
import pandas as pd
import re
import random
import time
import numpy as np

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

def _get_core_index_name(name):
    managers = ['ACE', 'TIGER', 'KODEX', 'SOL', 'RISE', 'PLUS', 'TIMEFOLIO', 'ARIRANG', 'HANARO', 'KBSTAR']
    core = name.upper()
    for m in managers:
        core = core.replace(m, "")
    return core.replace(" ", "").replace("(H)", "").replace("합성", "").strip()

# -----------------------------------------------------------
# [SECTION 2] 스마트 필터링 & 비중 최적화 엔진
# -----------------------------------------------------------

def get_smart_recommendation(df, user_choices):
    target_yield = user_choices.get('target_yield', 7.0)
    style = user_choices.get('style', 'balance')
    wanted_count = user_choices.get('count', 3)
    timing = user_choices.get('timing', 'mix')
    include_foreign = user_choices.get('include_foreign', True)
    
    # [Q4 수정] 다중 원픽 데이터 추출
    focus_labels = user_choices.get('focus_stock_labels', [])
    total_focus_weight = user_choices.get('focus_weight', 0)
    focus_real_names = []
    
    if focus_labels:
        for lbl in focus_labels:
            match = df[df['검색라벨'] == lbl]
            if not match.empty:
                focus_real_names.append(match.iloc[0]['pure_name'])

    pool = df[df['연배당률'] > 0].copy()
    
    # -----------------------------------------------------
    # [NEW] 국내/해외 필터링 (사장님 통찰 반영)
    # -----------------------------------------------------
    if not include_foreign:
        pool = pool[pool['분류'] == '국내']
        
    pool['temp_date_str'] = pool['배당락일'].fillna('').astype(str)
    
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

    cash_keywords = ['shv', 'bil', 'sgov', 'cd', 'kofr', '파킹', '단기채', '초단기']
    def check_is_cash(row):
        is_bond = (row.get('유형') == '채권')
        text = (str(row['종목명']) + " " + str(row.get('pure_name', ''))).lower()
        return is_bond and any(k in text for k in cash_keywords)

    filtered_pool['yield_diff'] = abs(filtered_pool['연배당률'] - target_yield)
    filtered_pool['score'] = 100 - (filtered_pool['yield_diff'] * 10)
    
    for idx, row in filtered_pool.iterrows():
        cat = row.get('유형', '')
        if style == 'growth':
            if cat == '배당성장': filtered_pool.at[idx, 'score'] += 50 
            elif cat == '고배당주': filtered_pool.at[idx, 'score'] += 20
            elif cat == '채권': filtered_pool.at[idx, 'score'] -= 30
        elif style == 'safe':
            if cat == '채권' or cat == '혼합': filtered_pool.at[idx, 'score'] += 100
            elif cat == '배당성장': filtered_pool.at[idx, 'score'] += 30
        elif style == 'flow':
            filtered_pool.at[idx, 'score'] += (row['연배당률'] * 2)
            if cat == '커버드콜': filtered_pool.at[idx, 'score'] += 15
            elif cat == '고배당주': filtered_pool.at[idx, 'score'] += 20
            elif cat == '리츠': filtered_pool.at[idx, 'score'] += 10

    filtered_pool['random_luck'] = [random.uniform(0, 15) for _ in range(len(filtered_pool))]
    filtered_pool['score'] += filtered_pool['random_luck']
    filtered_pool = filtered_pool.sort_values('score', ascending=False)

    final_picks = []
    picked_core_names = []
    
    # -----------------------------------------------------
    # [NEW] 원픽 종목들(1~2개) 0순위 알박기
    # -----------------------------------------------------
    for name in focus_real_names:
        final_picks.append(name)
        picked_core_names.append(_get_core_index_name(name))

    cc_count = 0
    cash_count = 0 
    bond_count = 0 
    reit_count = 0 
    
    # [기본 쿼터]
    MAX_CC = 2      
    MAX_CASH = 1    
    MAX_BOND = 1    
    MAX_REIT = 1    
    
    # [스타일별 예외 허용]
    if style == 'safe':
        MAX_BOND = wanted_count  # 안정형은 채권 제한 없음
    elif style == 'flow':
        MAX_CC = wanted_count    # 현금흐름형 커버드콜 무제한 (원하는 개수만큼)
        MAX_REIT = wanted_count  # 리츠도 무제한
    elif style == 'growth':
        MAX_REIT = 2             # 성장형은 리츠 2개까지
    
    # (A) 의무 선발 (원픽이 없을 때만 작동하거나, 원픽과 겹치지 않게)
    if style == 'safe':
        safe_candidates = filtered_pool[filtered_pool['유형'] == '채권']
        if not safe_candidates.empty:
            # 상위 후보 중 이미 뽑힌(원픽) 것 제외
            for _, cand in safe_candidates.iterrows():
                if cand['pure_name'] not in final_picks:
                    final_picks.append(cand['pure_name'])
                    picked_core_names.append(_get_core_index_name(cand['pure_name']))
                    if check_is_cash(cand): cash_count += 1
                    else: bond_count += 1
                    break # 1개만 의무
            
        growth_candidates = filtered_pool[filtered_pool['유형'] == '배당성장']
        if growth_candidates.empty:
             growth_candidates = filtered_pool[filtered_pool['유형'].isin(['고배당주', '혼합'])]
             
        growth_candidates = growth_candidates[~growth_candidates['pure_name'].isin(final_picks)]
        
        for _, g_row in growth_candidates.iterrows():
            core = _get_core_index_name(g_row['pure_name'])
            if core not in picked_core_names:
                final_picks.append(g_row['pure_name'])
                picked_core_names.append(core)
                break

    elif style == 'growth':
        growth_candidates = filtered_pool[filtered_pool['유형'] == '배당성장']
        if not growth_candidates.empty:
            for _, cand in growth_candidates.iterrows():
                if cand['pure_name'] not in final_picks:
                    final_picks.append(cand['pure_name'])
                    picked_core_names.append(_get_core_index_name(cand['pure_name']))
                    break

    # (B) 나머지 채우기 (쿼터 적용)
    # 원픽이 이미 final_picks에 들어있으므로, len 체크하며 채움
    total_needed = wanted_count + (1 if focus_real_names else 0) 
    # (만약 원픽이 wanted_count보다 많으면 리스트가 더 길어질 수 있으니 max 처리 등 필요하지만, UI에서 2개 제한했으므로 안전)

    for idx, row in filtered_pool.iterrows():
        if len(final_picks) >= wanted_count: break # 사용자가 원한 개수만큼만 채움
        if row['pure_name'] in final_picks: continue
            
        core_name = _get_core_index_name(row['pure_name'])
        if core_name in picked_core_names: continue
            
        cat = row.get('유형', '')
        is_cc = (cat == '커버드콜')
        is_reit = (cat == '리츠')
        is_cash = check_is_cash(row)
        is_bond = (cat == '채권') and not is_cash
        
        # 쿼터 체크
        if is_cc and cc_count >= MAX_CC: continue
        if is_cash and cash_count >= MAX_CASH: continue
        if is_bond and bond_count >= MAX_BOND: continue 
        if is_reit and reit_count >= MAX_REIT: continue
            
        final_picks.append(row['pure_name'])
        picked_core_names.append(core_name)
        
        if is_cc: cc_count += 1
        if is_cash: cash_count += 1
        if is_bond: bond_count += 1
        if is_reit: reit_count += 1
        
    # (C) [안전장치] 쿼터 때문에 모자라면 제한 풀고 채우기
    if len(final_picks) < wanted_count:
        remain_pool = filtered_pool[~filtered_pool['pure_name'].isin(final_picks)].copy()
        if not remain_pool.empty:
            needed = wanted_count - len(final_picks)
            final_picks.extend(remain_pool.head(needed)['pure_name'].tolist())

    selected_pool = filtered_pool[filtered_pool['pure_name'].isin(final_picks)].copy()

    # 4. 비중 최적화 (Min 10% ~ Max 50%)
    if selected_pool.empty: return "종목 선정 실패", [], {}

    pick_weights = {}
    
    # [비중 계산 로직 분기]
    if focus_real_names:
        # 1. 원픽 종목들에게 설정 비중을 균등하게 배분
        # 예: 총 40%고 원픽이 2개면 -> 각각 20%씩
        weight_per_focus = total_focus_weight // len(focus_real_names)
        for name in focus_real_names:
            pick_weights[name] = weight_per_focus
            
        remaining_quota = 100 - (weight_per_focus * len(focus_real_names))
        
        # 2. 나머지 AI 종목 비중 계산
        ai_picks = [p for p in final_picks if p not in focus_real_names]
        
        if ai_picks:
            ai_pool = selected_pool[selected_pool['pure_name'].isin(ai_picks)].copy()
            if not ai_pool.empty:
                yields = ai_pool['연배당률'].values
                scores = 1 / (abs(yields - target_yield) + 1.0)
                
                # 남은 쿼터 내에서 비율대로 나눔
                w_temp = (scores / scores.sum()) * remaining_quota
                w_temp = w_temp.round().astype(int)
                
                # 잔차 보정
                diff = remaining_quota - w_temp.sum()
                if len(w_temp) > 0:
                    max_idx = w_temp.argmax()
                    w_temp[max_idx] += diff
                
                for name, w in zip(ai_pool['pure_name'], w_temp):
                    pick_weights[name] = w
    else:
        # 기존 로직 (원픽 없음)
        selected_pool['sort_cat'] = pd.Categorical(selected_pool['pure_name'], categories=final_picks, ordered=True)
        selected_pool = selected_pool.sort_values('sort_cat')

        yields = selected_pool['연배당률'].values
        scores = 1 / (abs(yields - target_yield) + 1.0)
        weights = (scores / scores.sum()) * 100
        
        MAX_CAP = 50.0
        MIN_FLOOR = 10.0
        
        for _ in range(3):
            weights = weights.clip(MIN_FLOOR, MAX_CAP)
            weights = (weights / weights.sum()) * 100
        
        weights = weights.round().astype(int)
        diff = 100 - weights.sum()
        max_idx = weights.argmax()
        weights[max_idx] += diff
        
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
    st.session_state.wiz_step = 0 # 0단계부터 시작
    st.session_state.wiz_data = {}
    if "ai_result_cache" in st.session_state:
        del st.session_state.ai_result_cache


# -----------------------------------------------------------
# [SECTION 4] UI 위자드
# -----------------------------------------------------------

@st.dialog("🕵️ AI 포트폴리오 설계", width="small")
def show_wizard():
    df = st.session_state.get('shared_df')
    if df is None or df.empty:
        st.warning("⏳ 데이터 로딩 중입니다. 잠시 후 다시 시도해주세요.")
        return

    if "wiz_step" not in st.session_state: st.session_state.wiz_step = 0
    if "wiz_data" not in st.session_state: st.session_state.wiz_data = {}

    step = st.session_state.wiz_step

    # ------------------------------------------------------------------
    # [Step 0] 가이드 및 국내/해외 선택 (멘트 복구)
    # ------------------------------------------------------------------
    if step == 0:
        st.subheader("나만의 배당 조합, 막막하신가요?")
        st.write("투자 성향과 목표에 맞춰 배당팽이가 최적의 포트폴리오를 설계해 드립니다. ✨")
        
        st.caption("배당 팽이 알고리즘이 70여 개의 종목을 실시간으로 분석합니다.")

        st.markdown("---")
        st.write("🌍 **어떤 종목을 포함할까요?**")
        col_kor, col_all = st.columns(2)
        with col_kor:
            if st.button("🇰🇷 국내 종목만", use_container_width=True):
                go_next_step(1, 'include_foreign', False)
                st.rerun()
        with col_all:
            if st.button("🌎 해외 포함", use_container_width=True):
                go_next_step(1, 'include_foreign', True)
                st.rerun()

    elif step == 1:
        st.subheader("Q1. 어떤 투자를 원하세요?")
        st.button("📈 성장 추구 (주가 상승 + 배당)", use_container_width=True, on_click=go_next_step, args=(2, 'style', 'growth'))
        st.button("💰 현금 흐름 (월 배당금 극대화)", use_container_width=True, on_click=go_next_step, args=(2, 'style', 'flow'))
        st.button("🛡️ 안정성 (원금 방어 최우선)", use_container_width=True, on_click=go_next_step, args=(2, 'style', 'safe'))

    elif step == 2:
        st.subheader("Q2. 선호하는 배당 날짜는요?")
        st.button("🗓️ 월중 (매월 15일 경)", use_container_width=True, on_click=go_next_step, args=(3, 'timing', 'mid'))
        st.button("🔚 월말/월초 (월급날 전후)", use_container_width=True, on_click=go_next_step, args=(3, 'timing', 'end'))
        st.button("🔄 상관없음 (섞어서 2주마다 받기)", use_container_width=True, on_click=go_next_step, args=(3, 'timing', 'mix'))

    elif step == 3:
        st.subheader("Q3. 목표와 규모를 정해주세요")
        target = st.slider("💰 목표 연배당률 (%)", 3.0, 20.0, 7.0, 0.5)
        count = st.slider("📊 구성 종목 개수", 2, 4, 3)
        
        current_style = st.session_state.wiz_data.get('style')
        if current_style == 'safe':
            st.info("🛡️ **안정 추구:** 변동성이 낮은 채권 위주로 구성되나, 원금 손실 가능성은 여전히 존재합니다.")
            if target > 5.0:
                st.warning(f"⚠️ **수익률 제한:** 안전 자산 비중이 높아 목표({target}%) 달성이 어려울 수 있습니다. 더 높은 수익을 원하신다면 아래 **[계산기]**에서 **리츠나 고배당 상품을 직접 추가**하여 보완해 보세요.")
        elif current_style == 'growth':
            st.info("📈 **성장 집중:** 당장의 배당금보다 미래 주가 상승을 위한 종목이 의무 포함됩니다.")
            if target >= 7.0:
                st.warning(f"⚠️ **배당률 괴리:** 성장주 비중으로 인해 실제 배당률이 목표보다 낮을 수 있습니다. 당장의 현금흐름이 더 중요하다면 아래 화면에서 **성장주 일부를 고배당 ETF로 직접 교체**해 보세요.")
        else:
            st.info("💰 **현금 흐름:** 매월 들어오는 월 배당금 극대화에 집중합니다.")
            if target >= 8.0:
                st.warning(f"⚠️ **고배당 집중:** 목표 달성을 위해 리스크가 큰 커버드콜 비중이 높게 설정되었습니다. 특정 종목이 불안하시다면 아래 **[계산기]**에서 **안정적인 배당성장주로 직접 비중을 옮겨** 균형을 맞추실 수 있습니다.")

        if st.button("🚀 다음 단계로 (3/4)", type="primary", use_container_width=True):
            st.session_state.wiz_data['target_yield'] = target
            st.session_state.wiz_data['count'] = count
            st.session_state.wiz_step = 4
            st.rerun()

    elif step == 4:
        wanted_cnt = st.session_state.wiz_data.get('count', 3)
        max_fav = 2 if wanted_cnt == 4 else 1
        st.subheader("🎯 나만의 최애 종목 (선택사항)")
        st.info(f"💡 전체 {wanted_cnt}개 종목 중 최대 **{max_fav}개**까지 직접 지정할 수 있습니다.")
        st.caption("선택하지 않으셔도 AI가 최적의 종목을 알아서 찾아드립니다.")

        # [필터링 적용] 해외 포함 여부에 따라 리스트 필터링
        inc_foreign = st.session_state.wiz_data.get('include_foreign', True)
        if inc_foreign:
            stock_list = sorted(df['검색라벨'].tolist())
        else:
            stock_list = sorted(df[df['분류'] == '국내']['검색라벨'].tolist())

        selected_favs = st.multiselect("최애 종목 선택", options=stock_list, max_selections=max_fav)

        if selected_favs:
            focus_weight = st.slider(f"💰 선택 종목 합계 비중 (%)", 5, 50, 20, step=5)
            st.success(f"✅ 선택하신 종목에 총 **{focus_weight}%**를 고정 배치합니다.")
            st.session_state.wiz_data['focus_stock_labels'] = selected_favs
            st.session_state.wiz_data['focus_weight'] = focus_weight
        else:
            st.session_state.wiz_data['focus_stock_labels'] = []
            st.session_state.wiz_data['focus_weight'] = 0

        c1, c2 = st.columns(2)
        with c1:
            if st.button("⬅️ 이전으로", use_container_width=True):
                st.session_state.wiz_step = 3
                st.rerun()
        with c2:
            if st.button("🚀 결과 보기", type="primary", use_container_width=True):
                st.session_state.wiz_step = 5
                st.rerun()

    elif step == 5:
        if "ai_result_cache" not in st.session_state or st.session_state.ai_result_cache is None:
            with st.spinner("🎲 최적 조합 찾는 중..."):
                t_res, p_res, w_res = get_smart_recommendation(df, st.session_state.wiz_data)
                st.session_state.ai_result_cache = {"title": t_res, "picks": p_res, "weights": w_res}
        
        cached = st.session_state.ai_result_cache
        title = cached.get("title", "결과 없음")
        picks = cached.get("picks", [])
        weights = cached.get("weights", {})

        if not picks or title == "조건에 맞는 종목 없음":
            st.error("❌ 조건에 맞는 종목을 찾지 못했습니다.")
            st.button("처음으로 돌아가기", use_container_width=True, on_click=reset_wizard)
            return

        st.success(f"**{title}**")
        
        # 💡 [핵심 업데이트] 날짜가 유연하게 조정된 경우에만 결과창에서 이유 설명
        if "(날짜 유연)" in title:
            with st.container(border=True):
                st.caption("🔍 **설계 노트**")
                st.caption("설정하신 높은 배당률 목표를 달성하기 위해, 선택하신 배당 시기 외에도 수익성이 뛰어난 종목을 일부 포함하여 최적화했습니다.")
            
        for stock in picks:
            row_match = df[df['pure_name'] == stock]
            if not row_match.empty:
                row = row_match.iloc[0]
                w = weights.get(stock, 0)
                st.markdown(f"✅ **{stock}** (비중 **{w}%**)")
                st.caption(f"    └ 💰 연 {row['연배당률']:.2f}% | 📅 {row.get('배당락일', '-')} | 🔖 {row.get('유형', '-')}")

        st.write("") 
        st.warning("""⚠️ **투자 유의사항**\n1. 본 결과는 과거 데이터를 기반으로 한 단순 시뮬레이션입니다.\n2. 모든 투자의 책임은 투자자 본인에게 있습니다.""")

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
            st.toast("장바구니에 담았습니다! 🛒", icon="✅")
            time.sleep(0.5)
            st.rerun()
