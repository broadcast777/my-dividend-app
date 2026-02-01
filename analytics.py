import streamlit as st
import streamlit.components.v1 as components
from logger import logger

def inject_ga():
    """
    Google Analytics 4 (GA4) 추적 코드를 심습니다.
    (st.markdown 대신 components.html을 사용하여 스크립트 실행 보장)
    """
    
    # 1. secrets.toml에서 ID 안전하게 가져오기
    # secrets 파일이 없거나 ID가 설정 안 되어 있으면 None 반환
    ga_id = st.secrets.get("google_analytics_id")
    
    # ID가 없거나 기본값이면 실행 중단 (에러 방지)
    if not ga_id or ga_id == "G-XXXXXXXXXX":
        # logger가 없으면 print로 대체해도 됨
        try:
            logger.warning("⚠️ [Analytics] GA4 ID가 secrets에 설정되지 않았습니다.")
        except:
            pass
        return

    # 2. GA4 자바스크립트 코드 (로컬/배포 환경 자동 감지 로직 포함)
    ga_code = f"""
    <script async src="https://www.googletagmanager.com/gtag/js?id={ga_id}"></script>
    <script>
        window.dataLayer = window.dataLayer || [];
        function gtag(){{dataLayer.push(arguments);}}
        gtag('js', new Date());

        // 📡 현재 접속한 주소(도메인) 확인
        var host = window.location.hostname;
        var isLocal = (host === "localhost" || host === "127.0.0.1" || host.includes("192.168"));

        if (isLocal) {{
            // 🏠 로컬 환경: 디버그 모드 ON (데이터가 섞이지 않게 처리)
            console.log("🚀 GA4: 로컬 개발 환경 감지됨 (Debug Mode ON) - ID: {ga_id}");
            gtag('config', '{ga_id}', {{
                'debug_mode': true,
                'cookie_domain': 'none' 
            }});
        }} else {{
            // ☁️ 배포 환경: 정상 집계 모드
            console.log("✅ GA4: 배포 환경 감지됨 - ID: {ga_id}");
            gtag('config', '{ga_id}');
        }}
    </script>
    """

    # 3. [핵심] 투명 iframe으로 스크립트 강제 실행
    # height=0, width=0으로 설정하여 사용자 눈에는 보이지 않음
    components.html(ga_code, height=0, width=0)
    
    # 4. 로그 기록 (세션당 1회만 남기기)
    if "ga_injected" not in st.session_state:
        try:
            logger.info(f"📡 GA4 추적 코드 주입 시도 완료 (ID 숨김 처리됨)")
        except:
            pass
        st.session_state.ga_injected = True
