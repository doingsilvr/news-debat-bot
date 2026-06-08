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
    max-width: 1100px;
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
.warning-box {
    background: #FFF7ED;
    border: 1px solid #FED7AA;
    border-radius: 16px;
    padding: 16px 18px;
    margin-bottom: 16px;
}
</style>
""", unsafe_allow_html=True)


def normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip().lower()


def find_col(df: pd.DataFrame, candidates: list[str]) -> str | None:
    for candidate in candidates:
        for col in df.columns:
            if str(col).strip().lower() == candidate.strip().lower():
                return col
    return None


def extract_json_from_cell(cell):
    text = str(cell or "").strip()
    text = text.replace("```json", "").replace("```", "").strip()

    start = text.find("{")
    end = text.rfind("}")

    if start != -1 and end != -1:
        text = text[start:end + 1]

    try:
        return json.loads(text)
    except Exception:
        return None


def safe_parse_llm_json(content: str) -> dict:
    text = str(content or "").strip()
    text = text.replace("```json", "").replace("```", "").strip()

    start = text.find("{")
    end = text.rfind("}")

    if start != -1 and end != -1:
        text = text[start:end + 1]

    try:
        return json.loads(text)
    except Exception:
        return {"verdict": "X", "reason": "LLM 응답 JSON 파싱 실패로 보수적으로 X 처리"}


def llm_fact_check(
    api_key: str,
    source: str,
    translation: str,
    marked_text: str,
    note: str,
    model: str = "gpt-4o-mini"
) -> Tuple[str, str]:

    api_key = str(api_key or "").strip()

    if not api_key:
        return "O", "API Key가 없어 LLM 검수 미실행"

    client = OpenAI(api_key=api_key)

    payload = {
        "source_ko": str(source),
        "translation_en": str(translation),
        "marked_text": str(marked_text),
        "gemini_note": str(note),
        "decision_rule": {
            "return_O_only_if": [
                "Gemini's note identifies a clear and material translation error.",
                "The marked text clearly distorts the Korean source meaning.",
                "The issue is not merely a stylistic preference or unnecessary alternative."
            ],
            "return_X_if": [
                "The marked text is acceptable in context.",
                "Gemini suggests an alternative expression but the current translation is also valid.",
                "Gemini's note is not clearly supported by the Korean source and English translation.",
                "Gemini over-corrects a grammatically acceptable expression.",
                "The issue is only a preference, not a real translation error."
            ]
        },
        "output_format": {
            "verdict": "O or X",
            "reason": "short Korean reason"
        }
    }

    system_prompt = """
You are a strict false-positive detector for translation QA.

Your job is NOT to improve the translation.
Your job is to judge whether Gemini's error note is truly valid.

Be conservative about marking an error as valid.
Return O only when the marked_text clearly contains a real translation error.
Return X when the marked_text is acceptable, when Gemini over-corrects, or when Gemini's note is only a preference.

Return JSON only.
"""

    try:
        response = client.chat.completions.create(
            model=model,
            messages=[
                {
                    "role": "system",
                    "content": system_prompt
                },
                {
                    "role": "user",
                    "content": json.dumps(payload, ensure_ascii=False)
                }
            ],
            temperature=0,
        )

        content = response.choices[0].message.content
        result = safe_parse_llm_json(content)

        verdict = result.get("verdict", "X")
        reason = result.get("reason", "")

        if verdict not in ["O", "X"]:
            verdict = "X"
            reason = "LLM 판정값이 불명확하여 X 처리"

        return verdict, reason

    except Exception as e:
        return "O", f"LLM 검수 실패로 기본값 O 처리: {e}"


def review_dataframe(
    df: pd.DataFrame,
    api_key: str,
    use_llm: bool,
    model_name: str
) -> pd.DataFrame:

    source_col = find_col(df, [
        "Source (KO)",
        "source",
        "Source",
        "원문",
        "한국어 원문"
    ])

    translation_col = find_col(df, [
        "Translation (EN)",
        "translation",
        "Translation",
        "번역문",
        "영어 번역문"
    ])

    eval_col = find_col(df, [
        "MQM - LLM Evaluation / Accuracy",
        "MQM - LLM Evaluation",
        "Evaluation",
        "평가 결과",
        "LLM Evaluation"
    ])

    if translation_col is None or eval_col is None:
        st.error("필수 컬럼을 찾지 못했습니다.")
        st.write("현재 파일의 컬럼명:")
        st.write(df.columns.tolist())
        st.stop()

    results = []

    for idx, row in df.iterrows():

        source = row[source_col] if source_col else ""
        translation = row[translation_col]

        parsed = extract_json_from_cell(row[eval_col])

        if not parsed:
            continue

        segment_id = parsed.get("segment_id", idx + 1)
        errors = parsed.get("errors", [])

        for err in errors:

            marked_text = err.get("marked_text", "")
            note = err.get("note", "")

            exists = normalize_text(marked_text) in normalize_text(translation)

            if not exists:
                final_verdict = "X"
                review_type = "유형1: Rule Check"
                reason = "marked_text가 번역문에 존재하지 않아 허위 오류로 분류"

            else:
                review_type = "유형2: LLM Fact Check"

                if use_llm:
                    final_verdict, reason = llm_fact_check(
                        api_key=api_key,
                        source=source,
                        translation=translation,
                        marked_text=marked_text,
                        note=note,
                        model=model_name
                    )
                else:
                    final_verdict = "O"
                    reason = "marked_text가 번역문에 존재하여 LLM 검수 대상이나, LLM 검수 비활성화로 O 처리"

            results.append({
                "segment_id": segment_id,
                "source": source,
                "translation": translation,
                "category": err.get("category", ""),
                "subtype": err.get("subtype", ""),
                "severity": err.get("severity", ""),
                "marked_text": marked_text,
                "note": note,
                "rule_check": "존재" if exists else "미존재",
                "review_type": review_type,
                "final_verdict": final_verdict,
                "review_reason": reason
            })

    return pd.DataFrame(results)


with st.sidebar:
    st.header("⚙️ 검수 설정")

    api_key = st.text_input(
        "OpenAI API Key",
        type="password",
        placeholder="sk-..."
    )

    use_llm = st.toggle(
        "유형2 LLM Fact Check 사용",
        value=True
    )

    model_name = st.text_input(
        "모델명",
        value="gpt-4o-mini"
    )

    st.divider()

    st.subheader("검수 로직")

    st.markdown("""
<div class="logic-box">
<b>유형1: Rule Check</b><br>
<code>marked_text</code>가 번역문에 없으면<br>
→ 허위 오류(X)
</div>
""", unsafe_allow_html=True)

    st.markdown("""
<div class="logic-box">
<b>유형2: LLM Fact Check</b><br>
<code>marked_text</code>는 번역문에 존재하지만<br>
Gemini Note의 판단 근거가 부적절하면<br>
→ 허위 오류(X)
</div>
""", unsafe_allow_html=True)


st.markdown("# 🔍 번역 평가 검수 자동화")
st.markdown(
    "Gemini가 판정한 번역 오류 결과에서 **허위 오류(False Positive)** 를 자동으로 탐지합니다."
)

st.markdown("""
<div class="warning-box">
<b>PoC 목적</b><br>
AI 번역 평가 결과를 사람이 다시 검수하던 반복 업무를 줄이기 위해,
코드 기반 Rule Check와 LLM Fact Check를 조합한 검수 자동화 흐름을 설계했습니다.
</div>
""", unsafe_allow_html=True)

st.markdown("### 📂 xlsx 파일 업로드")

uploaded_file = st.file_uploader(
    "번역 평가 결과 xlsx 파일을 업로드해주세요.",
    type=["xlsx"]
)

if uploaded_file is None:
    st.info("xlsx 파일을 업로드하면 검수 자동화를 실행할 수 있습니다.")
    st.stop()

xls = pd.ExcelFile(uploaded_file)
sheet_name = st.selectbox("분석할 시트 선택", xls.sheet_names)

df = pd.read_excel(uploaded_file, sheet_name=sheet_name)

st.success(f"파일 업로드 완료: {len(df)}개 행을 불러왔습니다.")

with st.expander("업로드 데이터 미리보기", expanded=False):
    st.dataframe(df.head(10), use_container_width=True)
    st.write("컬럼명:", df.columns.tolist())

if st.button("🚀 자동 검수 실행", type="primary", use_container_width=True):
    result_df = review_dataframe(
        df=df,
        api_key=api_key,
        use_llm=use_llm,
        model_name=model_name
    )

    if len(result_df) == 0:
        st.error("검수 가능한 오류 데이터를 찾지 못했습니다. 평가 결과 JSON 형식을 확인해주세요.")
        st.stop()

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

type1_false = int(
    (
        (result_df["review_type"] == "유형1: Rule Check")
        & (result_df["final_verdict"] == "X")
    ).sum()
)

type2_false = int(
    (
        (result_df["review_type"] == "유형2: LLM Fact Check")
        & (result_df["final_verdict"] == "X")
    ).sum()
)


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

f1, f2, f3 = st.columns(3)

with f1:
    st.markdown(
        f"""
        <div class="result-box">
        <b>1. Rule Check</b><br><br>
        marked_text 존재 여부 확인<br>
        처리 대상: <b>{type1_count}건</b><br>
        허위 오류 탐지: <b>{type1_false}건</b>
        </div>
        """,
        unsafe_allow_html=True
    )

with f2:
    st.markdown(
        f"""
        <div class="result-box">
        <b>2. LLM Fact Check</b><br><br>
        문맥·문법 타당성 확인<br>
        처리 대상: <b>{type2_count}건</b><br>
        허위 오류 탐지: <b>{type2_false}건</b>
        </div>
        """,
        unsafe_allow_html=True
    )

with f3:
    st.markdown(
        f"""
        <div class="result-box">
        <b>3. Review Result</b><br><br>
        전체 후보 중 허위 오류 분류<br>
        최종 제거 후보: <b>{false_count}건</b><br>
        비율: <b>{false_ratio:.1f}%</b>
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
                <b>Segment {row.get('segment_id')}</b><br>
                <b>marked_text:</b> <code>{row.get('marked_text', '')}</code><br>
                <b>검수 유형:</b> {row.get('review_type')}<br>
                <b>판정 근거:</b> {row.get('review_reason')}
            </div>
            """,
            unsafe_allow_html=True
        )


st.markdown("### 🧾 전체 검수 결과")

st.dataframe(
    result_df,
    use_container_width=True
)

st.download_button(
    "📥 검수 결과 CSV 다운로드",
    data=result_df.to_csv(index=False).encode("utf-8-sig"),
    file_name="translation_review_result.csv",
    mime="text/csv",
    use_container_width=True
)
