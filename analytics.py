import streamlit as st
import streamlit.components.v1 as components

def inject_ga():
    ga_id = st.secrets.get("google_analytics_id")
    
    # 터미널에 ID 출력 (잘 가져오는지 확인용)
    if ga_id:
        print(f"🚀 GA4 ID 로드 완료: {ga_id}")
    else:
        print("❌ GA4 ID를 찾을 수 없음")
        return

    # GA4 추적 코드 (Debug 모드 ON)
    ga_code = f"""
    <script async src="https://www.googletagmanager.com/gtag/js?id={ga_id}"></script>
    <script>
        window.dataLayer = window.dataLayer || [];
        function gtag(){{dataLayer.push(arguments);}}
        gtag('js', new Date());
        
        // [중요] 디버그 모드 켜기 (로컬에서도 데이터 강제 전송)
        gtag('config', '{ga_id}', {{
            'debug_mode': true,
            'cookie_domain': 'none'
        }});
    </script>
    """
    
    # 높이 0짜리 iframe으로 심기
    components.html(ga_code, height=0, width=0)
