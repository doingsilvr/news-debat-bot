import streamlit as st
from openai import OpenAI
from PIL import Image
import random

# Streamlit 페이지 설정
st.set_page_config(
    page_title="토론 메이트 - 오늘의 주제",
    page_icon="🗣️",
    layout="centered"
)

# 서비스 로고 및 타이틀
service_logo = Image.open("로고.png")  # 로고 파일 경로 맞게 설정
st.image(service_logo, width=100)
st.title("토론 메이트 - 오늘의 주제 한마디")
st.markdown("""
<div style="text-align:center; margin-top:-10px; margin-bottom:30px; font-size:16px; color:#bbb;">
    흥미로운 사회 주제에 대해 함께 생각해보고 이야기 나눠보아요. 🧠
</div>
""", unsafe_allow_html=True)

# 초기화
client = OpenAI(api_key=st.secrets["OPENAI_API_KEY"])

if "openai_model" not in st.session_state:
    st.session_state["openai_model"] = "gpt-3.5-turbo"

if "messages" not in st.session_state:
    st.session_state.messages = []

if "current_topic" not in st.session_state:
    st.session_state.current_topic = None

if "turn_count" not in st.session_state:
    st.session_state.turn_count = 0

# 주제 후보
topic_pool = [
    "재택근무, 계속 확대되어야 할까요?",
    "AI 면접 도입, 공정한 채용일까요?",
    "출산 장려 정책, 효과가 있을까요?",
    "기후 변화 대응, 개인의 책임도 클까요?",
    "학벌 중심 사회, 과연 공정한가요?",
]

# 주제 생성 함수
def pick_new_topic():
    st.session_state.current_topic = random.choice(topic_pool)
    st.session_state.messages = []
    st.session_state.turn_count = 0

# 주제 없으면 초기화
if not st.session_state.current_topic:
    pick_new_topic()

# 주제 소개 메시지
if not st.session_state.messages:
    greeting = f"안녕하세요, 저는 오늘의 주제를 함께 이야기 나누는 '토론 메이트'예요! 🤖\n\n🗣️ **오늘의 주제: {st.session_state.current_topic}**\n\n이 주제에 대해 어떻게 생각하시나요? 찬성/반대 또는 다른 관점에서 자유롭게 이야기해 주세요."
    st.session_state.messages.append({"role": "assistant", "content": greeting})

# 과거 메시지 출력
for msg in st.session_state.messages:
    with st.chat_message(msg["role"], avatar="🤖" if msg["role"] == "assistant" else "🧑"):
        st.markdown(msg["content"])

# 주제 전환 버튼
if st.button("🔄 다른 주제 주세요"):
    pick_new_topic()
    st.rerun()

# 사용자 입력
if user_input := st.chat_input("당신의 생각은 어떠신가요?"):
    st.session_state.messages.append({"role": "user", "content": user_input})
    st.session_state.turn_count += 1

    with st.chat_message("user", avatar="🧑"):
        st.markdown(user_input)

    # 요약 추가 여부 판단
    if st.session_state.turn_count >= 5:
        system_content = f"""
        당신은 뉴스 토론 메이트입니다. 현재 주제는 "{st.session_state.current_topic}"입니다.
        지금까지의 대화 내용을 요약하고, 다양한 의견을 소개하고, 사용자의 시각을 한 번 더 구체적으로 묻는 방식으로 이어가세요.
        반드시 현재 주제를 유지하고, 대화를 정리하려 들지 마세요.
        """
    else:
        system_content = f"""
        당신은 친근하고 논리적인 토론 파트너입니다. 현재 주제는 "{st.session_state.current_topic}"입니다.
        사용자의 의견을 받아들이되, 반대되는 시각이나 추가로 고려해볼 만한 논점을 제시한 뒤,
        "당신은 이 중 어떤 시각에 더 공감하시나요?", "혹시 비슷한 경험이 있으신가요?" 같이 구체적으로 질문해 주세요.
        """

    with st.chat_message("assistant", avatar="🤖"):
        stream = client.chat.completions.create(
            model=st.session_state["openai_model"],
            messages=[{"role": "system", "content": system_content}] + st.session_state.messages,
            stream=True,
        )
        response = st.write_stream(stream)

    st.session_state.messages.append({"role": "assistant", "content": response})
