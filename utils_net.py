# utils_net.py
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

def requests_session_with_retries(total_retries=3, backoff_factor=0.3, status_forcelist=(429,500,502,503,504), timeout=6):
    """
    [네트워크 안전장치]
    인터넷 연결이 불안하거나 상대방 서버가 바쁠 때,
    바로 포기하지 않고 3번까지 재시도하는 '끈기 있는' 통신기를 만듭니다.
    """
    session = requests.Session()
    retries = Retry(
        total=total_retries,
        backoff_factor=backoff_factor,
        status_forcelist=list(status_forcelist),
        allowed_methods=frozenset(['GET','POST','PUT','DELETE','HEAD','OPTIONS'])
    )
    adapter = HTTPAdapter(max_retries=retries)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    
    # 타임아웃 속성 심어두기 (편의용)
    session._timeout = timeout
    return session
