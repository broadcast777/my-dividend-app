import streamlit as st
import time
import random
import pandas as pd

# -----------------------------------------------------------
# [SECTION 1] 스마트 필터링 & 비중 최적화 엔진
# -----------------------------------------------------------
def get_smart_recommendation(df, user_choices):
    """
    사용자 입력(목표 배당률, 스타일, 시기 등)을 분석하여 최적의 종목 조합과 비중을 산출합니다.
    
    Args:
        df (pd.DataFrame): 전체 종목 데이터베이스
        user_choices (dict): 연령, 투자스타일, 배당시기, 목표수익률 등 사용자 설정값
        
    Returns:
        tuple: (포트폴리오 제목, 선정 종목 리스트, 종목별 비중 딕셔너리)
    """
    
    # 1. 사용자 입력 추출
    target_yield = user_choices.get('target_yield', 7.0)
    style = user_choices.get('style', 'balance')
    wanted_count = user_choices.get('count', 3)
    timing = user_choices.get('timing', 'mix')
    age = user_choices.get('age', '4050')
    
    # 2. 데이터 기초 필터링 (배당률 정보가 존재하는 종목만 대상)
    pool = df[df['연배당률'] > 0].copy()

    # -------------------------------------------------------
    # [교정 1] ★ 스타일별 제한 및 배당 시기 엄격 필터 (Hard Filter) ★
    # -------------------------------------------------------
    
    # (A) 안정형 투자 스타일: 6% 상한선 강제 적용 및 목표 배당률 하향 조정
    if style == 'safe':
        pool = pool[pool['연배당률'] <= 6.0]
        target_yield = min(target_yield, 6.0)

    # (B) 배당 시기 필터링: 사용자 선호 시기(중순/말일)에 맞지 않는 종목은 풀에서 즉시 제거
    if '배당락일' in pool.columns:
        pool['배당락일'] = pool['배당락일'].fillna('').astype(str)
        if timing == 'mid': 
            pool = pool[pool['배당락일'].str.contains('15일|14일|16일|중순')]
        elif timing == 'end': 
            pool = pool[pool['배당락일'].str.contains('마지막|말일|30일|31일|28일|29일|초|하순')]

    # 필터링 결과 종목이 없을 경우 예외 처리
    if pool.empty:
        return "조건에 맞는 종목 없음", [], {}

    # -------------------------------------------------------
    # [교정 2] 점수 산정 (목표 배당률 근접도 우선 평가)
    # -------------------------------------------------------
    
    # 고배당(10% 이상) 목표 시 수익률 가중치 상승, 일반 목표 시 근접도 가중치 적용
    if target_yield >= 10.0:
        pool['score'] = pool['연배당률'] * 5.0  
    else:
        pool['score'] = -abs(pool['연배당률'] - target_yield) * 3.0

    # 종목명 및 순수종목명 내 키워드 매칭 여부 확인 함수
    def has_keyword(row, keywords):
        text = (str(row['종목명']) + " " + str(row.get('pure_name', ''))).lower()
        return any(k.lower() in text for k in keywords)

    # [스타일별 가중치 부여] 성향에 맞는 섹터/키워드 매칭 시 가산점 부여
    if style == 'growth':
        mask = pool.apply(lambda x: has_keyword(x, ['나스닥', 'nasdaq', 'S&P', '미국', '테크', '성장']), axis=1)
        pool.loc[mask, 'score'] += 5
    elif style == 'flow':
        pool['score'] += pool['연배당률'] * 0.8
        mask = pool.apply(lambda x: has_keyword(x, ['커버드콜', 'covered', 'premium', '리츠', '고배당']), axis=1)
        pool.loc[mask, 'score'] += 5
    elif style == 'safe':
        mask = pool.apply(lambda x: has_keyword(x, ['채권', '국채', '금', 'gold', '달러', 'CD', 'KOFR', '단기']), axis=1)
        pool.loc[mask, 'score'] += 10

    # 산출된 점수 기준으로 최상위 종목 추출
    pool = pool.sort_values('score', ascending=False)
    selected_pool = pool.head(wanted_count).copy()
    final_picks = selected_pool['pure_name'].tolist()

    # -------------------------------------------------------
    # [교정 3] 비중 최적화 로직 (목표 배당률 기여도 기반 배분)
    # -------------------------------------------------------
    yields = selected_pool['연배당률'].values
    
    # 목표 배당률에 가장 가까운 종목일수록 더 높은 비중을 할당 (역거리 가중치)
    inv_dist = 1 / (abs(yields - target_yield) + 0.1) 
    weights = (inv_dist / inv_dist.sum()) * 100
    
    # 비중 정수화 및 합계 100% 보정 (마지막 종목에서 차액 조정)
    weights = weights.round().astype(int)
    weights[-1] = 100 - weights[:-1].sum() 
    
    pick_weights = dict(zip(final_picks, weights))
    
    # 결과 타이틀 생성 (배당 시기 뱃지 포함)
    timing_badge = {"mid": "15일 월중배당", "end": "월말/월초배당", "mix": "날짜 혼합"}
    theme_title = f"{timing_badge.get(timing, '맞춤')} 포트폴리오"
        
    return theme_title, final_picks, pick_weights


# -----------------------------------------------------------
# [SECTION 2] 화면 전환 도우미
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
# [SECTION 3] UI 위자드 (Step 1 ~ 5)
# -----------------------------------------------------------

@st.dialog("🕵️ AI 포트폴리오 설계", width="small")
def show_wizard():
    """다이얼로그 형태의 인터랙티브 설문 조사를 통해 포트폴리오를 설계합니다."""
    
    df = st.session_state.get('shared_df')
    if df is None:
        st.error("데이터 오류! 새로고침 해주세요.")
        return

    # 세션 상태 초기화 체크
    if "wiz_step" not in st.session_state:
        st.session_state.wiz_step = 1
    if "wiz_data" not in st.session_state:
        st.session_state.wiz_data = {}

    step = st.session_state.wiz_step

    # --- [STEP 1] 연령대 선택 ---
    if step == 1:
        st.subheader("Q1. 연령대가 어떻게 되시나요?")
        c1, c2, c3 = st.columns(3)
        c1.button("🐣 2030", use_container_width=True, on_click=go_next_step, args=(2, 'age', '2030'))
        c2.button("🦁 4050", use_container_width=True, on_click=go_next_step, args=(2, 'age', '4050'))
        c3.button("🐢 60+", use_container_width=True, on_click=go_next_step, args=(2, 'age', '60plus'))

    # --- [STEP 2] 투자 스타일 선택 ---
    elif step == 2:
        st.subheader("Q2. 어떤 투자를 원하세요?")
        st.button("📈 성장 추구 (주가 상승 + 배당)", use_container_width=True, on_click=go_next_step, args=(3, 'style', 'growth'))
        st.button("💰 현금 흐름 (월 배당금 극대화)", use_container_width=True, on_click=go_next_step, args=(3, 'style', 'flow'))
        st.button("🛡️ 안정성 (원금 방어 최우선)", use_container_width=True, on_click=go_next_step, args=(3, 'style', 'safe'))

    # --- [STEP 3] 배당 시기 선택 ---
    elif step == 3:
        st.subheader("Q3. 선호하는 배당 날짜는요?")
        st.button("🗓️ 월중 (매월 15일 경)", use_container_width=True, on_click=go_next_step, args=(4, 'timing', 'mid'))
        st.button("🔚 월말/월초 (월급날 전후)", use_container_width=True, on_click=go_next_step, args=(4, 'timing', 'end'))
        st.button("🔄 상관없음 (섞어서 2주마다 받기)", use_container_width=True, on_click=go_next_step, args=(4, 'timing', 'mix'))

    # --- [STEP 4] 목표 배당률 및 종목 개수 설정 ---
    elif step == 4:
        st.subheader("Q4. 구체적인 목표를 정해주세요")
        target = st.slider("💰 목표 연배당률 (%)", 3.0, 20.0, 7.0, 0.5)
        
        # [실시간 주의 문구 노출 로직]
        if st.session_state.wiz_data.get('style') == 'safe':
            st.info("🛡️ **안정형 모드:** 자산 보호를 위해 배당률이 **6% 이하**인 종목으로 제한됩니다.")
            if target > 6.0:
                st.warning("설정값이 6%보다 높지만, 결과는 6% 이하 종목에서 선정됩니다.")
        elif target >= 10.0:
            st.error(f"⚠️ **고배당 투자 유의사항 ({target}%)**\n\n원금 손실 위험이 큰 종목이 포함될 수 있습니다.")
        elif target >= 8.0:
            st.warning("💡 8% 이상은 중위험 종목이 포함될 수 있습니다.")
            
        count = st.slider("📊 종목 개수", 3, 5, 3)
        
        if st.button("🚀 결과 확인하기", type="primary", use_container_width=True):
            st.session_state.wiz_data['target_yield'] = target
            st.session_state.wiz_data['count'] = count
            st.session_state.wiz_step = 5
            st.rerun()

    # --- [STEP 5] 최종 추천 결과 출력 ---
    elif step == 5:
        # 무거운 계산 로직은 캐시를 활용하여 중복 연산 방지
        if "ai_result_cache" not in st.session_state:
            with st.spinner("최적 조합 계산 중..."):
                t_res, p_res, w_res = get_smart_recommendation(df, st.session_state.wiz_data)
                st.session_state.ai_result_cache = {"title": t_res, "picks": p_res, "weights": w_res}
        
        cached = st.session_state.ai_result_cache
        title, picks, weights = cached["title"], cached["picks"], cached["weights"]

        # 결과가 없는 경우 예외 처리
        if not picks or title == "조건에 맞는 종목 없음":
            st.error("❌ 조건에 맞는 종목을 찾지 못했습니다. 설정을 변경해 보세요.")
            if st.button("처음으로 돌아가기", use_container_width=True):
                reset_wizard()
                st.rerun()
            return

        # 추천 결과 요약 및 종목 리스트 출력
        st.success(f"**{title}**")
        for stock in picks:
            row_match = df[df['pure_name'] == stock]
            if not row_match.empty:
                row = row_match.iloc[0]
                w = weights.get(stock, 0)
                st.markdown(f"✅ **{stock}** (비중 **{w}%**)")
                st.caption(f"    └ 💰 연 {row['연배당률']:.2f}% | 📅 {row.get('배당락일', '-')}")

        # 면책 조항 (유저 주의 환기)
        st.write("") 
        st.warning("""
        ⚠️ **투자 유의사항**
        * 본 결과는 과거 데이터를 기반으로 한 단순 시뮬레이션이며, 종목의 매수/매도 추천이 아닙니다.
        * 모든 투자의 책임은 투자자 본인에게 있습니다.
        * '안정성'을 추구하는 포트폴리오라 할지라도 시장 변동에 따라 원금 손실이 발생할 수 있습니다.
        """)

        st.divider()
        c_a, c_b = st.columns(2)
        c_a.button("🔄 다시 하기", on_click=reset_wizard, use_container_width=True)
        
        # [담기] 버튼 클릭 시 추천 결과를 메인 시뮬레이션 세션에 연동
        if c_b.button("✅ 담기", type="primary", use_container_width=True):
            st.session_state.selected_stocks = picks
            st.session_state.ai_suggested_weights = weights
            st.session_state.ai_modal_open = False

            # 다음 모달 실행을 위해 캐시 데이터 삭제
            if "ai_result_cache" in st.session_state:
                del st.session_state.ai_result_cache
            
            # 메인 페이지 세션 상태(로그인 등) 백업 및 복구하며 리런
            u_bk = st.session_state.get("user_info")
            l_bk = st.session_state.get("is_logged_in")
            st.toast("장바구니에 담았습니다! 🛒", icon="✅")
            st.session_state.user_info = u_bk
            st.session_state.is_logged_in = l_bk
            st.rerun()
