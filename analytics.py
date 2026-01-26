import streamlit as st
from logger import logger

def inject_ga():
    """
    Google Analytics 4 (GA4) 추적 코드를 심습니다.
    (components.html 대신 st.markdown을 사용하여 메인 페이지에 직접 주입)
    """
    # 1. secrets.toml에서 ID 가져오기
    # (없으면 하드코딩된 값이라도 넣어서 테스트해보세요)
    ga_id = st.secrets.get("google_analytics_id", "G-XXXXXXXXXX") 
    
    if not ga_id or ga_id == "G-XXXXXXXXXX":
        logger.warning("⚠️ [Analytics] GA4 ID가 설정되지 않았습니다.")
        return

    # 2. GA4 자바스크립트 코드 (메인 윈도우에 주입)
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
            // 🏠 로컬 환경: 디버그 모드 ON
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
    
    # 3. [핵심 변경] components.html 대신 st.markdown 사용!
    # 그래야 iframe에 갇히지 않고 전체 페이지를 추적합니다.
    st.markdown(ga_code, unsafe_allow_html=True)
    
    # 로그 기록 (세션당 1회)
    if "ga_injected" not in st.session_state:
        logger.info(f"📡 GA4 추적 코드 주입 완료 ({ga_id})")
        st.session_state.ga_injected = True
