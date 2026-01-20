"""
프로젝트: 배당 팽이 (Dividend Top) v2.9
파일명: recommendation.py
설명: AI 로보어드바이저 엔진 (안정형 리스크 필터링 + 투자 유의사항 + 좀비 팝업 방지 안전 종료 추가)
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
# [SECTION 2] AI 스마트 추천 엔진 (The Brain)
# ===========================================================

def get_smart_recommendation(df, user_choices):
    """사용자 선택값에 따라 가중치와 필터링을 거쳐 최적의 포트폴리오를 제안합니다."""
    target_yield = user_choices.get('target_yield', 7.0)
    style = user_choices.get('style', 'balance')
    wanted_count = user_choices.get('count', 3)
    timing = user_choices.get('timing', 'mix')
    include_foreign = user_choices.get('include_foreign', True)
    
    # 1. 다중 원픽(Focus Stocks) 데이터 파싱
    focus_labels = user_choices.get('focus_stock_labels', [])
    total_focus_weight = user_choices.get('focus_weight', 0)
    focus_real_names = []
    
    if focus_labels:
        for lbl in focus_labels:
            match = df[df['검색라벨'] == lbl]
            if not match.empty: focus_real_names.append(match.iloc[0]['pure_name'])

    # 2. 기초 종목 풀 구성 (국내/해외 필터링 적용)
    pool = df[df['연배당률'] > 0].copy()
    if not include_foreign:
        pool = pool[pool['분류'] == '국내']
    pool['temp_date_str'] = pool['배당락일'].fillna('').astype(str)
    
    # 3. 배당 스타일별 목표 배당률 보정 (안정형인 경우 상한선 제한)
    if style == 'safe':
        pool = pool[pool['연배당률'] <= 10.0]
        target_yield = min(target_yield, 6.0)
    
    # 4. 배당 시기 1차 필터링
    mask_timing = pool['temp_date_str'].apply(lambda x: _check_timing_match(x, timing))
    first_try = pool[mask_timing].copy()
    
    # 필터링 결과가 부족할 경우 전체 데이터로 확장 (Relaxed Stage)
    if not first_try.empty and len(first_try) >= wanted_count:
        filtered_pool = first_try
    else:
        filtered_pool = pool.copy()
        
    if filtered_pool.empty: return "조건에 맞는 종목 없음", [], {}

    # 5. 종목별 점수 산정 (목표 배당률 근접도 + 스타일 가중치)
    filtered_pool['yield_diff'] = abs(filtered_pool['연배당률'] - target_yield)
    filtered_pool['score'] = 100 - (filtered_pool['yield_diff'] * 10)
    
    for idx, row in filtered_pool.iterrows():
        cat = row.get('유형', '')
        name_full = (str(row.get('종목명', '')) + " " + str(row.get('pure_name', ''))).lower()
        
        # [리스크 필터] 하이일드/액티브 리스크 탐지 키워드
        is_risky_bond = any(k in name_full for k in ['하이일드', 'high yield', 'active', '액티브'])

        if style == 'growth':
            if cat == '배당성장': filtered_pool.at[idx, 'score'] += 50 
        
        elif style == 'safe':
            # 안정형일 때 채권/혼합은 우대하되, 리스크 있는 채권은 강력 페널티
            if cat in ['채권', '혼합']: 
                if is_risky_bond:
                    filtered_pool.at[idx, 'score'] -= 150 # 🚨 하이일드 강력 억제 (추천 제외급)
                else:
                    filtered_pool.at[idx, 'score'] += 100 # 국채/우량채 우대
            elif is_risky_bond:
                 filtered_pool.at[idx, 'score'] -= 100

        elif style == 'flow':
            filtered_pool.at[idx, 'score'] += (row['연배당률'] * 2)

    filtered_pool['score'] += [random.uniform(0, 15) for _ in range(len(filtered_pool))]
    filtered_pool = filtered_pool.sort_values('score', ascending=False)

    # 6. 최종 종목 선정 (원픽 우선 + AI 추천 보완)
    final_picks = []
    picked_core_names = []
    
    for name in focus_real_names: # 원픽 알박기
        final_picks.append(name)
        picked_core_names.append(_get_core_index_name(name))

    for idx, row in filtered_pool.iterrows(): # 나머지 칸 채우기
        if len(final_picks) >= wanted_count: break
        if row['pure_name'] in final_picks: continue
        core_name = _get_core_index_name(row['pure_name'])
        if core_name in picked_core_names: continue 
        final_picks.append(row['pure_name'])
        picked_core_names.append(core_name)
    
    final_picks = list(dict.fromkeys(final_picks))
    selected_pool = filtered_pool[filtered_pool['pure_name'].isin(final_picks)].copy()

    # 7. 비중(Weight) 최적화
    pick_weights = {}
    if focus_real_names:
        w_per_focus = total_focus_weight // len(focus_real_names)
        for name in focus_real_names: pick_weights[name] = w_per_focus
        
        remaining_quota = 100 - (w_per_focus * len(focus_real_names))
        ai_picks = [p for p in final_picks if p not in focus_real_names]
        
        if ai_picks: 
            ai_pool = selected_pool[selected_pool['pure_name'].isin(ai_picks)].copy()
            if not ai_pool.empty:
                scores = 1 / (abs(ai_pool['연배당률'].values - target_yield) + 1.0)
                w_temp = ((scores / scores.sum()) * remaining_quota).round().astype(int)
                diff = remaining_quota - w_temp.sum()
                if len(w_temp) > 0: w_temp[w_temp.argmax()] += diff
                for name, w in zip(ai_pool['pure_name'], w_temp): pick_weights[name] = w
        else: 
            if focus_real_names: pick_weights[focus_real_names[-1]] += remaining_quota
    else:
        yields = selected_pool['연배당률'].values
        scores = 1 / (abs(yields - target_yield) + 1.0)
        weights = ((scores / scores.sum()) * 100).round().astype(int)
        weights[weights.argmax()] += (100 - weights.sum())
        pick_weights = dict(zip(selected_pool['pure_name'], weights))
    
    # 8. 실제 결과물(final_picks) 기반 날짜 유연성 검증
    is_timing_compromised = False
    if timing != 'mix':
        for pick in final_picks:
            row_match = df[df['pure_name'] == pick]
            if not row_match.empty:
                d_str = str(row_match.iloc[0].get('배당락일', ''))
                if not _check_timing_match(d_str, timing):
                    is_timing_compromised = True
                    break

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

    # [Step 0] 도입부 및 국가 필터 선택
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
        
        # 🚨 [안전 장치] 시작 화면에서 나가기 버튼 (좀비 팝업 방지)
        st.write("")
        if st.button("닫기", use_container_width=True):
            st.session_state.ai_modal_open = False
            st.rerun()

    # [Step 1] 투자 스타일 결정
    elif step == 1:
        st.subheader("Q1. 어떤 투자를 원하세요?")
        st.button("📈 성장 추구 (주가 상승 + 배당)", use_container_width=True, on_click=go_next_step, args=(2, 'style', 'growth'))
        st.button("💰 현금 흐름 (월 배당금 극대화)", use_container_width=True, on_click=go_next_step, args=(2, 'style', 'flow'))
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
        
        # [NEW] 스타일별 맞춤형 조언 및 경고
        if current_style == 'safe':
            st.info("🛡️ **안정 추구:** 변동성이 낮은 국채/우량채 위주로 구성합니다.")
            st.warning("⚠️ **주의:** 채권형 ETF라도 금리 변동에 따라 원금 손실 가능성은 존재합니다.")
            if target > 5.0:
                st.caption("💡 안정형에서 5% 이상 수익을 내려면 리츠나 혼합형 상품이 일부 포함될 수 있습니다.")
                
        elif current_style == 'growth':
            st.info("📈 **성장 집중:** 당장의 배당금보다 미래 주가 상승(S&P500, 나스닥 등)을 위한 종목이 포함됩니다.")
            if target >= 7.0:
                st.warning("⚠️ **주의:** 성장주 위주로는 고배당(7%+) 달성이 어렵습니다. 실제 결과가 목표보다 낮을 수 있습니다.")
                
        else: # flow (현금흐름)
            st.info("💰 **현금 흐름:** 커버드콜 등 월 배당금이 많이 나오는 종목에 집중합니다.")
            if target >= 9.0:
                st.warning("⚠️ **고위험 경고:** 목표 배당률이 매우 높습니다. 원금 하락 위험이 있는 고배당 커버드콜 비중이 높아질 수 있습니다.")

        if st.button("🚀 다음 단계로 (3/4)", type="primary", use_container_width=True):
            st.session_state.wiz_data['target_yield'] = target
            st.session_state.wiz_data['count'] = count
            st.session_state.wiz_step = 4; st.rerun()

    # [Step 4] 나만의 원픽(Focus) 종목 선택
    elif step == 4:
        wanted_cnt = st.session_state.wiz_data.get('count', 3)
        max_fav = 2 if wanted_cnt == 4 else 1 # 4종목 선택 시에만 2개 허용
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

    # [Step 5] 최종 결과 출력 및 카톡 공유
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
        
        # 블로그 최신글 연동
        blog_title, blog_url = _get_latest_blog_info()
        
        # [표현 수정] 중립적인 표현 사용
        share_text = f"🐌 [AI 분석 포트폴리오]\n\n📌 컨셉: {title}\n"
        total_avg_yld = 0

        for stock in picks:
            row = df[df['pure_name'] == stock].iloc[0]
            w = weights.get(stock, 0)
            total_avg_yld += (row['연배당률'] * w / 100)
            st.markdown(f"✅ **{stock}** (비중 **{w}%**)")
            st.caption(f"    └ 💰 연 {row['연배당률']:.2f}% | 📅 {row.get('배당락일', '-')} | 🔖 {row.get('유형', '-')}")
            share_text += f"- {stock}: {w}% (연 {row['연배당률']:.2f}%)\n"

        share_text += f"\n📈 예상 평균 배당률: 연 {total_avg_yld:.2f}%\n"
        share_text += f"\n📖 추천 분석글: {blog_title}\n🔗 {blog_url}"
        share_text += f"\n📍 출처: 배당팽이"

        with st.expander("📲 친구에게 공유하거나 카톡에 저장하기", expanded=False):
            st.code(share_text, language="text")
            st.info("💡 우측 상단 복사 아이콘을 눌러 카톡에 붙여넣으세요!")

        st.write("")
        st.warning("""⚠️ **투자 유의사항 (필독)**

1. 본 결과는 매수/매도 추천이 아니며, 과거 데이터를 기반으로 한 단순 시뮬레이션입니다.

2. 배당률 및 지급일정은 시장 상황과 운용사 정책에 따라 언제든 변동될 수 있습니다.

3. 과거의 수익이 미래의 수익을 보장하지 않으므로, 모든 투자의 책임은 본인에게 있습니다.""")
        
        st.info("💡 **팁:** AI 제안 결과는 단순 참고용입니다. [가져오기]를 누르신 후, 아래 [💰 배당금 계산기]에서 종목이나 비중을 자유롭게 수정하실 수 있습니다.")

        st.divider()
        c1, c2 = st.columns(2)
        if c1.button("🎲 다른 조합", use_container_width=True): del st.session_state.ai_result_cache; st.rerun()
        if c2.button("🔄 처음부터", on_click=reset_wizard, use_container_width=True): st.rerun()
        
        # 💡 [핵심] 스위치 끄기 로직 (회로 차단) & Toss 스타일 문구
        if st.button("✅ 내 포트폴리오로 가져오기", type="primary", use_container_width=True):
            st.session_state.selected_stocks = picks
            st.session_state.ai_suggested_weights = weights
            st.session_state.ai_modal_open = False # 스위치 OFF (팝업 닫힘)
            if "ai_result_cache" in st.session_state: del st.session_state.ai_result_cache
            st.toast("장바구니에 담았습니다! 🛒", icon="✅")
            time.sleep(0.5)
            st.rerun()
            
        # 🚨 [안전 장치] 결과 화면에서 그냥 닫고 싶을 때 (좀비 팝업 방지)
        st.write("")
        if st.button("닫기 (저장 안 함)", use_container_width=True):
            st.session_state.ai_modal_open = False
            if "ai_result_cache" in st.session_state: del st.session_state.ai_result_cache
            st.rerun()
