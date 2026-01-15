import streamlit as st
import time
import random
import pandas as pd

# -----------------------------------------------------------
# [1] 스마트 필터링 엔진 (최종 완성판 V4.0)
# -----------------------------------------------------------
def get_smart_recommendation(df, user_choices):
    # 1. 사용자 입력
    target_yield = user_choices.get('target_yield', 7.0)
    style = user_choices.get('style', 'balance')   # growth / flow / safe
    age = user_choices.get('age', '4050')          # 2030 / 4050 / 60plus
    timing = user_choices.get('timing', 'mix')     # mid / end / mix
    wanted_count = user_choices.get('count', 3)    # 3~5개
    
    # 2. 데이터 복사 (배당률 있는 것만)
    pool = df[df['연배당률'] > 0].copy()
    
    # [기본 점수] 목표 배당률 근접도 (거리가 멀수록 감점)
    pool['score'] = -abs(pool['연배당률'] - target_yield) * 2

    # -------------------------------------------------------
    # [전략 0] 배당 시기 (Timing) - 안전 처리
    # -------------------------------------------------------
    if '배당락일' in pool.columns:
        pool['배당락일'] = pool['배당락일'].fillna('').astype(str)
        if timing == 'mid': # 15일/중순
            mask = pool['배당락일'].str.contains('15일|14일|16일|중순')
            pool.loc[mask, 'score'] += 10
        elif timing == 'end': # 월말/월초
            mask = pool['배당락일'].str.contains('마지막|말일|30일|31일|28일|29일|초|하순')
            pool.loc[mask, 'score'] += 10
        # mix는 점수 반영 없음 (자연스럽게 섞임)

    # -------------------------------------------------------
    # [전략 1] 안정성 (배당 역사) - 안전 처리
    # -------------------------------------------------------
    if '배당기록' in pool.columns:
        def check_history(record):
            if not isinstance(record, str): return 0
            return len(record.split('|'))
        
        pool['history_cnt'] = pool['배당기록'].apply(check_history)
        pool['score'] += pool['history_cnt'] * 0.1 # 오래될수록 가산점
    else:
        pool['history_cnt'] = 0

    # -------------------------------------------------------
    # [전략 2] 키워드 매칭 함수
    # -------------------------------------------------------
    def has_keyword(row, keywords):
        text = (str(row['종목명']) + " " + str(row.get('pure_name', ''))).lower()
        return any(k.lower() in text for k in keywords)

    # -------------------------------------------------------
    # [전략 3] 연령대별 가중치
    # -------------------------------------------------------
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
        if '신규상장개월수' in pool.columns:
            try: pool.loc[pool['신규상장개월수'].astype(int) < 12, 'score'] -= 3
            except: pass

    # -------------------------------------------------------
    # [전략 4] 투자 성향별 가중치
    # -------------------------------------------------------
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
    # [최종] 5. 스타일별 쿼터제 & 다양성 (밸런스 패치)
    # -------------------------------------------------------
    # 1. 점수 순 정렬
    pool = pool.sort_values('score', ascending=False)
    
    # 2. 커버드콜(CC) 식별
    cc_keys = ['커버드콜', 'covered', '타겟', 'premium', '200위클리', 'top10', 'monthly', 'jepi', 'qyld', 'nvid', 'tsly']
    pool['is_cc'] = pool.apply(lambda x: has_keyword(x, cc_keys), axis=1)
    
    pool_cc = pool[pool['is_cc'] == True]      # 커버드콜 그룹
    pool_normal = pool[pool['is_cc'] == False] # 일반 그룹
    
    # 3. 스타일별 커버드콜 한도 설정 (선생님 피드백 반영!)
    if style == 'growth':
        limit_cc = 1  # 성장형: 배당 보너스로 최대 1개
    elif style == 'safe':
        limit_cc = 1  # 안정형: 수익률 보정을 위해 최대 1개 허용 (0개 아님!)
    else:
        limit_cc = int(wanted_count * 0.4) # 현금흐름형: 40% (2개 정도)
        if limit_cc < 1: limit_cc = 1

    # 4. 종목 추출 (상위권에서 후보군 뽑아서 랜덤)
    picks_cc = []
    picks_normal = []

    # (A) 커버드콜 뽑기
    if limit_cc > 0 and not pool_cc.empty:
        cand_cc = pool_cc.head(limit_cc * 3) # 후보군 3배수
        k_cc = min(len(cand_cc), limit_cc)
        if k_cc > 0:
            picks_cc = random.sample(cand_cc['pure_name'].tolist(), k_cc)
            
    # (B) 일반 종목 뽑기
    rem_count = wanted_count - len(picks_cc)
    if not pool_normal.empty:
        cand_norm = pool_normal.head(rem_count * 2) # 후보군 2배수
        k_norm = min(len(cand_norm), rem_count)
        if k_norm > 0:
            picks_normal = random.sample(cand_norm['pure_name'].tolist(), k_norm)
            
    # 5. 합치기 & 부족분 채우기
    final_picks = picks_cc + picks_normal
    
    if len(final_picks) < wanted_count:
        needed = wanted_count - len(final_picks)
        pool_remain = pool[~pool['pure_name'].isin(final_picks)]
        if not pool_remain.empty:
            more = pool_remain.head(needed)['pure_name'].tolist()
            final_picks.extend(more)
            
    # 6. 순서 섞기
    random.shuffle(final_picks)
    
    # 타이틀 생성
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
    # 캐시 초기화 (NameError 방지)
    if "ai_result_cache" in st.session_state:
        del st.session_state.ai_result_cache

# -----------------------------------------------------------
# [3] UI 위자드 (Step 1 ~ 5)
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

    # --- [STEP 4] 목표 설정 (현실화) ---
    elif step == 4:
        st.subheader("Q4. 구체적인 목표를 정해주세요")
        st.write("")
        
        # [수정] 최소 3% (성장주/안정형 포함)
        target = st.slider("💰 목표 연배당률 (%)", 3.0, 20.0, 7.0, 0.5, format="%f%%")
        
        # [수정] 종목 3~5개 (집중 투자)
        count = st.slider("📊 포트폴리오 종목 개수", 3, 5, 3)
        st.write("")
        
        def save_and_go():
            st.session_state.wiz_data['target_yield'] = target
            st.session_state.wiz_data['count'] = count
            st.session_state.wiz_step = 5

        st.button("🚀 결과 확인하기", type="primary", use_container_width=True, on_click=save_and_go)

    # --- [STEP 5] 결과 및 담기 ---
    elif step == 5:
        # 1. 계산 결과 캐싱 (NameError 방지)
        if "ai_result_cache" not in st.session_state:
            with st.spinner("AI가 최적의 조합을 찾는 중..."):
                time.sleep(0.7) 
                t_res, p_res = get_smart_recommendation(df, st.session_state.wiz_data)
                st.session_state.ai_result_cache = {"title": t_res, "picks": p_res}
        
        # 2. 캐시에서 불러오기
        cached = st.session_state.ai_result_cache
        title = cached["title"]
        picks = cached["picks"]
        
        user_name = st.session_state.get("user_id", st.session_state.get("user_email", "회원님"))
        if "@" in user_name: user_name = user_name.split("@")[0]

        st.success(f"**{title}**")
        st.write(f"**{user_name}** 님의 조건에 딱 맞는 종목들입니다.")
        
        st.write("📋 **추천 리스트 (상세 정보)**")
        
        if not picks:
            st.warning("조건에 맞는 종목을 찾지 못했습니다. 설정을 조금 변경해보세요.")
        else:
            for stock in picks:
                row = df[df['pure_name'] == stock]
                if not row.empty:
                    r_data = row.iloc[0]
                    rate = r_data['연배당률']
                    
                    # [안전] 배당락일 확인
                    date = str(r_data.get('배당락일', '-'))
                    if date == 'nan': date = '-'
                    
                    # [안전] 직전 배당금 추출 (0원 방지)
                    hist_raw = str(r_data.get('배당기록', ''))
                    last_div = "0"
                    if hist_raw and hist_raw != 'nan' and hist_raw.strip():
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
        
        # [안전] 장바구니 담기 (로그아웃 방지)
        if col_b.button("✅ 장바구니 담기", type="primary"):
            st.session_state.selected_stocks = picks
            st.session_state.wiz_step = 1
            st.session_state.ai_modal_open = False
            
            # 캐시 삭제
            if "ai_result_cache" in st.session_state:
                del st.session_state.ai_result_cache
            
            # 인증 정보 백업
            u_bk = st.session_state.get("user_info")
            l_bk = st.session_state.get("is_logged_in")
            
            st.toast("장바구니에 담았습니다! 🛒", icon="✅")
            
            # 복구 & 새로고침
            st.session_state.user_info = u_bk
            st.session_state.is_logged_in = l_bk
            
            st.rerun()
