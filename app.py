import json
import os
import re
from io import StringIO
from typing import Any, Dict, List, Tuple

import pandas as pd
import streamlit as st

try:
    from openai import OpenAI
except Exception:
    OpenAI = None

st.set_page_config(page_title="AI Translation QA Review Dashboard", page_icon="🧪", layout="wide")

st.markdown("""
<style>
.main {background-color: #FAFAFC;}
.block-container {padding-top: 2rem; padding-bottom: 3rem;}
.metric-card {background: white; border: 1px solid #E8E8EF; border-radius: 18px; padding: 18px 20px; box-shadow: 0 2px 10px rgba(27,31,44,.04);}
.small-label {color:#6B7280; font-size:.88rem;}
.big-number {font-size:2rem; font-weight:800; color:#4F35E8;}
.insight-box {background:#F3F0FF; border:1px solid #D8D0FF; border-radius:16px; padding:18px 22px; margin-top:12px;}
.step {background:white; border:1px solid #E8E8EF; border-radius:18px; padding:18px; text-align:center; min-height:125px;}
.arrow {font-size:2rem; color:#9CA3AF; text-align:center; padding-top:35px;}
</style>
""", unsafe_allow_html=True)

st.title("AI 번역 평가 결과 검수 자동화 PoC")
st.caption("Gemini가 탐지한 번역 오류 중 허위 오류(false positive)를 Rule Check와 LLM Fact Check로 분류하는 운영자용 QA Dashboard")

with st.expander("이 PoC의 목적", expanded=True):
    st.markdown("""
기존 번역 품질 평가 프로세스에서는 **AI가 탐지한 오류를 사람이 다시 검수**해야 했습니다.

이 PoC는 사람이 반복적으로 확인하던 검수 업무를 줄이기 위해 다음 두 단계를 적용합니다.

1. **Rule Check**: `marked_text`가 실제 번역문에 존재하는지 코드로 확인
2. **LLM Fact Check**: 표현이 존재하는 경우에만, 오류 지적이 문법·맥락상 실제로 타당한지 확인
""")

st.markdown("### 1. 기존 업무 프로세스와 개선 프로세스")
c1, a1, c2, a2, c3, a3, c4 = st.columns([1.2, .25, 1.2, .25, 1.2, .25, 1.2])
with c1:
    st.markdown('<div class="step"><b>HCX 번역</b><br><br><span class="small-label">한국어 원문을 영어로 번역</span></div>', unsafe_allow_html=True)
with a1:
    st.markdown('<div class="arrow">→</div>', unsafe_allow_html=True)
with c2:
    st.markdown('<div class="step"><b>Gemini 평가</b><br><br><span class="small-label">오류 후보를 JSON으로 출력</span></div>', unsafe_allow_html=True)
with a2:
    st.markdown('<div class="arrow">→</div>', unsafe_allow_html=True)
with c3:
    st.markdown('<div class="step"><b>자동 검수</b><br><br><span class="small-label">Rule Check + LLM Fact Check</span></div>', unsafe_allow_html=True)
with a3:
    st.markdown('<div class="arrow">→</div>', unsafe_allow_html=True)
with c4:
    st.markdown('<div class="step"><b>사람 최종 확인</b><br><br><span class="small-label">허위 오류 제거 후 정리</span></div>', unsafe_allow_html=True)

st.divider()
st.markdown("### 2. 파일 업로드")
st.write("CSV에는 `segment_id`, `source`, `translation` 컬럼이 필요합니다. JSON에는 Gemini 평가 결과가 들어갑니다.")

left, right = st.columns(2)
with left:
    csv_file = st.file_uploader("HCX 번역 결과 CSV 업로드", type=["csv"])
with right:
    json_file = st.file_uploader("Gemini 평가 결과 JSON 업로드", type=["json"])

use_sample = st.toggle("샘플 데이터로 테스트하기", value=True)

sample_csv = """segment_id,source,translation
1,2024년 2월 이후 물가는 안정세를 보였다.,Since February 2024, inflation has shown signs of stabilization.
2,상반기에는 MMF 수신의 큰 폭 증가로 단기자금 운용 규모가 확대되었다.,"In the first half of the year, short-term fund operations expanded due to a substantial increase in MMF deposits."
3,지난해 12월 이후 미 국채금리는 큰 폭 하락하였다.,"Since December last year, U.S. Treasury yields have fallen significantly."
4,상품수지는 흑자를 지속하였다.,The goods account continued to post a surplus.
7,중소 지역은행의 유동성 리스크가 확대되었다.,Liquidity risks among small and medium-sized regional banks increased.
"""

sample_json = [
    {"segment_id": 1, "errors": [{"category": "Accuracy", "subtype": "Meaning Accuracy", "severity": "Minor", "marked_text": "since February 2024", "note": "해당 표현은 원문의 기간 표현을 과도하게 특정함"}]},
    {"segment_id": 2, "errors": [{"category": "Accuracy", "subtype": "Meaning Accuracy", "severity": "Minor", "marked_text": "rapidly", "note": "rapidly라는 과장된 표현이 사용되어 원문의 의미를 왜곡함"}]},
    {"segment_id": 3, "errors": [{"category": "Style", "subtype": "Awkward Expression", "severity": "Minor", "marked_text": "since December last year", "note": "지난해 12월 이후는 since가 아니라 in December로 번역해야 함"}]},
    {"segment_id": 4, "errors": [{"category": "Terminology", "subtype": "Term Choice", "severity": "Major", "marked_text": "goods trade", "note": "상품수지는 goods trade로 번역해야 함"}]},
    {"segment_id": 7, "errors": [{"category": "Terminology", "subtype": "Term Choice", "severity": "Major", "marked_text": "medium and small regional banks", "note": "중소 지역은행은 medium and small regional banks로 번역해야 함"}]},
]

def normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip().lower()

def load_translation_df() -> pd.DataFrame:
    if use_sample:
        return pd.read_csv(StringIO(sample_csv))
    if csv_file is None:
        return pd.DataFrame(columns=["segment_id", "source", "translation"])
    return pd.read_csv(csv_file)

def load_eval_json() -> List[Dict[str, Any]]:
    if use_sample:
        return sample_json
    if json_file is None:
        return []
    return json.load(json_file)

def flatten_errors(eval_data: List[Dict[str, Any]], translation_df: pd.DataFrame) -> pd.DataFrame:
    records = []
    translation_lookup = {str(row.get("segment_id")): row.get("translation", "") for _, row in translation_df.iterrows()}
    source_lookup = {str(row.get("segment_id")): row.get("source", "") for _, row in translation_df.iterrows()}

    for item in eval_data:
        sid = str(item.get("segment_id"))
        for err in item.get("errors", []):
            marked_text = err.get("marked_text", "")
            translation = translation_lookup.get(sid, "")
            exists = normalize_text(marked_text) in normalize_text(translation)
            records.append({
                "segment_id": sid,
                "source": source_lookup.get(sid, ""),
                "translation": translation,
                "category": err.get("category", ""),
                "subtype": err.get("subtype", ""),
                "severity": err.get("severity", ""),
                "marked_text": marked_text,
                "note": err.get("note", ""),
                "rule_check": "존재" if exists else "미존재",
                "rule_verdict": "O" if exists else "X",
                "final_verdict": "O" if exists else "X",
                "review_reason": "marked_text가 번역문에 존재하지 않아 허위 오류로 분류" if not exists else "LLM Fact Check 대상"
            })
    return pd.DataFrame(records)

def llm_fact_check(row: pd.Series, model: str = "gpt-4o-mini") -> Tuple[str, str]:
    if OpenAI is None:
        return "O", "OpenAI 패키지가 설치되어 있지 않아 LLM 검수를 건너뜀"
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        return "O", "OPENAI_API_KEY가 없어 LLM 검수를 건너뜀"

    client = OpenAI(api_key=api_key)
    prompt = f"""
You are a translation QA fact-checker.

Decide whether Gemini's error note is actually valid.

Return only JSON:
{{"verdict":"O or X","reason":"short Korean reason"}}

Definitions:
- O: Gemini's error note is valid. The marked text contains a real translation error.
- X: Gemini's error note is false positive. The translation is acceptable or Gemini's note is wrong.

Source Korean:
{row['source']}

English translation:
{row['translation']}

Marked text:
{row['marked_text']}

Gemini note:
{row['note']}
"""
    try:
        resp = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": "You are a precise translation QA reviewer. Return JSON only."},
                {"role": "user", "content": prompt},
            ],
            temperature=0,
        )
        result = json.loads(resp.choices[0].message.content)
        verdict = result.get("verdict", "O")
        reason = result.get("reason", "")
        return (verdict if verdict in ["O", "X"] else "O"), reason
    except Exception as e:
        return "O", f"LLM 검수 오류로 기본값 O 처리: {e}"

with st.sidebar:
    st.header("검수 설정")
    use_llm = st.checkbox("LLM Fact Check 사용", value=False)
    model_name = st.text_input("OpenAI 모델명", value="gpt-4o-mini")
    st.caption("LLM 검수를 사용하려면 실행 환경에 OPENAI_API_KEY가 설정되어 있어야 합니다.")
    st.markdown("---")
    st.markdown("**판정 기준**")
    st.markdown("- O: 유효 오류")
    st.markdown("- X: 허위 오류")

translation_df = load_translation_df()
eval_data = load_eval_json()

if translation_df.empty or not eval_data:
    st.warning("파일을 업로드하거나 샘플 데이터 테스트를 켜주세요.")
    st.stop()

review_df = flatten_errors(eval_data, translation_df)

if st.button("자동 검수 실행", type="primary", use_container_width=True):
    if use_llm:
        for idx, row in review_df.iterrows():
            if row["rule_verdict"] == "O":
                verdict, reason = llm_fact_check(row, model=model_name)
                review_df.at[idx, "final_verdict"] = verdict
                review_df.at[idx, "review_reason"] = reason
    st.session_state["review_df"] = review_df

if "review_df" not in st.session_state:
    st.info("자동 검수 실행 버튼을 눌러 결과를 확인하세요.")
    st.stop()

result_df = st.session_state["review_df"]
total = len(result_df)
valid_count = int((result_df["final_verdict"] == "O").sum())
false_count = int((result_df["final_verdict"] == "X").sum())
false_ratio = false_count / total * 100 if total else 0

st.markdown("### 3. 검수 결과 요약")
m1, m2, m3, m4 = st.columns(4)
for col, label, value in [
    (m1, "전체 오류 후보", f"{total}건"),
    (m2, "유효 오류(O)", f"{valid_count}건"),
    (m3, "허위 오류(X)", f"{false_count}건"),
    (m4, "허위 오류 비율", f"{false_ratio:.1f}%"),
]:
    with col:
        st.markdown(f'<div class="metric-card"><div class="small-label">{label}</div><div class="big-number">{value}</div></div>', unsafe_allow_html=True)

st.markdown(f"""
<div class="insight-box">
<b>핵심 인사이트</b><br>
전체 오류 후보 {total}건 중 <b>{false_count}건({false_ratio:.1f}%)</b>은 자동 검수 과정에서 허위 오류로 분류되었습니다.
반복 검수 업무에서 사람이 확인해야 하는 후보군을 줄이는 데 활용할 수 있습니다.
</div>
""", unsafe_allow_html=True)

st.markdown("### 4. 오류 판정 분포")
chart_df = pd.DataFrame({"판정": ["유효 오류(O)", "허위 오류(X)"], "건수": [valid_count, false_count]}).set_index("판정")
st.bar_chart(chart_df)

st.markdown("### 5. 상세 검수 결과")
st.dataframe(
    result_df[["segment_id", "category", "subtype", "severity", "marked_text", "rule_check", "final_verdict", "note", "review_reason"]],
    use_container_width=True
)

st.download_button(
    "검수 결과 CSV 다운로드",
    data=result_df.to_csv(index=False).encode("utf-8-sig"),
    file_name="translation_qa_review_result.csv",
    mime="text/csv",
    use_container_width=True,
)

st.markdown("### 6. 허위 오류 목록")
false_df = result_df[result_df["final_verdict"] == "X"]
if false_df.empty:
    st.success("허위 오류로 분류된 항목이 없습니다.")
else:
    for _, row in false_df.iterrows():
        with st.container(border=True):
            st.markdown(f"**Segment {row['segment_id']} | marked_text: `{row['marked_text']}`**")
            st.write(row["review_reason"])
            st.caption(row["note"])
