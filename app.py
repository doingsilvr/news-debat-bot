import streamlit as st
from openai import OpenAI
from PIL import Image
import random
from datetime import datetime
import gspread
import time

# ==================== 시크릿 설정 ====================
client = OpenAI(api_key=st.secrets["OPENAI_API_KEY"])

def get_gsheet():
    credentials = st.secrets["GSHEET_CREDENTIALS"]
    gc = gspread.service_account_from_dict(credentials)
    sheet = gc.open_by_url(st.secrets["GSHEET_URL"]).sheet1
    return sheet

def log_to_gsheet(user_input, gpt_response, turn):
    sheet = get_gsheet()
    session_duration = int(time.time() - st.session_state.start_time)
    sheet.append_row([
        st.session_state.session_id,
        datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        turn,
        st.session_state.current_topic,
        user_input,
        gpt_response,
        st.session_state.topic_change_count,
        session_duration
    ])

# ==================== 초기 세션 상태 ====================
st.set_page_config(page_title="토론 메이트", page_icon="🗣️", layout="centered")

if "session_id" not in st.session_state:
    st.session_state.session_id = f"session_{datetime.now().strftime('%Y%m%d%H%M%S')}"
if "messages" not in st.session_state:
    st.session_state.messages = []
if "current_topic" not in st.session_state:
    st.session_state.current_topic = None
if "turn_count" not in st.session_state:
    st.session_state.turn_count = 0
if "topic_change_count" not in st.session_state:
    st.session_state.topic_change_count = 0
if "start_time" not in st.session_state:
    st.session_state.start_time = time.time()

# ==================== UI ====================
try:
    service_logo = Image.open("로고1.png")
    st.image(service_logo, width=100)
except:
    st.warning("로고 이미지를 불러올 수 없습니다. '로고1.png' 파일을 확인해주세요.")

st.title("🗣️ 토론 메이트 - 오늘의 주제 한마디")
st.markdown("""
<div style='text-align:center; margin-top:-10px; margin-bottom:30px; font-size:16px; color:#888;'>
흥미로운 사회 주제에 대해 함께 생각해보아요! 💬
</div>
""", unsafe_allow_html=True)

topic_pool = [
    "재택근무, 계속 확대되어야 할까요?",
    "AI 면접 도입, 공정한 채용일까요?",
    "출산 장려 정책, 효과가 있을까요?",
    "기후 변화 대응, 개인의 책임도 클까요?",
    "학벌 중심 사회, 과연 공정한가요?",
]

def pick_new_topic():
    st.session_state.current_topic = random.choice(topic_pool)
    st.session_state.messages = []
    st.session_state.turn_count = 0
    st.session_state.topic_change_count += 1

if not st.session_state.current_topic:
    pick_new_topic()

if not st.session_state.messages:
    intro = f"""안녕하세요, 저는 오늘의 주제를 함께 이야기 나누는 '토론 메이트'예요! 🤖  
🗣️ **오늘의 주제: {st.session_state.current_topic}**  
이 주제에 대해 어떻게 생각하시나요? 찬성/반대 또는 다른 관점에서 자유롭게 이야기해 주세요."""
    st.session_state.messages.append({"role": "assistant", "content": intro})

for msg in st.session_state.messages:
    with st.chat_message(msg["role"], avatar="🤖" if msg["role"] == "assistant" else "🧑"):
        st.markdown(msg["content"])

# 주제 바꾸기 버튼
if st.button("🔄 다른 주제 주세요"):
    pick_new_topic()
    st.rerun()

# ==================== 사용자 입력 처리 ====================
if user_input := st.chat_input("당신의 생각은 어떠신가요?"):
    st.session_state.messages.append({"role": "user", "content": user_input})
    st.session_state.turn_count += 1

    with st.chat_message("user", avatar="🧑"):
        st.markdown(user_input)

    # 시스템 프롬프트 구성
    if st.session_state.turn_count >= 5:
        system_prompt = f"""
        당신은 토론 메이트입니다. 주제는 "{st.session_state.current_topic}"입니다.
        사용자의 기존 발언을 요약하고, 찬반 양쪽 관점을 소개한 후, 다시 의견을 물어보세요.
        """
    else:
        system_prompt = f"""
        당신은 친근하고 논리적인 토론 파트너입니다. 주제는 "{st.session_state.current_topic}"입니다.
        - 사용자의 의견을 요약하거나 존중한 뒤, 반대 시각을 소개하세요.
        - 반드시 하나의 주장(찬성 또는 반대)을 하세요.
        - 5줄 이내로 응답하세요.
        - 마지막에 구체적인 질문을 던지세요.
        """

    # GPT 응답 생성
    with st.chat_message("assistant", avatar="🤖"):
        try:
            stream = client.chat.completions.create(
                model="gpt-3.5-turbo",
                messages=[{"role": "system", "content": system_prompt}] + st.session_state.messages,
                stream=True,
            )
            response = st.write_stream(stream)
        except Exception as e:
            response = f"❌ GPT 호출 중 오류: {str(e)}"
            st.error(response)

    st.session_state.messages.append({"role": "assistant", "content": response})
    log_to_gsheet(user_input, response, st.session_state.turn_count)
