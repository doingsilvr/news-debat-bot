import json
import re
from typing import Tuple

import pandas as pd
import streamlit as st
from openai import OpenAI


st.set_page_config(
    page_title="번역 평가 검수 자동화",
    page_icon="🔍",
    layout="wide"
)

st.markdown("""
<style>
.block-container {
    padding-top: 3rem;
    max-width: 1050px;
}
.metric-card {
    background: #F7F9FC;
    border: 1px solid #E5EAF2;
    border-radius: 18px;
    padding: 22px;
    text-align: center;
}
.metric-num {
    font-size: 2.2rem;
    font-weight: 800;
    color: #2563EB;
}
.metric-label {
    color: #4B5563;
    font-size: 0.95rem;
}
.result-box {
    background: white;
    border: 1px solid #E5EAF2;
    border-radius: 16px;
    padding: 18px;
    margin-bottom: 12px;
}
.logic-box {
    background: #F8FAFC;
    border-left: 4px solid #2563EB;
    border-radius: 12px;
    padding: 14px 16px;
    margin-bottom: 12px;
}
</style>
""", unsafe_allow_html=True)


# =====================
# Helper
# =====================

def normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip().lower()


def find_col(df: pd.DataFrame, candidates: list[str]) -> str | None:
    cols = list(df.columns)
    for c in candidates:
        for col in cols:
            if str(col).strip().lower() == c.lower():
                return col
    return None


def llm_fact_check(
    api_key: str,
    source: str,
    translation: str,
    marked_text: str,
    note: str,
    model: str = "gpt-4o-mini"
) -> Tuple[str, str]:
    client = OpenAI(api_key=api_key)

    prompt = f"""
You are a translation QA fact-checker.

Your task is to decide whether Gemini's error note is actually valid.

Return only JSON:
{{"verdict":"O or X","reason":"short Korean reason"}}

Definitions:
- O: Gemini's error note is valid. The marked text contains a real translation error.
- X: Gemini's error note is a false positive. The translation is acceptable, or Gemini's note is wrong.

Source Korean:
{source}

English translation:
{translation}

Marked text:
{marked_text}

Gemini note:
{note}
"""

    try:
        resp = client.chat.completions.create(
            model=model,
            messages=[
                {
                    "role": "system",
                    "content": "You are a precise translation QA reviewer. Return JSON only."
                },
                {"role": "user", "content": prompt},
            ],
            temperature=0,
        )

        content = resp.choices[0].message.content
        result = json.loads(content)

        verdict = result.get("verdict", "O")
        reason = result.get("reason", "")

        if verdict not in ["O", "X"]:
            verdict = "O"

        return verdict, reason

    except Exception as e:
        return "O", f"LLM 검수 실패로 기본값 O 처리: {e}"


def review_dataframe(df: pd.DataFrame, api_key: str, use_llm: bool) -> pd.DataFrame:
    source_col = find_col(df, ["source", "Source", "원문", "한국어 원문"])
    translation_col = find_col(df, ["translation", "Translation", "번역문", "영어 번역문"])
    marked_col = find_col(df, ["marked_text", "Marked Text", "지적 표현"])
    note_col = find_col(df, ["note", "Note", "검수 내용", "오류 설명"])
    segment_col = find_col(df, ["segment_id", "Segment", "segment", "번호"])

    required = {
        "translation": translation_col,
        "marked_text": marked_col,
        "note": note_col,
    }

    missing = [k for k, v in required.items() if v is None]
    if missing:
        st.error(f"필수 컬럼을 찾지 못했습니다: {missing}")
        st.stop()

    results = []

    for idx, row in df.iterrows():
        source = row[source_col] if source_col else ""
        translation = row[translation_col]
        marked_text = row[marked_col]
        note = row[note_col]
        segment_id = row[segment_col] if segment_col else idx + 1

        exists = normalize_text(marked_text) in normalize_text(translation)

        if not exists:
            final_verdict = "X"
            review_type = "유형1: Rule Check"
            reason = "marked_text가 번역문에 존재하지 않아 허위 오류로 분류"
        else:
            review_type = "유형2: LLM Fact Check"

            if use_llm and api_key:
                final_verdict, reason = llm_fact_check(
                    api_key=api_key,
                    source=source,
                    translation=translation,
                    marked_text=marked_text,
                    note=note,
                )
            else:
                final_verdict = "O"
                reason = "marked_text가 번역문에 존재하여 LLM 검수 대상이나, API 미사용으로 O 처리"

        new_row = row.to_dict()
        new_row.update({
            "segment_id_review": segment_id,
            "rule_check": "존재" if exists else "미존재",
            "review_type": review_type,
            "final_verdict": final_verdict,
            "review_reason": reason,
        })
        results.append(new_row)

    return pd.DataFrame(results)


# =====================
# Sidebar
# =====================

with st.sidebar:
    st.header("⚙️ 설정")

    api_key = st.text_input(
        "OpenAI API Key",
        type="password",
        placeholder="sk-..."
    )

    use_llm = st.toggle("유형2 LLM Fact Check 사용", value=False)

    st.divider()

    st.subheader("검수 로직")
    st.markdown("""
<div class="logic-box">
<b>유형1 (Rule)</b><br>
<code>marked_text</code>가 번역문에 없으면<br>
→ 허위 오류(X)
</div>
""", unsafe_allow_html=True)

    st.markdown("""
<div class="logic-box">
<b>유형2 (LLM)</b><br>
번역문에 존재하지만<br>
Gemini Note의 판단 근거가 부적절하면<br>
→ 허위 오류(X)
</div>
""", unsafe_allow_html=True)


# =====================
# Main
# =====================

st.markdown("# 🔍 번역 평가 검수 자동화")
st.markdown(
    "Gemini가 판정한 번역 오류 결과에서 **허위 오류(False Positive)** 를 자동으로 탐지합니다."
)

st.markdown("### 📂 xlsx 파일 업로드")
uploaded_file = st.file_uploader(
    "번역 평가 결과 xlsx 파일을 업로드해주세요.",
    type=["xlsx"]
)

if uploaded_file is None:
    st.info("위에서 번역 평가 결과 xlsx 파일을 업로드해주세요.")
    st.stop()

xls = pd.ExcelFile(uploaded_file)
sheet_name = st.selectbox("분석할 시트 선택", xls.sheet_names)
df = pd.read_excel(uploaded_file, sheet_name=sheet_name)

st.success(f"파일 업로드 완료: {len(df)}개 행을 불러왔습니다.")

with st.expander("업로드 데이터 미리보기", expanded=False):
    st.dataframe(df.head(10), use_container_width=True)

if st.button("🚀 자동 검수 실행", type="primary", use_container_width=True):
    result_df = review_dataframe(df, api_key=api_key, use_llm=use_llm)
    st.session_state["result_df"] = result_df

if "result_df" not in st.session_state:
    st.stop()

result_df = st.session_state["result_df"]

total = len(result_df)
false_count = int((result_df["final_verdict"] == "X").sum())
valid_count = int((result_df["final_verdict"] == "O").sum())
false_ratio = false_count / total * 100 if total else 0

type1_count = int((result_df["review_type"] == "유형1: Rule Check").sum())
type2_count = int((result_df["review_type"] == "유형2: LLM Fact Check").sum())

st.markdown("### 📊 검수 결과 요약")

m1, m2, m3, m4 = st.columns(4)

with m1:
    st.markdown(
        f"""
        <div class="metric-card">
            <div class="metric-num">{total}</div>
            <div class="metric-label">전체 오류 후보</div>
        </div>
        """,
        unsafe_allow_html=True
    )

with m2:
    st.markdown(
        f"""
        <div class="metric-card">
            <div class="metric-num">{false_count}</div>
            <div class="metric-label">허위 오류 탐지</div>
        </div>
        """,
        unsafe_allow_html=True
    )

with m3:
    st.markdown(
        f"""
        <div class="metric-card">
            <div class="metric-num">{false_ratio:.1f}%</div>
            <div class="metric-label">False Positive 비율</div>
        </div>
        """,
        unsafe_allow_html=True
    )

with m4:
    st.markdown(
        f"""
        <div class="metric-card">
            <div class="metric-num">{valid_count}</div>
            <div class="metric-label">유효 오류</div>
        </div>
        """,
        unsafe_allow_html=True
    )

st.markdown("### 🧭 검수 흐름")

flow1, flow2, flow3 = st.columns(3)

with flow1:
    st.markdown(
        f"""
        <div class="result-box">
        <b>1. Rule Check</b><br><br>
        marked_text 존재 여부 확인<br>
        <b>{type1_count}건</b> Rule 기반 처리
        </div>
        """,
        unsafe_allow_html=True
    )

with flow2:
    st.markdown(
        f"""
        <div class="result-box">
        <b>2. LLM Fact Check</b><br><br>
        문맥·문법 타당성 확인<br>
        <b>{type2_count}건</b> LLM 검수 대상
        </div>
        """,
        unsafe_allow_html=True
    )

with flow3:
    st.markdown(
        f"""
        <div class="result-box">
        <b>3. Review Result</b><br><br>
        허위 오류 자동 분류<br>
        <b>{false_count}건</b> 제거 후보
        </div>
        """,
        unsafe_allow_html=True
    )

st.markdown("### 📌 허위 오류 목록")

false_df = result_df[result_df["final_verdict"] == "X"]

if false_df.empty:
    st.success("허위 오류로 분류된 항목이 없습니다.")
else:
    for _, row in false_df.iterrows():
        st.markdown(
            f"""
            <div class="result-box">
                <b>Segment {row.get('segment_id_review')}</b><br>
                <b>marked_text:</b> <code>{row.get('marked_text', '')}</code><br>
                <b>검수 유형:</b> {row.get('review_type')}<br>
                <b>판정 근거:</b> {row.get('review_reason')}
            </div>
            """,
            unsafe_allow_html=True
        )

st.markdown("### 🧾 전체 검수 결과")
st.dataframe(result_df, use_container_width=True)

st.download_button(
    "📥 검수 결과 CSV 다운로드",
    data=result_df.to_csv(index=False).encode("utf-8-sig"),
    file_name="translation_review_result.csv",
    mime="text/csv",
    use_container_width=True,
)
