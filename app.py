import streamlit as st
import time
import random
import re

# =========================================================
# 기본 설정
# =========================================================
st.set_page_config(page_title="AI 쇼핑 에이전트", page_icon="🎧", layout="wide")

# -----------------------------
# 세션 상태
# -----------------------------
def ss_init():
    ss = st.session_state
    ss.setdefault("nickname", None)
    ss.setdefault("page", "onboarding")      # onboarding -> chat
    ss.setdefault("stage", "explore")        # explore -> summary -> comparison
    ss.setdefault("messages", [])
    ss.setdefault("memory", [])              # list[str]
    ss.setdefault("last_intent", None)       # to reduce repetitive ask
    ss.setdefault("summary_text", "")
    ss.setdefault("wants_recommend", False)  # 버튼 클릭 여부
    ss.setdefault("just_updated_memory", False)
    # (7) 두 번째 고정 멘트 제어용 플래그
    ss.setdefault("fixed_second_done", False)
    # 요약 전 최우선 기준 입력 대기 상태
    ss.setdefault("await_priority_choice", False)

ss_init()

# =========================================================
# 유틸: 자연화/정제
# =========================================================
def naturalize_memory(text: str) -> str:
    """메모리 문장을 사용자 1인칭 자연어로 다듬기."""
    t = text.strip()
    # 키워드성 변형
    t = t.replace("노이즈 캔슬링", "노이즈캔슬링")
    # 끝맺음 통일
    if t.endswith(("다", "다.")):
        t = t.rstrip(".")
        if any(kw in t for kw in ["중요", "중시", "중요시", "우선"]):
            t = t + "고 있어요."
        elif "이내" in t or "이상" in t or "정도" in t:
            t = t + "로 생각하고 있어요."
        else:
            t = t + "이에요."
    # 흔한 패턴 스무딩
    t = t.replace("선호한다고", "선호한다고").replace("생각한고", "생각하고")
    t = t.replace("이내다", "이내로 생각하고 있어요")
    # 문장 끝 보정
    if not t.endswith(("요.", "다.", "요")):
        if t.endswith("요"):
            t += "."
        else:
            t += " "
    return t

# ---- (4) 한 문장 내 다중 기준 인식 지원 ----
def _clause_split(u: str) -> list[str]:
    # 그리고/랑/및/하고/고/,&/,/· 등 연결사를 쉼표로 치환 후 분할
    repl = re.sub(r"(그리고|랑|및|하고|고|\&|·)", ",", u)
    parts = [p.strip() for p in re.split(r"[，,]", repl) if p.strip()]
    return parts if parts else [u.strip()]

def memory_sentences_from_user_text(utter: str) -> list[str] | None:
    """
    사용자 발화에서 복수의 쇼핑 기준/맥락을 추출.
    - 키워드 규칙
    - 스타일/디자인/무게/휴대성 확장
    - '~하면 좋겠어/~가 좋아/~선호/~필요해/~중요해' 패턴 반영
    - 예산/브랜드/색상
    """
    u = utter.strip().replace("  ", " ")
    mems = []

    # 1) 예산(문장 전체에서 1회만)
    m = re.search(r"(\d+)\s*만\s*원", u)
    if m:
        price = m.group(1)
        mems.append(f"예산은 약 {price}만 원 이내로 생각하고 있어요.")

    # 2) 브랜드(전역 탐색)
    brands = ["Sony", "BOSE", "Bose", "JBL", "Apple", "Anker", "Soundcore", "Sennheiser", "AKG"]
    for b in brands:
        if b.lower() in u.lower():
            mems.append(f"{b} 브랜드에 관심이 있어요.")
            break

    # 3) 색상 단답
    single = u.replace("색", "").strip()
    if single in ["블랙", "검정"]:
        mems.append("블랙 색상을 선호하고 있어요.")
    elif single in ["화이트", "하양", "하얀", "화이트색"]:
        mems.append("화이트 색상을 선호하고 있어요.")
    elif single in ["파랑", "파란색", "파랑색", "블루"]:
        mems.append("블루 색상을 선호하고 있어요.")
    elif single in ["그레이", "회색", "스페이스 그레이", "스페이스그레이"]:
        mems.append("그레이 색상을 선호하고 있어요.")

    # 4) 절(clause)별 키워드 규칙
    clauses = _clause_split(u)
    for c in clauses:
        # 기본 규칙
        base_rules = [
            ("노이즈캔슬링", "노이즈캔슬링 기능을 고려하고 있어요."),
            ("ANC", "노이즈캔슬링 기능을 고려하고 있어요."),
            ("가볍", "가벼운 착용감을 선호하고 있어요."),
            ("무겁지", "가벼운 착용감을 선호하고 있어요."),
            ("무겁다", "가벼운 착용감을 선호하고 있어요."),
            ("착용감", "착용감을 중요하게 생각하고 있어요."),
            ("음질", "음질을 중요하게 생각하고 있어요."),
            ("사운드", "음질을 중요하게 생각하고 있어요."),
            ("통화", "통화 품질도 고려하고 있어요."),
            ("배터리", "배터리 지속시간이 긴 제품을 선호하고 있어요."),
            ("출퇴근", "출퇴근길에 사용할 예정이에요."),
            ("등하교", "등하교/이동 중에 사용할 예정이에요."),
            ("버스", "이동 환경(대중교통)에서 사용할 예정이에요."),
        ]
        # 디자인/스타일/미적 선호 확장
        design_keys = [
            "예쁘", "이쁘", "유행", "스타일리시", "스타일리쉬", "스타일리시하다", "스타일리쉬하다", "깔끔",
            "세련", "쿨하", "귀엽", "멋있", "감성", "디자인"
        ]
        weight_mobility_keys = ["가벼워", "무거워", "가벼운", "들고 다니기 편", "휴대성", "휴대하기 편"]

        matched = False
        for key, sent in base_rules:
            if key in c:
                mems.append(sent)
                matched = True

        if any(k in c for k in design_keys):
            mems.append("디자인/스타일을 중요하게 생각하고 있어요.")
            matched = True

        if any(k in c for k in weight_mobility_keys):
            mems.append("가벼움과 휴대성을 중요하게 생각하고 있어요.")
            matched = True

        # 자유형 패턴: ~하면 좋겠어/~가 좋아/~선호/~필요해/~중요해
        if re.search(r"(하면 좋겠|좋겠어|가 좋아|선호|필요해|중요해)", c):
            mems.append(c.strip() + "로 생각하고 있어요.")
            matched = True

    # 중복 제거(포함관계 기준)
    dedup = []
    for m in mems:
        if not any(m in x or x in m for x in dedup):
            dedup.append(m)
    return dedup if dedup else None

def add_memory(mem_text: str, announce=True):
    mem_text = mem_text.strip()
    if not mem_text:
        return
    # 중복 방지(간단 포함 체크)
    for m in st.session_state.memory:
        if mem_text in m or m in mem_text:
            return
    st.session_state.memory.append(mem_text)
    st.session_state.just_updated_memory = True
    if announce:
        st.toast("🧩 메모리에 추가했어요. (왼쪽 사이드바 메모리 제어창에서 수정/삭제 가능)", icon="📝")
        time.sleep(3)

def delete_memory(idx: int):
    if 0 <= idx < len(st.session_state.memory):
        # ✅ 삭제 전 내용 저장
        deleted = st.session_state.memory[idx]

        # 실제 삭제
        del st.session_state.memory[idx]
        st.session_state.just_updated_memory = True

        # ✅ 삭제 안내 (시간 3배 길게)
        st.toast("🧹 메모리에서 삭제했어요.", icon="🧽")
        time.sleep(3)

        # ✅ [추가] ‘가장 중요한 기준’ 삭제 감지 → 재선택 안내
        if "(가장 중요)" in deleted:
            ai_say("⚠️ 현재 가장 중요한 기준이 삭제되었어요. 다른 기준 중 하나를 새로 지정하시겠어요?")
            
            # 남아 있는 기준들 중에서 선택지 제시
            if st.session_state.memory:
                options = [m.split(" ")[0] for m in st.session_state.memory if m]
                ai_say("👉 가능한 선택: " + ", ".join(options))
                st.session_state.await_priority_choice = True
                st.session_state.stage = "explore"


def update_memory(idx: int, new_text: str):
    if 0 <= idx < len(st.session_state.memory):
        st.session_state.memory[idx] = new_text.strip()
        st.session_state.just_updated_memory = True
        st.toast("🧩 메모리가 업데이트되었어요.", icon="🔄")
        time.sleep(3)

# =========================================================
# 요약/추천
# =========================================================
def detect_priority(mem_list):
    # ‘(가장 중요)’가 붙은 항목이 있으면 그 문구에서 라벨 제거 후 그대로 사용
    for m in mem_list:
        if "(가장 중요)" in m:
            return m.replace("(가장 중요)", "").strip()
    # 키워드 힌트
    for m in reversed(mem_list):
        for key in ["가장 중요", "우선", "최우선", "무엇보다", "제일"]:
            if key in m:
                if "착용감" in m: return "착용감"
                if "음질" in m: return "음질"
                if "가격" in m or "예산" in m: return "가격"
                if "노이즈캔슬링" in m: return "노이즈캔슬링"
                if "디자인" in m or "스타일" in m: return "디자인/스타일"

    for m in st.session_state.memory:
        if ("가격" in mem_text and "예산" in m) or ("예산" in mem_text and "가격" in m):
            return  # 의미상 중복 방지

    # fallback
    for cand in ["디자인", "스타일", "음질", "착용감", "가격", "노이즈캔슬링", "배터리"]:
        if any(cand in x for x in mem_list):
            return "디자인/스타일" if cand in ["디자인", "스타일"] else cand
    return None

def generate_summary(name, mems):
    if not mems:
        return ""
    lines = []
    for m in mems:
        lines.append(f"- {naturalize_memory(m)}")
    prio = detect_priority(mems)
    header = f"[@{name}님의 메모리 요약_지금 나의 쇼핑 기준은?]\n\n"
    if st.session_state.just_updated_memory:
        body = "업데이트된 메모리를 바탕으로 " + name + "님이 중요하게 생각하신 기준을 다시 정리해봤어요:\n\n"
    else:
        body = "지금까지 대화를 바탕으로 " + name + "님이 헤드셋을 고를 때 중요하게 생각하신 기준을 정리해봤어요:\n\n"
    body += "\n".join(lines) + "\n"
    if prio:
        body += f"\n그중에서도 가장 중요한 기준은 **‘{prio}’**이에요.\n"
    tail = (
        "\n제가 정리한 기준이 맞을까요? 왼쪽 사이드바 메모리 제어창에서 언제든 수정할 수 있어요.\n"
        "변경이 없다면 아래 버튼을 눌러 추천을 받아보세요 👇"
    )
    return header + body + tail

# 간이 카탈로그 (예시 데이터)
CATALOG = [
    {
        "name": "Anker Soundcore Q45", "brand": "Anker",
        "price": 179000, "rating": 4.4, "reviews": 1600, "rank": 8,
        "tags": ["가성비", "배터리", "노이즈캔슬링", "편안함"],
        "review_one": "가격 대비 성능이 훌륭하고 배터리가 길어요.",
        "color": ["블랙", "네이비"]
    },
    {
        "name": "JBL Tune 770NC", "brand": "JBL",
        "price": 129000, "rating": 4.4, "reviews": 2300, "rank": 9,
        "tags": ["가벼움", "균형형 음질", "노이즈캔슬링"],
        "review_one": "가볍고 음색이 밝다는 평이 많아요.",
        "color": ["블랙", "화이트"]
    },
    {
        "name": "Sony WH-CH720N", "brand": "Sony",
        "price": 169000, "rating": 4.5, "reviews": 2100, "rank": 6,
        "tags": ["노이즈캔슬링", "경량", "무난한 음질"],
        "review_one": "경량이라 출퇴근용으로 좋다는 후기가 많아요.",
        "color": ["블랙", "화이트", "블루"]
    },
    {
        "name": "Bose QC45", "brand": "Bose",
        "price": 420000, "rating": 4.7, "reviews": 2800, "rank": 2,
        "tags": ["최상급 착용감", "자연스러운 사운드", "노이즈캔슬링"],
        "review_one": "장시간 써도 귀가 편하다는 리뷰가 많아요.",
        "color": ["블랙", "화이트"]
    },
    {
        "name": "Sony WH-1000XM5", "brand": "Sony",
        "price": 450000, "rating": 4.8, "reviews": 3200, "rank": 1,
        "tags": ["최상급 노캔", "균형 음질", "플래그십"],
        "review_one": "소음 많은 환경에서 확실히 조용해진다는 평가.",
        "color": ["블랙", "화이트"]
    },
    {
        "name": "Apple AirPods Max", "brand": "Apple",
        "price": 679000, "rating": 4.6, "reviews": 1500, "rank": 3,
        "tags": ["프리미엄", "노이즈캔슬링", "디자인"],
        "review_one": "디자인과 브랜드 감성 때문에 만족도가 높아요.",
        "color": ["실버", "스페이스그레이"]
    },
]

def extract_budget(mems):
    for m in mems:
        mm = re.search(r"약\s*([0-9]+)\s*만\s*원\s*이내", m)
        if mm:
            return int(mm.group(1)) * 10000
        mm2 = re.search(r"([0-9]+)\s*만\s*원\s*이내", m)
        if mm2:
            return int(mm2.group(1)) * 10000
    return None

def prefers_color(mems):
    if any("화이트" in x for x in mems): return "화이트"
    if any("블랙" in x for x in mems): return "블랙"
    if any("블루" in x for x in mems): return "블루"
    return None

def prefers_brand(mems):
    brands = ["Sony", "Bose", "JBL", "Anker", "Apple", "Sennheiser", "AKG"]
    for b in brands:
        if any(b in x for x in mems):
            return b
    return None

def _brief_feature_from_item(c):
    # 2번째 이미지 스타일의 '특징' 생성 규칙
    if "가성비" in c["tags"]:
        return "가성비 인기"
    if c["rank"] <= 3:
        return "이달 판매 상위"
    if "최상급" in " ".join(c["tags"]):
        return "프리미엄 추천"
    if "디자인" in " ".join(c["tags"]):
        return "디자인 강점"
    return "실속형 추천"

# ---- (1) 추천 3개 보장: 단계적 완화 + 보충 ----
def filter_products():
    mem = " ".join(st.session_state.memory)
    budget = extract_budget(st.session_state.memory)
    # ✅ 수정된 필터링 로직
    if strict_budget:
        # 가격이 가장 중요한 경우 → 예산 이내 제품만 추천
        cands = [c for c in CATALOG if (not budget) or c["price"] <= budget]
    else:
        # 일반적인 경우 → 약간의 여유 (예산 * 1.3)까지 허용
        cands = [c for c in CATALOG if (not budget) or c["price"] <= budget or c["price"] <= (budget * 1.3)]


    # ✅ 추가: '가격' 또는 '예산'이 최우선 기준이면 strict 모드 적용
    prio = detect_priority(st.session_state.memory)
    strict_budget = prio and ("가격" in prio or "예산" in prio)

    # 1차: 예산 내(또는 1.3배 허용)
    cands = [c for c in CATALOG if (not budget) or c["price"] <= budget or c["price"] <= (budget * 1.3)]
    # 점수 함수 (디자인/무게/노캔/브랜드 가중)
    def score(c):
        s = c["rating"]
        # 취향 가중
        if "노이즈캔슬링" in mem and "노이즈캔슬링" in " ".join(c["tags"]): s += 1.5
        if ("가벼움" in mem or "가벼운" in mem or "휴대성" in mem) and (("가벼움" in " ".join(c["tags"])) or ("경량" in " ".join(c["tags"]))): s += 1.3
        if ("디자인" in mem or "스타일" in mem) and ("디자인" in " ".join(c["tags"])): s += 1.2
        if "음질" in mem and ("균형" in " ".join(c["tags"]) or "사운드" in " ".join(c["tags"])): s += 0.8
        # 브랜드 힌트(경향성)
        if "디자인" in mem and c["brand"] in ["Apple", "Sony", "Bose"]: s += 0.4
        # 인기/순위 보너스
        s += max(0, 10 - c["rank"])
        return s

    cands.sort(key=score, reverse=True)

    # 보장: 3개 미만이면 단계적으로 풀어가며 채우기
    if len(cands) < 3:
        # 2차: 예산 *1.6까지 확대
        extra = [c for c in CATALOG if c not in cands and budget and c["price"] <= budget * 1.6]
        extra.sort(key=score, reverse=True)
        cands += extra
    if len(cands) < 3:
        # 3차: 전체에서 남은 것 채우기(점수순)
        remain = [c for c in CATALOG if c not in cands]
        remain.sort(key=score, reverse=True)
        cands += remain

    return cands[:3]

def recommend_products(name, mems):
    products = filter_products()
    blocks = []
    for c in products:
        block = (
            f"모델명: {c['name']}\n"
            f"브랜드: {c['brand']}\n"
            f"가격: {c['price']:,}원\n\n"
            f"평점: {c['rating']:.1f} / 리뷰 수: {c['reviews']}개\n\n"
            f"리뷰 한줄요약: {c['review_one']}\n\n"
            f"특징: {_brief_feature_from_item(c)}"
        )
        blocks.append(block)
    header = "🎯 추천 제품 3가지\n\n"
    tail = "\n\n궁금한 제품을 골라 물어보셔도 좋아요. 조건을 바꾸면 추천도 함께 바뀝니다."
    return header + "\n\n---\n\n".join(blocks) + tail

# =========================================================
# 온보딩
# =========================================================
def onboarding():
    st.title("🎧 AI 쇼핑 에이전트")
    st.caption("실험용 환경 - 대화를 통해 취향을 반영하는 사용자 개인형 에이전트로, 블루투스 헤드셋에 대한 추천을 도와드리고 있어요.")
    st.markdown("**이름을 적어주세요. 단, 설문 응답 칸에도 동일하게 적어주셔야 보상을 받을 수 있습니다.** *(성 포함/띄어쓰기 주의)*")
    nick = st.text_input("이름 입력", placeholder="예: 홍길동")
    if st.button("시작하기"):
        if not nick.strip():
            st.warning("이름을 입력해 주세요.")
            return
        st.session_state.nickname = nick.strip()
        st.session_state.page = "chat"
        st.rerun()

# =========================================================
# 왼쪽 사이드바 메모리 제어창
# =========================================================
def top_memory_panel():
    st.subheader("🧠 현재까지 기억된 메모리 정보(메모리 자유 편집·삭제·추가 가능)")
    if len(st.session_state.memory) == 0:
        st.caption("아직 파악된 정보가 없습니다.")
    else:
        for i, item in enumerate(st.session_state.memory):
            cols = st.columns([6,1])
            with cols[0]:
                st.text_input(
                    f"메모리 {i+1}", item, key=f"mem_edit_{i}",
                    on_change=update_memory, args=(i, st.session_state.get(f"mem_edit_{i}", item))
                )
            with cols[1]:
                if st.button("삭제", key=f"del_{i}"):
                    delete_memory(i)
                    # 요약/비교 단계라면 요약 재생성 + 새 메시지로 재출력
                    if st.session_state.stage in ("summary", "comparison"):
                        st.session_state.summary_text = generate_summary(st.session_state.nickname, st.session_state.memory)
                        st.toast("🧩 메모리를 반영해 요약을 갱신했어요.", icon="✅")
                        time.sleep(0.2)
                        ai_say(st.session_state.summary_text)
                    st.rerun()

    # ✅ placeholder만 사용 → 예시 문구 자동 저장 방지
    new_mem = st.text_input("새 메모리 추가", placeholder="예: 음질이 중요해요 / 블랙 색상을 선호해요")
    if st.button("추가"):
        if new_mem.strip():
            add_memory(new_mem.strip(), announce=True)
            if st.session_state.stage in ("summary", "comparison"):
                st.session_state.summary_text = generate_summary(st.session_state.nickname, st.session_state.memory)
                st.toast("🧩 메모리를 반영해 요약을 갱신했어요.", icon="✅")
                time.sleep(0.2)
                ai_say(st.session_state.summary_text)
            st.rerun()

# =========================================================
# 대화 흐름
# =========================================================
ASK_VARIANTS = [
    "좋아요. 그 외에 제가 기억해두면 좋을 조건이 있을까요? (예: 브랜드, 기능, 착용감 등)",
    "혹시 추가로 고려하실 조건이 있을까요? (브랜드/착용감/노이즈캔슬링 등)",
    "다른 기준도 말씀해 주실 수 있을까요? (예: 배터리, 색상, 무게 등)", "추가로 고려할 기준이 또 있을까요?"
]

FOLLOW_CONTEXT = [
    "어떤 용도로 사용하실 예정인가요?",
    "사용 상황(이동/실내/운동 등)에서 무엇이 더 중요할까요?",
]

FOLLOW_UPS_AFTER_ADD = [
    "좋아요 🙂 방금 말씀하신 내용을 메모리에 추가했어요. (왼쪽 사이드바 메모리 제어창에서 수정·삭제 가능해요.) 이어서 추가로 고려하실 조건이 또 있을까요?(예 : 색상, 음질, 착용감 등 )",
    "반영 완료했습니다! 🙂 이어서 꼭 반영하고 싶은 기준이 또 있을까요?",
    "기억해 둘게요. 다음으로 어떤 점을 더 고려하면 좋을까요? (예: 배터리, 음질, 색상 등)"
]

def ai_say(text):
    st.session_state.messages.append({"role": "assistant", "content": text})

def user_say(text):
    st.session_state.messages.append({"role": "user", "content": text})

def handle_user_input(user_input: str):
    # (최우선 기준 대기 상태)
    if st.session_state.await_priority_choice and st.session_state.stage == "explore":
        st.session_state.memory.append(user_input.strip() + " (가장 중요)")
        st.session_state.just_updated_memory = True
        ai_say("🌟 가장 중요한 기준으로 반영했어요. 요약을 정리해 드릴게요.")
        time.sleep(0.2)
        st.session_state.await_priority_choice = False
        st.session_state.stage = "summary"
        return

    # 1) 메모리 추출/추가 — 복수 기준 처리
    mems = memory_sentences_from_user_text(user_input)
    if mems:
        for m in mems:
            add_memory(m, announce=True)
        # 추가 직후 후속 멘트 1개
        ai_say(random.choice(FOLLOW_UPS_AFTER_ADD))
  # ✅ [여기 추가] 새 기준(처음 등장한 항목) 감지 후 세부 질문 유도
        for m in mems:
            if "디자인" in m and not any("디자인" in x for x in st.session_state.memory[:-1]):
                ai_say("디자인이 중요하시군요! 😊 디자인 중에서는 어떤 부분이 특히 중요할까요? (예: 색상 등)")
            elif "브랜드" in m and not any("브랜드" in x for x in st.session_state.memory[:-1]):
                ai_say("특정 브랜드를 선호하신다면 알려주세요. (예: Sony, Bose, Apple 등)")
            elif "착용감" in m and not any("착용감" in x for x in st.session_state.memory[:-1]):
                ai_say("착용감 중에서는 어떤 부분을 더 중시하시나요? (예: 장시간 착용, 귀압, 무게 등)")
        
        # 메모리 3개 이상이면 요약 전에 최우선 기준 요청
        if st.session_state.stage == "explore" and len(st.session_state.memory) >= 3:
            ai_say("좋습니다! 마지막으로 가장 중요한 기준 하나만 콕 집어주세요.")
            st.session_state.await_priority_choice = True
            return
        return

    # 2) 종료/다음단계 트리거 단어
    if any(k in user_input for k in ["없어", "그만", "끝", "충분", "추천해줘", "추천", "OK", "ok"]):
        if st.session_state.stage == "explore" and len(st.session_state.memory) >= 3:
            ai_say("좋습니다! 마지막으로 가장 중요한 기준 하나만 콕 집어주세요.")
            st.session_state.await_priority_choice = True
            return
        st.session_state.stage = "summary"

    # 3) 질문 설계 (중복방지)
    if st.session_state.stage == "explore":
        # 두 번째 AI 멘트는 고정 출력
        assistant_count = sum(1 for m in st.session_state.messages if m["role"] == "assistant")
        if (assistant_count == 1) and (not st.session_state.fixed_second_done):
            ai_say("그렇다면 주로 사용하게 될 상황에서는 어떤 점이 더 중요할까요? (예: 외부라면 노이즈캔슬링 등)")
            st.session_state.fixed_second_done = True
            st.session_state.last_intent = "context"
            return

        # 예산 질문(한 번)
        if extract_budget(st.session_state.memory) is None and st.session_state.last_intent != "budget":
            ai_say("추천으로 넘어가기 전에, 예산은 어느 정도로 생각하고 계세요? (예: 10만 원대, 15만 원 이하)")
            st.session_state.last_intent = "budget"
            return

        # 3개 미만이면 추가 탐색, 이상이면 최우선 질문 먼저
        if len(st.session_state.memory) < 3:
            if st.session_state.last_intent != "context":
                ai_say(random.choice(FOLLOW_CONTEXT))
                st.session_state.last_intent = "context"
            else:
                ai_say(random.choice(ASK_VARIANTS))
                st.session_state.last_intent = "criterion"
        else:
            ai_say("좋습니다! 마지막으로 가장 중요한 기준 하나만 콕 집어주세요.")
            st.session_state.await_priority_choice = True
            # stage는 explore 유지

def summary_step():
    st.session_state.summary_text = generate_summary(st.session_state.nickname, st.session_state.memory)
    ai_say(st.session_state.summary_text)

def comparison_step():
    rec = recommend_products(st.session_state.nickname, st.session_state.memory)
    ai_say(rec)

# =========================================================
# 채팅 UI
# =========================================================
def chat_interface():
    st.title("🎧 AI 쇼핑 에이전트")
    st.caption("실험용 환경 - 대화를 통해 취향을 반영하는 사용자 개인형 에이전트입니다.")

    # 왼쪽 사이드바에 메모리 제어창
    with st.sidebar:
        top_memory_panel()

    # 첫 인사(에이전트가 시작)
    if not st.session_state.messages:
        ai_say(f"안녕하세요 {st.session_state.nickname}님! 😊 저는 당신의 AI 쇼핑 도우미예요. "
               "대화를 통해 기준을 기억하며 블루투스 헤드셋을 함께 찾아볼게요. "
               "우선, 어떤 용도로 사용하실 예정인가요?")

    # 메시지 렌더
    for msg in st.session_state.messages:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])

    # 요약 단계 진입 시 요약 + 버튼
    if st.session_state.stage == "summary":
        # 이미 요약이 없다면 만든다(중복 방지)
        if not any("메모리 요약" in m["content"] for m in st.session_state.messages if m["role"]=="assistant"):
            summary_step()
        with st.chat_message("assistant"):
            st.markdown(st.session_state.summary_text)
            if st.button("🔍 추천 시작하기"):
                st.session_state.stage = "comparison"
                comparison_step()
                st.rerun()

    # 비교 단계에서는 추천이 노출됨
    if st.session_state.stage == "comparison":
        # 추천이 없다면 생성
        if not any("🎯 추천 제품 3가지" in m["content"] for m in st.session_state.messages if m["role"]=="assistant"):
            comparison_step()

    # 사용자 입력
    user_input = st.chat_input("메시지를 입력하세요.")
    if user_input:
        user_say(user_input)
        handle_user_input(user_input)
        # 요약/비교 단계에서 메모리 변동이 있으면 요약 갱신 + 새 메시지로 재출력
        if st.session_state.just_updated_memory and st.session_state.stage in ("summary", "comparison"):
            st.session_state.summary_text = generate_summary(st.session_state.nickname, st.session_state.memory)
            st.toast("🧩 메모리를 반영해 요약을 갱신했어요.", icon="✅")
            time.sleep(0.2)
            ai_say(st.session_state.summary_text)
            st.session_state.just_updated_memory = False
        st.rerun()

# =========================================================
# 라우팅
# =========================================================
def onboarding():
    st.title("🎧 AI 쇼핑 에이전트")
    st.caption("실험용 환경 - 대화를 통해 취향을 반영하는 사용자 개인형 에이전트로 블루투스 헤드셋에 대한 추천을 도와드리고 있어요.")
    st.markdown("**이름을 적어주세요. 단, 설문 응답 칸에도 동일하게 적어주셔야 보상을 받을 수 있습니다.** *(성 포함/띄어쓰기 주의)*")
    nick = st.text_input("이름 입력", placeholder="예: 홍길동")
    if st.button("시작하기"):
        if not nick.strip():
            st.warning("이름을 입력해 주세요.")
            return
        st.session_state.nickname = nick.strip()
        st.session_state.page = "chat"
        st.rerun()

if st.session_state.page == "onboarding":
    onboarding()
else:
    chat_interface()
