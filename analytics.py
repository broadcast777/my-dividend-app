import streamlit as st
import streamlit.components.v1 as components

def inject_ga():
    """구글 애널리틱스(GA4) 추적 코드를 심는 함수"""
    
    # secrets.toml에서 ID 가져오기 (없으면 작동 안 함)
    ga_id = st.secrets.get("google_analytics_id")
    
    if not ga_id:
        return

    # GA4 추적 스크립트 (HTML 헤더 삽입용)
    ga_code = f"""
    <script async src="https://www.googletagmanager.com/gtag/js?id={ga_id}"></script>
    <script>
        window.dataLayer = window.dataLayer || [];
        function gtag(){{dataLayer.push(arguments);}}
        gtag('js', new Date());
        gtag('config', '{ga_id}');
    </script>
    """
    
    # 사용자 눈에는 안 보이게(height=0) 스크립트만 심음
    components.html(ga_code, height=0, width=0)
