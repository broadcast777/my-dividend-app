import streamlit as st
import streamlit.components.v1 as components
from logger import logger # 아까 만든 관제 시스템 연동

def inject_ga():
    """
    Google Analytics 4 (GA4) 추적 코드를 심습니다.
    - 로컬(localhost) 환경: Debug 모드 자동 활성화 (통계 오염 방지)
    - 배포(Server) 환경: 정상 집계 모드 자동 전환
    """
    # secrets.toml에서 ID 가져오기
    ga_id = st.secrets.get("google_analytics_id")
    
    if not ga_id:
        logger.warning("⚠️ [Analytics] GA4 ID가 설정되지 않았습니다. 통계 수집이 중단됩니다.")
        return

    # GA4 자바스크립트 코드 (환경 자동 감지 로직 포함)
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
            // 🏠 로컬 환경: 디버그 모드 ON (데이터가 DebugView로만 전송됨)
            console.log("🚀 GA4: 로컬 개발 환경 감지됨 (Debug Mode ON)");
            gtag('config', '{ga_id}', {{
                'debug_mode': true,
                'cookie_domain': 'none' 
            }});
        }} else {{
            // ☁️ 배포 환경: 정상 집계 모드
            gtag('config', '{ga_id}');
        }}
    </script>
    """
    
    # iframe을 통해 헤더에 스크립트 주입 (화면에는 안 보임)
    components.html(ga_code, height=0, width=0)
    
    # (선택) 로그에 한 번만 기록 (너무 자주 뜨지 않게 세션 체크)
    if "ga_injected" not in st.session_state:
        logger.info(f"📡 GA4 추적 코드 주입 완료 ({ga_id})")
        st.session_state.ga_injected = True
