"""
프로젝트: 배당 팽이 (Dividend Top) v2.9
파일명: recommendation.py
설명: AI 로보어드바이저 엔진 (최종 완성: 쿼터제 + 황금비율 + 셔플 + 데이터 무결성 + 심플 결과창 + 안정형 리스크 방어)
업데이트: 2026.01.20
"""

import streamlit as st
import pandas as pd
import re
import random
import time
import numpy as np
import requests
import xml.etree.ElementTree as ET

# ===========================================================
# [SECTION 1] 데이터 처리 및 외부 연동 헬퍼 함수
# ===========================================================

@st.cache_data(ttl=3600)
def _get_latest_blog_info():
    """네이버 RSS 피드에서 최신 분석글의 제목과 링크를 수집합니다."""
    try:
        rss_url = "https://rss.blog.naver.com/dividenpange.xml"
        response = requests.get(rss_url, timeout=5)
        root = ET.fromstring(response.content)
        item = root.find(".//item")
        if item is not None:
            title = item.find("title").text
            link = item.find("link").text
            return title, link
    except Exception:
        pass
    return "배당팽이 투자 일지", "https://blog.naver.com/dividenpange"

def _parse_day_category(date_str):
    """배당락일 문자열을 분석하여 초/중/말 카테고리로 분류합니다."""
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
    """사용자가 선호하는 배당 시기와 종목의 일정을 비교합니다."""
    if user_timing == 'mix': return True
    cat = _parse_day_category(row_date)
    if user_timing == 'mid': return cat == 'mid'
    elif user_timing == 'end': return cat in ['end', 'early']
    return True

def _get_core_index_name(name):
    """운용사 브랜드를 제외한 순수 지수 명칭만 추출합니다 (중복 추천 방지용)."""
    managers = ['ACE', 'TIGER', 'KODEX', 'SOL', 'RISE', 'PLUS', 'TIMEFOLIO', 'ARIRANG', 'HANARO', 'KBSTAR']
    core = name.upper()
    for m in managers:
        core = core.replace(m, "")
    return core.replace(" ", "").replace("(H)", "").replace("합성", "").strip()


# ===========================================================
# [SECTION 2] AI 스마트 추천 엔진 (The Toss Style + Safety Lock)
# ===========================================================

def get_smart_recommendation(df, user_choices):
    """
    토스(Toss) 스타일 추천 엔진 (최종 완성형):
    1. Safety Lock: 사용자가 비현실적인 배당률(20% 등)을 요구해도 내부적으로 상한선을 적용해 알고리즘 고장을 방지.
    2. Toss Logic: 성장형=SCHD 필수, 현금흐름형=커버드콜+리츠 믹스, 황금 비율(5:3:2) 적용.
    """
    target_yield = user_choices.get('target_yield', 7.0)
    style = user_choices.get('style', 'balance')
    wanted_count = user_choices.get('count', 3)
    timing = user_choices.get('timing', 'mix')
    include_foreign = user_choices.get('include_foreign', True)
    
# -----------------------------------------------------------
    # [Safety Lock] 사용자 욕심 억제기 (현실적 상한선 적용)
    # -----------------------------------------------------------
    calc_target = target_yield  # 기본은 사용자 입력값

    if style == 'safe':
        # [안정형]: 6% 넘어가면 위험자산. SCHD/리츠/국채 위주로 유도.
        calc_target = min(target_yield, 6.0) 
        
    elif style == 'growth':
        # [성장형]: 배당성장주는 보통 2~4%대. 5% 넘게 잡으면 SCHD가 탈락하므로 제한.
        calc_target = min(target_yield, 5.0)

    elif style == 'flow':
        # [현금흐름형]: 🔥 봉인 해제! 
        # 커버드콜(12~20%)을 원하는 사용자를 위해 20%까지 허용합니다.
        # 단, 데이터 오류(100% 등) 방지를 위해 35% 이상은 유니버스 필터링에서 이미 걸러집니다.
        calc_target = min(target_yield, 20.0) 
    # -----------------------------------------------------------
    
    # 1. 기초 데이터 준비 (원픽 처리)
    focus_labels = user_choices.get('focus_stock_labels', [])
    total_focus_weight = user_choices.get('focus_weight', 0)
    focus_real_names = []
    
    if focus_labels:
        for lbl in focus_labels:
            match = df[df['검색라벨'] == lbl]
            if not match.empty: focus_real_names.append(match.iloc[0]['pure_name'])

    # 2. 유니버스 필터링 (데이터 클렌징)
    df['연배당률'] = pd.to_numeric(df['연배당률'], errors='coerce')
    pool = df.dropna(subset=['연배당률'])
    pool = pool[(pool['연배당률'] > 0) & (pool['연배당률'] <= 35.0)].copy() # 0~35% 정상 범위만
    
    if not include_foreign:
        pool = pool[pool['분류'] == '국내']
        
    pool['temp_date_str'] = pool['배당락일'].fillna('').astype(str)

    # 3. 점수 산정 (기본 점수 + 랜덤성)
    # [중요] 사용자가 입력한 target_yield가 아니라, 보정된 calc_target을 사용!
    pool['yield_diff'] = abs(pool['연배당률'] - calc_target)
    pool['score'] = 100 - (pool['yield_diff'] * 15) # 감점 폭 확대 (엄격하게)
    
    # [날짜 가산점]
    if timing != 'mix':
        is_timing_match = pool['temp_date_str'].apply(lambda x: _check_timing_match(x, timing))
        pool.loc[is_timing_match, 'score'] += 40
    
    # [셔플] 약간의 랜덤성 (매번 똑같으면 재미없으니까)
    pool['score'] += [random.uniform(0, 5) for _ in range(len(pool))]
    
    # 4. 자산군(Cluster) 분류
    def get_cluster(row):
        asset_type = str(row.get('자산유형', ''))
        if '채권' in asset_type: return 'bond'
        if '리츠' in asset_type: return 'reit'
        if '커버드콜' in asset_type: return 'cov'
        if '배당성장' in asset_type or '주식' in asset_type: return 'growth'
        if '고배당' in asset_type: return 'income'
        return 'etc'

    pool['cluster'] = pool.apply(get_cluster, axis=1)

    # 5. 스타일별 [필수 쿼터] 및 [가산점 전략]
    quotas = []
    forced_schd = False # 성장형일 때 SCHD 강제 포함 플래그
    
    if style == 'safe':
        # [안정형]: "잃지 않는 게 중요해" -> 채권 필수, 리츠 필수
        pool = pool[pool['연배당률'] <= 12.0] # 위험한 건 아예 안 보여줌
        quotas = ['bond', 'reit'] 
        
        pool.loc[pool['cluster'] == 'bond', 'score'] += 50 # 채권 점수 떡상
        pool.loc[pool['cluster'] == 'reit', 'score'] += 30
        
        # 위험한 하이일드 채권은 감점 (안정형이니까)
        for idx, row in pool.iterrows():
            if '하이일드' in str(row['pure_name']): pool.at[idx, 'score'] -= 50

    elif style == 'growth':
        # [성장형]: "SCHD 없으면 섭섭하지" -> SCHD 강제 소환 + 채권 배제
        forced_schd = True
        quotas = ['growth'] # 나머지는 성장주로 채움
        pool.loc[pool['cluster'] == 'growth', 'score'] += 50
        pool.loc[pool['cluster'] == 'bond', 'score'] -= 100 # 성장형에 채권은 노노

    elif style == 'flow':
        # [현금흐름형]: "월세 받는 건물주 느낌" -> 커버드콜(고수익) + 리츠(월세) 조합
        # 커버드콜만 3개 나오면 위험해보임. 리츠를 강제로 섞음.
        quotas = ['cov', 'reit'] 
        
        pool.loc[pool['cluster'] == 'cov', 'score'] += 50   # 커버드콜은 여전히 대장
        pool.loc[pool['cluster'] == 'reit', 'score'] += 40  # 리츠 점수를 대폭 상향 (커버드콜과 경쟁 가능하게)
        pool.loc[pool['cluster'] == 'income', 'score'] += 20 # 일반 고배당주도 가산점

    # 6. 종목 선발 (Selection Logic)
    final_picks = []
    picked_names = set(focus_real_names)
    
    # [중복 방지 로직] 브랜드만 다르고 지수가 같은 상품(예: SOL 미국배당 vs TIGER 미국배당) 걸러내기
    picked_core_indices = [_get_core_index_name(n) for n in focus_real_names]
    
    # (1) 사용자 원픽 먼저 담기
    final_picks.extend(focus_real_names)
    
    # (2) [토스 스타일] 성장형이면 '배당다우존스(SCHD)' 시리즈 중 하나 무조건 1순위 픽
    if forced_schd:
        # 이미 원픽에 SCHD가 있으면 패스, 없으면 추가
        if not any("배당다우존스" in core for core in picked_core_indices):
            schd_candidates = pool[pool['pure_name'].str.contains("배당다우존스")].sort_values('score', ascending=False)
            if not schd_candidates.empty:
                # 상위 2개 중 랜덤 1개 (TIGER냐 SOL이냐 ACE냐)
                best_schd = schd_candidates.head(2).sample(1).iloc[0]
                final_picks.append(best_schd['pure_name'])
                picked_names.add(best_schd['pure_name'])
                picked_core_indices.append(_get_core_index_name(best_schd['pure_name']))

    # (3) 쿼터(필수 자산군) 채우기
    for q_type in quotas:
        if len(final_picks) >= wanted_count: break
        
        # 해당 클러스터에서 점수 높은 순 + 중복 지수 제외
        candidates = pool[
            (pool['cluster'] == q_type) & 
            (~pool['pure_name'].isin(picked_names))
        ].sort_values('score', ascending=False)
        
        # 상위 5개 중 랜덤 (다양성)
        top_candidates = candidates.head(5)
        if not top_candidates.empty:
            shuffled = top_candidates.sample(frac=1)
            for _, row in shuffled.iterrows():
                core = _get_core_index_name(row['pure_name'])
                if core not in picked_core_indices: # 지수 중복 체크
                    final_picks.append(row['pure_name'])
                    picked_names.add(row['pure_name'])
                    picked_core_indices.append(core)
                    break 

    # (4) 남은 자리 채우기 (점수순)
    while len(final_picks) < wanted_count:
        candidates = pool[~pool['pure_name'].isin(picked_names)].sort_values('score', ascending=False)
        if candidates.empty: break
        
        top_n = candidates.head(5)
        shuffled = top_n.sample(frac=1)
        
        found = False
        for _, row in shuffled.iterrows():
            core = _get_core_index_name(row['pure_name'])
            if core not in picked_core_indices:
                final_picks.append(row['pure_name'])
                picked_names.add(row['pure_name'])
                picked_core_indices.append(core)
                found = True
                break
        if not found: break # 더 이상 뽑을 게 없으면 중단

    # 7. 비중(Weight) 최적화 (황금 비율 적용)
    # 토스라면 1/n 안함. 대장주에 몰아줌.
    selected_pool = pool[pool['pure_name'].isin(final_picks)].copy()
    pick_weights = {}
    
    # 우선순위 정렬 (SCHD > 필수쿼터 > 나머지)
    ranked_picks = []
    for p in final_picks:
        priority = 0
        
        # 스타일별 대장주 우선순위 (황금 비율의 주인공 찾기)
        if "배당다우존스" in p and style == 'growth': priority = 10 # 성장형 대장
        elif style == 'safe' and "채권" in p: priority = 8       # 안정형 대장
        elif style == 'flow' and "커버드콜" in p: priority = 8   # 현금흐름형 대장
        else: priority = selected_pool[selected_pool['pure_name']==p]['score'].iloc[0] / 20 
        
        if p in focus_real_names: priority += 100 # 사용자 픽은 무조건 최우선
        
        ranked_picks.append((p, priority))
    
    # 우선순위 높은 순서대로 정렬
    ranked_picks.sort(key=lambda x: x[1], reverse=True)
    ordered_names = [x[0] for x in ranked_picks]
    
    # 비율 할당 (원픽이 있으면 원픽 비중 제외하고 나머지 배분)
    if focus_real_names:
        w_focus = total_focus_weight // len(focus_real_names)
        for n in focus_real_names: pick_weights[n] = w_focus
        rem_quota = 100 - (w_focus * len(focus_real_names))
        
        ai_picks = [p for p in final_picks if p not in focus_real_names]
        if ai_picks:
            # 1등 몰아주기 로직 (잔여 비중의 60%를 1등에게)
            ai_picks_sorted = [n for n in ordered_names if n in ai_picks]
            
            if len(ai_picks) == 1: w_dist = [rem_quota]
            elif len(ai_picks) == 2: w_dist = [int(rem_quota*0.6), rem_quota - int(rem_quota*0.6)]
            else: w_dist = [rem_quota // len(ai_picks)] * len(ai_picks) # 3개 이상은 균등
            
            for i, name in enumerate(ai_picks_sorted):
                if i < len(w_dist): pick_weights[name] = w_dist[i]
                else: pick_weights[name] = 0
    else:
        # 순수 AI 추천 시 황금 비율 (5:3:2)
        if len(ordered_names) == 1: ratios = [100]
        elif len(ordered_names) == 2: ratios = [60, 40]
        elif len(ordered_names) == 3: ratios = [50, 30, 20] # 이게 제일 예쁨
        elif len(ordered_names) == 4: ratios = [40, 30, 20, 10]
        else: ratios = [100]
        
        for i, name in enumerate(ordered_names):
            if i < len(ratios): pick_weights[name] = ratios[i]
            else: pick_weights[name] = 0

    # 8. 타이틀 생성
    is_timing_compromised = False
    if timing != 'mix':
        for pick in final_picks:
            d_str = selected_pool[selected_pool['pure_name'] == pick]['temp_date_str'].iloc[0]
            if not _check_timing_match(d_str, timing):
                is_timing_compromised = True; break

    timing_badge = {"mid": "15일 배당", "end": "월말 배당", "mix": "맞춤"}
    prefix = "(날짜 유연) " if is_timing_compromised else ""
    theme_title = f"{prefix}{timing_badge.get(timing, '맞춤')} 포트폴리오"
        
    return theme_title, final_picks, pick_weights    


# ===========================================================
# [SECTION 3] 위저드 상태 제어 및 흐름 도우미
# ===========================================================

def go_next_step(next_step_num, key=None, value=None):
    st.session_state.wiz_step = next_step_num
    if key is not None:
        st.session_state.wiz_data[key] = value

def reset_wizard():
    st.session_state.wiz_step = 0
    st.session_state.wiz_data = {}
    if "ai_result_cache" in st.session_state:
        del st.session_state.ai_result_cache


# ===========================================================
# [SECTION 4] AI 로보어드바이저 UI 위저드
# ===========================================================

@st.dialog("🕵️ AI 포트폴리오 설계", width="small")
def show_wizard():
    df = st.session_state.get('shared_df')
    if df is None or df.empty:
        st.warning("⏳ 데이터 로딩 중입니다. 잠시 후 다시 시도해주세요.")
        return

    if "wiz_step" not in st.session_state: st.session_state.wiz_step = 0
    if "wiz_data" not in st.session_state: st.session_state.wiz_data = {}
    step = st.session_state.wiz_step

    # [Step 0] 도입부 (닫기 버튼 삭제됨)
    if step == 0:
        st.subheader("나만의 배당 조합, 막막하신가요?")
        st.write("투자 성향과 목표에 맞춰 배당팽이가 최적의 포트폴리오를 설계해 드립니다. ✨")
        st.caption("AI 알고리즘이 30여 개의 종목을 실시간으로 분석합니다.")
        st.markdown("---")
        st.write("🌍 **어떤 종목을 포함할까요?**")
        col_kor, col_all = st.columns(2)
        with col_kor:
            if st.button("🇰🇷 국내 종목만", use_container_width=True): go_next_step(1, 'include_foreign', False); st.rerun()
        with col_all:
            if st.button("🌎 해외 포함", use_container_width=True): go_next_step(1, 'include_foreign', True); st.rerun()

    # [Step 1] 투자 스타일 결정
    elif step == 1:
        st.subheader("Q1. 어떤 투자를 원하세요?")
        
        st.button("📈 성장 추구 (주가 상승 + 배당)", use_container_width=True, on_click=go_next_step, args=(2, 'style', 'growth'))
        st.write("") 
        
        st.button("💰 현금 흐름 (월 배당금 극대화)", use_container_width=True, on_click=go_next_step, args=(2, 'style', 'flow'))
        st.write("") 
        
        st.button("🛡️ 안정성 (원금 방어 최우선)", use_container_width=True, on_click=go_next_step, args=(2, 'style', 'safe'))

    # [Step 2] 배당 주기 결정
    elif step == 2:
        st.subheader("Q2. 선호하는 배당 날짜는요?")
        st.button("🗓️ 월중 (매월 15일 경)", use_container_width=True, on_click=go_next_step, args=(3, 'timing', 'mid'))
        st.button("🔚 월말/월초 (월급날 전후)", use_container_width=True, on_click=go_next_step, args=(3, 'timing', 'end'))
        st.button("🔄 상관없음 (섞어서 2주마다 받기)", use_container_width=True, on_click=go_next_step, args=(3, 'timing', 'mix'))

    # [Step 3] 목표 수치 및 종목 개수 설정
    elif step == 3:
        st.subheader("Q3. 목표와 규모를 정해주세요")
        target = st.slider("💰 목표 연배당률 (%)", 3.0, 20.0, 7.0, 0.5)
        count = st.slider("📊 구성 종목 개수", 2, 4, 3)
        
        current_style = st.session_state.wiz_data.get('style')
        
        if current_style == 'safe':
            st.info("🛡️ **안정 추구:** 국채 등 안전자산 비중을 **50% 이상** 높여 리스크를 최소화합니다.")
            if target > 5.0:
                st.caption("💡 **참고:** 안정형에서 5% 이상 수익을 내기 위해 리츠나 고배당주가 일부 포함될 수 있습니다.")
                
        elif current_style == 'growth':
            st.info("📈 **성장 집중:** 미래 가치가 높은 배당성장주 위주로 구성됩니다.")
            if target >= 7.0:
                st.warning("⚠️ **현실적 조언:** 성장주 위주로는 고배당(7%+) 달성이 어렵습니다. 실제 결과 배당률은 목표보다 낮을 수 있습니다.")
                
        else: # flow
            st.info("💰 **현금 흐름:** 커버드콜과 안전자산(채권)을 적절히 섞어 **수익과 안정성**을 동시에 추구합니다.")
            if target >= 9.0:
                st.warning("⚠️ **고위험 경고:** 목표 수익률이 매우 높습니다. 원금 변동성이 큰 고배당 종목 비중이 높아질 수 있습니다.")

        if st.button("🚀 다음 단계로 (3/4)", type="primary", use_container_width=True):
            st.session_state.wiz_data['target_yield'] = target
            st.session_state.wiz_data['count'] = count
            st.session_state.wiz_step = 4; st.rerun()

    # [Step 4] 나만의 원픽(Focus) 종목 선택
    elif step == 4:
        wanted_cnt = st.session_state.wiz_data.get('count', 3)
        max_fav = 2 if wanted_cnt == 4 else 1 
        st.subheader("🎯 나만의 최애 종목 (선택사항)")
        st.info(f"💡 전체 {wanted_cnt}개 종목 중 최대 **{max_fav}개**까지 직접 지정할 수 있습니다.")
        
        inc_foreign = st.session_state.wiz_data.get('include_foreign', True)
        stock_list = sorted(df['검색라벨'].tolist()) if inc_foreign else sorted(df[df['분류'] == '국내']['검색라벨'].tolist())

        selected_favs = st.multiselect("최애 종목 선택", options=stock_list, max_selections=max_fav)

        if selected_favs:
            focus_weight = st.slider(f"💰 선택 종목 합계 비중 (%)", 5, 50, 20, step=5)
            st.success(f"✅ 선택하신 종목에 총 {focus_weight}%를 고정 배치합니다.")
            st.session_state.wiz_data['focus_stock_labels'] = selected_favs
            st.session_state.wiz_data['focus_weight'] = focus_weight
        else:
            st.session_state.wiz_data['focus_stock_labels'] = []; st.session_state.wiz_data['focus_weight'] = 0
        
        c1, c2 = st.columns(2)
        if c1.button("⬅️ 이전으로", use_container_width=True): st.session_state.wiz_step = 3; st.rerun()
        if c2.button("🚀 결과 보기", type="primary", use_container_width=True): st.session_state.wiz_step = 5; st.rerun()

    # [Step 5] 최종 결과 출력 (심플 UI)
    elif step == 5:
        if "ai_result_cache" not in st.session_state or st.session_state.ai_result_cache is None:
            with st.spinner("🎲 최적 조합 찾는 중..."):
                t_res, p_res, w_res = get_smart_recommendation(df, st.session_state.wiz_data)
                st.session_state.ai_result_cache = {"title": t_res, "picks": p_res, "weights": w_res}
        
        cached = st.session_state.ai_result_cache
        title, picks, weights = cached.get("title"), cached.get("picks"), cached.get("weights")

        if not picks or title == "조건에 맞는 종목 없음":
            st.error("❌ 종목을 찾지 못했습니다."); st.button("처음으로", on_click=reset_wizard); return

        st.success(f"**{title}**")
        
        if "(날짜 유연)" in title:
            with st.container(border=True):
                st.caption("🔍 **설계 노트**")
                st.caption("목표 달성을 위해, 선택하신 배당 시기 외에도 수익성이 좋은 종목을 일부 포함하여 최적화했습니다.")
        
        blog_title, blog_url = _get_latest_blog_info()
        
        share_text = f"🐌 [AI 분석 포트폴리오]\n\n📌 컨셉: {title}\n"
        total_avg_yld = 0

        for stock in picks:
            row = df[df['pure_name'] == stock].iloc[0]
            w = weights.get(stock, 0)
            total_avg_yld += (row['연배당률'] * w / 100)
            
            # 신규 상장 태그
            months = int(row.get('신규상장개월수', 0))
            new_tag = " | 🌱 신규 상장" if 0 < months < 12 else ""
            
            st.markdown(f"✅ **{stock}** (비중 **{w}%**)")
            st.caption(f"    └ 💰 연 {row['연배당률']:.2f}% | 📅 {row.get('배당락일', '-')} | 🔖 {row.get('유형', '-')}{new_tag}")
            share_text += f"- {stock}: {w}% (연 {row['연배당률']:.2f}%)\n"

        share_text += f"\n📈 예상 평균 배당률: 연 {total_avg_yld:.2f}%\n"
        share_text += f"\n📖 추천 분석글: {blog_title}\n🔗 {blog_url}"
        share_text += f"\n📍 출처: 배당팽이"

        with st.expander("📲 친구에게 공유하거나 카톡에 저장하기", expanded=False):
            st.code(share_text, language="text")
            st.info("💡 우측 상단 복사 아이콘을 눌러 카톡에 붙여넣으세요!")

        st.write("")
        
        # 💡 [핵심] 면책 조항 삭제 후 심플한 팁만 남김
        st.info("💡 **팁:** AI 제안 결과는 시뮬레이션용 단순 참고 자료입니다. [가져오기] 후 자유롭게 수정하여 최종 결정하세요.")

        st.divider()
        c1, c2 = st.columns(2)
        if c1.button("🎲 다른 조합", use_container_width=True): 
            del st.session_state.ai_result_cache
            st.rerun()
            
        if c2.button("🔄 처음부터", on_click=reset_wizard, use_container_width=True): st.rerun()
        
        # 💡 [핵심] 스위치 끄기 로직 (회로 차단) & Toss 스타일 문구
        if st.button("✅ 내 포트폴리오로 가져오기", type="primary", use_container_width=True):
            st.session_state.selected_stocks = picks
            st.session_state.ai_suggested_weights = weights
            st.session_state.ai_modal_open = False 
            if "ai_result_cache" in st.session_state: del st.session_state.ai_result_cache
            st.toast("장바구니에 담았습니다! 🛒", icon="✅")
            time.sleep(0.5)
            st.rerun()
            
        st.write("")
        if st.button("닫기 (저장 안 함)", use_container_width=True):
            st.session_state.ai_modal_open = False
            if "ai_result_cache" in st.session_state: del st.session_state.ai_result_cache
            st.rerun()
