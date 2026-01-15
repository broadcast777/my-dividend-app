import streamlit as st
import time
import random
import pandas as pd

# -----------------------------------------------------------
# [1] 스마트 필터링 엔진 (무적 방어 로직 적용)
# -----------------------------------------------------------
def get_smart_recommendation(df, user_choices):
    # 1. 사용자 입력
    target_yield = user_choices.get('target_yield', 7.0)
    style = user_choices.get('style', 'balance')
    age = user_choices.get('age', '4050')
    timing = user_choices.get('timing', 'mix')
    wanted_count = user_choices.get('count', 5)
    
    # 2. 데이터 복사 (안전하게)
    pool = df[df['연배당률'] > 0].copy()
    
    # [기본 점수] 목표 배당률 근접도
    pool['score'] = -abs(pool['연배당률'] - target_yield) * 2

    # -------------------------------------------------------
    # [전략 0] 배당 시기 (Timing) -> '배당락일' 사용
    # -------------------------------------------------------
    # 컬럼이 있는지 확인하고("if") 안전하게 처리
    if '배당락일' in pool.columns:
        pool['배당락일'] = pool['배당락일'].fillna('').astype(str)
        
        if timing == 'mid': # 15일/중순
            mask = pool['배당락일'].str.contains('15일|14일|16일|중순')
            pool.loc[mask, 'score'] += 10
        elif timing == 'end': # 월말/월초
            mask = pool['배당락일'].str.contains('마지막|말일|30일|31일|28일|29일|초|하순')
            pool.loc[mask, 'score'] += 10

    # -------------------------------------------------------
    # [전략 1] 안정성 (배당 역사) -> '배당기록' 사용
    # -------------------------------------------------------
    # 여기가 아까 에러났던 부분! 안전 장치 추가 완료.
    if '배당기록' in pool.columns:
        def check_history(record):
            if not isinstance(record, str): return 0
            # 파이프(|) 개수로 배당 횟수 추정
            return len(record.split('|'))
        
        pool['history_cnt'] = pool['배당기록'].apply(check_history)
        pool['score'] += pool['history_cnt'] * 0.1
    else:
        # 없으면 그냥 0으로 채움 (에러 방지)
        pool['history_cnt'] = 0

    # -------------------------------------------------------
    # [전략 2] 키워드 매칭 함수
    # -------------------------------------------------------
    def has_keyword(row, keywords):
        text = (str(row['종목명']) + " " + str(row.get('pure_name', ''))).lower()
        return any(k.lower() in text for k in keywords)

    # -------------------------------------------------------
    # [전략 3] 연령대 & 투자 성향 (점수 로직)
    # -------------------------------------------------------
    # (A) 연령대
    if age == '2030':
        pool['score'] += pool['연배당률'] * 0.3
        mask = pool.apply(lambda x: has_keyword(x, ['테크', '나스닥', 'nasdaq', 'S&P', '성장', 'AI', '반도체']), axis=1)
        pool.loc[mask, 'score'] += 5
    elif age == '4050':
        pool['score'] += pool['연배당률'] * 0.4
        mask = pool.apply(lambda x: has_keyword(x, ['고배당', '리츠', 'reit', '배당', '금융']), axis=1)
        pool.loc[mask, 'score'] += 3
    elif age == '60plus':
        mask_kor = pool['분류'] == '국내'
        pool.loc[mask_kor, 'score'] += 3
        # 신규 상장 감점 (컬럼 있을 때만)
        if '신규상장개월수' in pool.columns:
            try: pool.loc[pool['신규상장개월수'].astype(int) < 12, 'score'] -= 3
            except: pass

    # (B) 투자 성향
    if style == 'growth':
        mask = pool.apply(lambda x: has_keyword(x, ['나스닥', 'nasdaq', 'S&P', '미국', '테크', '성장', '다우존스']), axis=1)
        pool.loc[mask, 'score'] += 6
    elif style == 'flow':
        pool['score'] += pool['연배당률'] * 0.8
        flow_keys = ['커버드콜', 'covered', '타겟', 'premium', '월지급', '리츠', 'reit', '고배당', '우선주', 'pff', 'jepi']
        mask = pool.apply(lambda x: has_keyword(x, flow_keys), axis=1)
        pool.loc[mask, 'score'] += 6
        if age == '60plus': pool.loc[mask, 'score'] += 3
    elif style == 'safe':
        safe_keys = ['채권', '국채', '금', 'gold', '달러', 'CD', 'KOFR', '단기', 'treasury', 't-bill', 'bond', 'shv', 'bil', 'sgov']
        mask_safe = pool.apply(lambda x: has_keyword(x, safe_keys), axis=1)
        pool.loc[mask_safe, 'score'] += 10
        mask_risk = pool.apply(lambda x: has_keyword(x, ['레버리지', '2X', '인버스', 'high yield']), axis=1)
        pool.loc[mask_risk, 'score'] -= 20
        pool.loc[pool['연배당률'] > 12, 'score'] -= 10

    # -------------------------------------------------------
    # [최종] 다양성 확보 (Shuffle)
    # -------------------------------------------------------
    # 1. 점수 순 정렬
    pool = pool.sort_values('score', ascending=False)
    
    # 2. 상위 2배수 후보군
    candidate_pool = pool.head(wanted_count * 2)
    
    # 3. 랜덤 샘플링
    if len(candidate_pool) >= wanted_count:
        final_picks_df = candidate_pool.sample(wanted_count)
    else:
        final_picks_df = candidate_pool
        
    final_picks = final_picks_df['pure_name'].tolist()
    
    # 타이틀
    timing_badge = {"mid": "15일 월중배당", "end": "월말/월초배당", "mix": "날짜 혼합"}
    theme_title = f"{timing_badge.get(timing)} 맞춤 포트폴리오"
        
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
    df = st.session_state.get('shared_df')
    if df is None:
        st.error("데이터 오류! 새로고침 해주세요.")
        return

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

    # --- [STEP 3] 배당 시기 ---
    elif step == 3:
        st.subheader("Q3. 선호하는 배당 날짜는요?")
        st.write("")
        st.button("🗓️ 월중 (매월 15일 경)", use_container_width=True, on_click=go_next_step, args=(4, 'timing', 'mid'))
        st.button("🔚 월말/월초 (월급날 전후)", use_container_width=True, on_click=go_next_step, args=(4, 'timing', 'end'))
        st.button("🔄 상관없음 (섞어서 2주마다 받기)", use_container_width=True, on_click=go_next_step, args=(4, 'timing', 'mix'))

    # --- [STEP 4] 목표 설정 ---
    elif step == 4:
        st.subheader("Q4. 구체적인 목표를 정해주세요")
        st.write("")
        target = st.slider("💰 목표 연배당률 (%)", 3.0, 20.0, 7.0, 0.5, format="%f%%")
        count = st.slider("📊 포트폴리오 종목 개수", 3, 7, 5)
        st.write("")
        
        def save_and_go():
            st.session_state.wiz_data['target_yield'] = target
            st.session_state.wiz_data['count'] = count
            st.session_state.wiz_step = 5

        st.button("🚀 결과 확인하기", type="primary", use_container_width=True, on_click=save_and_go)

    # --- [STEP 5] 결과 및 담기 ---
    elif step == 5:
        # [핵심 수정] 결과를 세션에 저장해서 'NameError' 방지 & 재계산 방지
        if "ai_result_cache" not in st.session_state:
            with st.spinner("AI가 최적의 조합을 찾는 중..."):
                time.sleep(0.7) 
                # 여기서 계산 실행
                title_res, picks_res = get_smart_recommendation(df, st.session_state.wiz_data)
                # 결과 저장
                st.session_state.ai_result_cache = {"title": title_res, "picks": picks_res}
        
        # 저장된 결과 불러오기 (이제 변수가 사라지지 않습니다!)
        cached_data = st.session_state.ai_result_cache
        title = cached_data["title"]
        picks = cached_data["picks"]
        
        user_name = st.session_state.get("user_id", st.session_state.get("user_email", "회원님"))
        if "@" in user_name: user_name = user_name.split("@")[0]

        st.success(f"**{title}**")
        st.write(f"**{user_name}** 님의 조건에 딱 맞는 종목들입니다.")
        
        st.write("📋 **추천 리스트 (상세 정보)**")
        
        # [수정] picks가 비어있을 경우를 대비한 방어 코드
        if not picks:
            st.warning("조건에 맞는 종목을 찾지 못했습니다. 다시 시도해주세요.")
        else:
            for stock in picks:
                row = df[df['pure_name'] == stock]
                if not row.empty:
                    r_data = row.iloc[0]
                    rate = r_data['연배당률']
                    
                    # 안전한 접근 (Safe Access)
                    date = str(r_data.get('배당락일', '-'))
                    if date == 'nan': date = '-'
                    
                    # 직전 배당금 추출
                    hist_raw = str(r_data.get('배당기록', ''))
                    last_div = "0"
                    if hist_raw and hist_raw != 'nan':
                        try:
                            vals = hist_raw.split('|')
                            if vals: last_div = vals[0].strip()
                        except: last_div = "0"

                    # 통화 단위
                    category = str(r_data.get('분류', '국내'))
                    div_str = f"${last_div}" if '해외' in category else f"{last_div}원"

                    st.text(f"- {stock}")
                    st.caption(f"  └ 💰 연 {rate:.2f}% | 📅 {date} | 💸 지난달 {div_str}")
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
        
        if col_b.button("✅ 장바구니 담기", type="primary"):
            st.session_state.selected_stocks = picks
            st.session_state.wiz_step = 1
            st.session_state.ai_modal_open = False
            
            # 초기화 (다음을 위해 결과 캐시 삭제)
            if "ai_result_cache" in st.session_state:
                del st.session_state.ai_result_cache

            u_bk = st.session_state.get("user_info")
            l_bk = st.session_state.get("is_logged_in")
            
            st.toast("장바구니에 담았습니다! 🛒", icon="✅")
            
            st.session_state.user_info = u_bk
            st.session_state.is_logged_in = l_bk
            
            st.rerun()
