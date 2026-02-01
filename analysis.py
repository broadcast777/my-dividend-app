import streamlit as st
import pandas as pd
import altair as alt
import db  # DB 연결 도구

# ---------------------------------------------------------
# 1. 데이터 정제 함수
# ---------------------------------------------------------
def _get_clean_data(row, col_map):
    raw_name = row.get(col_map['stock_name'], '') 
    name = str(raw_name).upper().strip()
    
    # 제외 키워드
    exclude_keywords = ['KODEX', 'TIGER', 'RISE', 'ACE', 'SOL', 'KOSEF', 'ARIRANG', '스왑', '설정액', 'PLUS', 'USD', 'KRW', '선물']
    if any(x in name for x in exclude_keywords): return None, None, None

    clean_name = name
    if any(x in name for x in ['NVIDIA', 'NVDA', '엔비디아']): clean_name = '엔비디아'
    elif any(x in name for x in ['APPLE', 'AAPL', '애플']): clean_name = '애플'
    elif any(x in name for x in ['MICROSOFT', 'MSFT', '마이크로소프트']): clean_name = '마이크로소프트'
    elif any(x in name for x in ['ALPHABET', 'GOOG', '알파벳']): clean_name = '구글(알파벳)'
    elif any(x in name for x in ['META', '메타']): clean_name = '메타'
    elif any(x in name for x in ['TESLA', 'TSLA', '테슬라']): clean_name = '테슬라'
    elif any(x in name for x in ['AMAZON', 'AMZN', '아마존']): clean_name = '아마존'
    elif any(x in name for x in ['BROADCOM', 'AVGO', '브로드컴']): clean_name = '브로드컴'

    sector = str(row.get(col_map['category'], '기타'))
    
    # 섹터 분류 (짧은 이름)
    if '하이일드' in clean_name or 'USHY' in clean_name or 'JNK' in clean_name or 'HYG' in clean_name or '고수익' in sector:
        sector = "🔥 하이일드"
    elif any(x in clean_name for x in ['BIL', 'SHV', 'SGOV', '초단기', 'CD금리', 'KOFR', '머니마켓', '현금', '예금']):
        sector = "🛡️ 현금"
    elif '국채' in clean_name or '채권' in clean_name or 'TLT' in clean_name or '30년' in clean_name: 
        sector = "📉 국채"
    elif clean_name in ['엔비디아', '애플', '마이크로소프트', '구글(알파벳)', '메타', '테슬라', '아마존', '브로드컴']: sector = "💻 빅테크"
    elif '금융' in sector or '은행' in clean_name or '지주' in clean_name: sector = "💰 금융"
    elif '리츠' in sector or '부동산' in clean_name or '인프라' in clean_name: sector = "🏢 리츠"
    elif '산업재' in sector or '자동차' in clean_name: sector = "🚗 산업재"
    elif '필수소비재' in sector: sector = "🛒 소비재"

    try: 
        w_val = row.get(col_map['weight'], 0)
        if isinstance(w_val, str): weight = float(w_val.replace('%', '').strip())
        else: weight = float(w_val)
    except: weight = 0.0
    
    return clean_name, sector, weight

# ---------------------------------------------------------
# 2. UI 컴포넌트 (멘트 최적화됨)
# ---------------------------------------------------------
def _render_blur_ui(top_weight, top_stock_sector, max_portfolio_sector):
    # 1. [용어 보정]
    display_sector = top_stock_sector
    if "현금" in top_stock_sector: display_sector = "현금성 자산"
    elif "국채" in top_stock_sector: display_sector = "미국 국채"
    elif "하이일드" in top_stock_sector: display_sector = "하이일드 채권"
    
    # 2. [문구 최적화] '단일 종목' -> '기초자산' (오해 방지)
    if top_stock_sector == max_portfolio_sector:
        badge_text = f"{display_sector} 내 비중 1위"
        description = f"현재 포트폴리오에서 <b>{max_portfolio_sector}</b> 섹터의 비중이 가장 높으며,<br>해당 섹터 내에서 이 자산이 가장 큰 비중을 차지하고 있습니다."
    else:
        badge_text = f"{display_sector} 최다 보유"
        description = f"전체적으로는 <b>{max_portfolio_sector}</b> 섹터 비중이 높지만,<br><span style='color:#0050ff; font-weight:bold;'>ETF 속 알맹이(기초자산) 기준으로는 {display_sector}인 이 자산이 1위입니다.</span>"

    # 3. [배지 색상 설정]
    badge_bg, badge_color = "#f1f3f5", "#495057"
    if "빅테크" in top_stock_sector: badge_bg, badge_color = "#e7f5ff", "#1971c2"
    elif "금융" in top_stock_sector: badge_bg, badge_color = "#fff9db", "#f08c00"
    elif "현금" in top_stock_sector: badge_bg, badge_color = "#e6fcf5", "#0ca678" 
    elif "국채" in top_stock_sector: badge_bg, badge_color = "#f3f0ff", "#7950f2" 
    elif "하이일드" in top_stock_sector: badge_bg, badge_color = "#fff5f5", "#fa5252"
    
    # 4. [상단 카드] 제목 변경 (종목 -> 기초자산)
    html_top = f"""
    <div style="border: 1px solid #e0e0e0; border-bottom: none; border-top-left-radius: 16px; border-top-right-radius: 16px; background-color: white; padding: 24px 24px 10px 24px; text-align: center; margin-bottom: -5px;">
        <span style="background-color: {badge_bg}; color: {badge_color}; padding: 4px 12px; border-radius: 20px; font-size: 12px; font-weight: 700; display: inline-block; margin-bottom: 12px;">{badge_text}</span>
        <h4 style="margin: 0 0 8px 0; color: #868e96; font-size: 14px; font-weight: 500;">가장 비중이 큰 기초자산</h4>
        <p style="margin: 0; font-size: 32px; font-weight: 800; color: #343a40; letter-spacing: -0.5px;"><span style="color: #0050ff;">???</span> <span style="font-weight: 300; color: #868e96;">({top_weight:.1f}%)</span></p>
    </div>
    """
    st.markdown(html_top, unsafe_allow_html=True)

    # 5. [중간 버튼]
    st.markdown("""<style>div[data-testid="column"] { padding: 0 !important; }</style>""", unsafe_allow_html=True)
    c1, c2, c3 = st.columns([0.2, 0.6, 0.2])
    with c2:
        btn = st.button("🔒 자산명 확인하기 (로그인 필요)", use_container_width=True) # 버튼 멘트도 '자산명'으로 변경
        if btn:
            st.toast("로그인이 필요합니다!", icon="🔒")
            st.error("상단(모바일은 메뉴)의 로그인 버튼을 이용해 주세요.")

    # 6. [하단 카드]
    html_bottom = f"""
    <div style="border: 1px solid #e0e0e0; border-top: none; border-bottom-left-radius: 16px; border-bottom-right-radius: 16px; background-color: #f8f9fa; padding: 15px 24px 24px 24px; margin-top: -5px;">
        <div style="filter: blur(5px); -webkit-filter: blur(5px); opacity: 0.6; user-select: none;">
            <p style="margin: 0 0 12px 0; font-size: 14px; line-height: 1.6; color: #495057;">{description}</p>
            <div style="width: 70%; height: 10px; background: #dee2e6; margin-bottom: 8px; border-radius: 5px;"></div>
            <div style="width: 50%; height: 10px; background: #dee2e6; margin-bottom: 8px; border-radius: 5px;"></div>
        </div>
    </div>
    """
    st.markdown(html_bottom, unsafe_allow_html=True)

# ---------------------------------------------------------
# 3. 메인 분석 함수
# ---------------------------------------------------------
def render_analysis(user_weights, user_name, is_logged_in):
    # 제목도 조금 더 명확하게 수정
    st.header("🧐 ETF 속 실제 보유 자산 분석")
    st.markdown("ETF 겉포장이 아닌, **실제로 투자되고 있는 알맹이(기초자산)** 기준의 비중입니다.")
    st.markdown("---")

    supabase = db.init_supabase()
    if not supabase:
        st.error("❌ DB 연결 실패")
        return

    total_input = sum(user_weights.values())
    if total_input == 0: return
    normalized_weights = {k: (v / total_input) * 100 for k, v in user_weights.items()}

    try:
        response = supabase.table("etf_holdings").select("*").execute()
        if not response.data:
            st.error("🚨 DB 데이터 없음")
            return
        df_raw = pd.DataFrame(response.data)
    except Exception as e:
        st.error(f"❌ 데이터 로드 오류: {e}")
        return

    cols = df_raw.columns.tolist()
    col_map = {
        'etf_name': next((c for c in cols if c in ['ETF명', 'etf명', 'etf_name']), 'ETF명'),
        'etf_code': next((c for c in cols if c in ['ETF코드', 'etf코드', 'etf_code']), 'ETF코드'),
        'stock_name': next((c for c in cols if c in ['보유종목명', '보유종목', 'stock_name']), '보유종목명'),
        'weight': next((c for c in cols if c in ['비중', 'weight']), '비중'),
        'category': next((c for c in cols if c in ['분류', 'category']), '분류'),
    }

    try:
        df_raw['KEY_NAME'] = df_raw[col_map['etf_name']].astype(str).str.replace(' ', '').str.upper()
        df_raw['KEY_CODE'] = df_raw[col_map['etf_code']].astype(str).str.replace(' ', '').str.upper()
        df_raw['비중_수치'] = pd.to_numeric(df_raw[col_map['weight']], errors='coerce').fillna(0)
    except KeyError:
        st.error("🚨 DB 컬럼 형식 오류")
        return

    etf_sums = df_raw.groupby(col_map['etf_name'])['비중_수치'].sum()
    scale_correction_map = {etf: (100.0 / s if s > 0 else 0) for etf, s in etf_sums.items()}

    exposure = {}
    failed_etfs = [] 

    ALIAS_MAP = {
        "KODEX 미국30년국채타겟커버드콜(합성)": "KODEX 미국30년국채액티브(H)",
        "ACE 미국30년국채액티브(H)": "ACE 미국30년국채액티브",
        "SOL 미국30년국채액티브(H)": "SOL 미국30년국채커버드콜(합성)", 
        "TIGER 미국초단기(3개월이하)국채": "TIGER 미국초단기채권액티브",
    }

    for etf_input, u_w in normalized_weights.items():
        if u_w <= 0: continue
        target_name = ALIAS_MAP.get(etf_input, etf_input)
        search_key = str(target_name).replace(' ', '').upper()
        
        items = df_raw[df_raw['KEY_NAME'] == search_key]
        if items.empty: items = df_raw[df_raw['KEY_CODE'] == search_key]
        if items.empty: items = df_raw[df_raw['KEY_NAME'].str.contains(search_key, na=False)]
        
        if items.empty:
            failed_etfs.append(etf_input)
            continue
        
        matched_etf_name = items.iloc[0][col_map['etf_name']]
        target_items = df_raw[df_raw[col_map['etf_name']] == matched_etf_name]
        correction_factor = scale_correction_map.get(matched_etf_name, 1.0)

        for _, row in target_items.iterrows():
            c_name, sector, w = _get_clean_data(row, col_map)
            if not c_name: continue
            
            real_w = (w * correction_factor / 100) * u_w 
            if c_name not in exposure: exposure[c_name] = {'w': 0, 's': sector}
            exposure[c_name]['w'] += real_w

    if failed_etfs:
        st.toast(f"⚠️ 매칭 실패: {failed_etfs}", icon="ℹ️")

    if not exposure: 
        st.warning("🔍 표시할 데이터가 없습니다.")
        return

    df_exp = pd.DataFrame([{'종목': k, '비중': v['w'], '섹터': v['s']} for k, v in exposure.items()]).sort_values('비중', ascending=False)
    
    total_exposure = df_exp['비중'].sum()
    if total_exposure > 0: df_exp['비중'] = (df_exp['비중'] / total_exposure) * 100

    sector_df = df_exp.groupby('섹터')['비중'].sum().reset_index().sort_values('비중', ascending=False)
    max_s, max_p = sector_df.iloc[0]['섹터'], sector_df.iloc[0]['비중']
    top_stock_weight = df_exp.iloc[0]['비중']
    top_stock_sector = df_exp.iloc[0]['섹터']

    if not is_logged_in:
        _render_blur_ui(top_stock_weight, top_stock_sector, max_s)
    else:
        benchmark = { 
            "💻 빅테크": 38.5, 
            "💰 금융": 12.0, 
            "🚗 산업재": 15.2, 
            "🏢 리츠": 1.2, 
            "🛡️ 현금": 5.0,
            "📉 국채": 0.0,
            "🔥 하이일드": 0.0 
        }
        avg_val = benchmark.get(max_s, 10.0)
        diff = max_p - avg_val
        
        bg, border, label = ("#fff5f5", "#ff8787", "집중도 높음 (경계)") if max_p >= 50 else ("#fff9db", "#fab005", "집중도 관찰 (주의)")
        if max_p < 40: bg, border, label = ("#e6fcf5", "#63e6be", "양호 (분산됨)")

        st.markdown(f"""
        <div style="background-color: {bg}; border: 1px solid {border}; border-radius: 12px; padding: 20px; margin-bottom: 20px;">
            <div style="font-size: 14px; font-weight: bold; color: #495057; margin-bottom: 8px;">📍 {label}</div>
            <div style="font-size: 16px; color: #212529; line-height: 1.6;">
                {user_name}님의 포트폴리오 내 <b>{max_s}</b> 비중이 <b>{max_p:.1f}%</b>입니다. <br>
                <span style="font-size: 14px; color: #495057;">
                    (<b>코스피(KOSPI) 시장</b> 평균 대비 <b>{diff:+.1f}%p</b> 차이)
                </span>
            </div>
        </div>
        """, unsafe_allow_html=True)

        c1, c2 = st.columns([1.3, 1])
        with c1:
            st.markdown("##### 🏗️ 섹터별 실질 비중")
            bar = alt.Chart(df_exp).mark_bar(cornerRadius=3, height=20).encode(
                x=alt.X('sum(비중)', axis=None), 
                y=alt.Y('섹터', sort='-x', axis=alt.Axis(labels=True, tickSize=0, title=None)), 
                color=alt.Color('섹터', legend=None, scale=alt.Scale(scheme='tableau10')), 
                order=alt.Order('비중', sort='descending'),
                tooltip=[alt.Tooltip('종목'), alt.Tooltip('비중', format='.1f'), alt.Tooltip('섹터')]
            )
            st.altair_chart(bar.properties(height=200), use_container_width=True)
            
        with c2:
            st.markdown("##### 🏆 상위 종목 TOP 5")
            st.dataframe(
                df_exp.head(5)[['비중', '종목']], 
                column_config={"비중": st.column_config.ProgressColumn(format="%.1f%%", min_value=0, max_value=100)}, 
                hide_index=True, use_container_width=True
            )
    
    st.markdown("---")
    st.info("""
    **📢 투자 주의사항**
    1. **시점 안내:** 상기 데이터는 최근 공시 기준이며, 실제 운용 현황과 차이가 있을 수 있습니다.
    2. **책임 제한:** 본 분석은 참고용이며, 투자 권유가 아닙니다.
    """)
