# app.py
import streamlit as st
from PIL import Image, ImageFilter, ImageOps
import pytesseract
import numpy as np
import cv2
import re
from fractions import Fraction
from sympy import sympify

# -------------------------
# Utilities
# -------------------------
def pil_to_cv(img_pil):
    return cv2.cvtColor(np.array(img_pil), cv2.COLOR_RGB2BGR)

def cv_to_pil(img_cv):
    return Image.fromarray(cv2.cvtColor(img_cv, cv2.COLOR_BGR2RGB))

def preprocess_variants(pil_img):
    """Return list of (name, PIL image) variants for OCR."""
    variants = []
    # original
    variants.append(("orig", pil_img.copy()))
    # grayscale
    g = ImageOps.grayscale(pil_img)
    variants.append(("gray", g))
    # resized (improve small text)
    w, h = pil_img.size
    scale = 2 if max(w, h) < 1200 else 1
    if scale != 1:
        variants.append(("resized", pil_img.resize((w*scale, h*scale), Image.LANCZOS)))
    # sharpen
    variants.append(("sharpen", pil_img.filter(ImageFilter.SHARPEN)))
    # adaptive threshold via OpenCV
    cv = pil_to_cv(pil_img.convert("L"))
    cv = cv2.medianBlur(cv, 3)
    th = cv2.adaptiveThreshold(cv, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                               cv2.THRESH_BINARY, 31, 10)
    variants.append(("th_adaptive", cv_to_pil(cv2.cvtColor(th, cv2.COLOR_GRAY2BGR))))
    # Otsu
    _, otsu = cv2.threshold(cv, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    variants.append(("th_otsu", cv_to_pil(cv2.cvtColor(otsu, cv2.COLOR_GRAY2BGR))))
    return variants

def ocr_with_config(pil_img, config):
    """Run pytesseract and return raw text and word confidences list."""
    try:
        data = pytesseract.image_to_data(pil_img, output_type=pytesseract.Output.DICT, config=config)
        text = " ".join([w for w in data['text'] if w.strip()])
        # compute average confidence (ignore -1)
        confs = [int(c) for c in data['conf'] if c.strip() and int(float(c)) >= 0]
        avg_conf = float(np.mean(confs)) if confs else 0.0
        return text.strip(), avg_conf, data
    except Exception as e:
        return "", 0.0, None

def aggregate_ocr_results(results):
    """
    results: list of dicts {variant, config, text, conf}
    Strategy: choose the text with highest conf; also keep top N candidates.
    """
    if not results:
        return "", 0.0, results
    # sort by conf then by text length (prefer longer meaningful text)
    sorted_r = sorted(results, key=lambda r: (r['conf'], len(r['text'])), reverse=True)
    best = sorted_r[0]
    # build combined candidate by majority token voting (optional)
    return best['text'], best['conf'], sorted_r

# -------------------------
# Parsing and evaluation
# -------------------------
def extract_numbers(text):
    return [int(n) for n in re.findall(r'\d+', text)]

def extract_fractions(text):
    return re.findall(r'\d+\s*/\s*\d+', text)

def parse_question_answer(candidate_text, raw_text_lines):
    """
    Heuristics:
    - If 'Answer:' present -> split
    - If '=' present -> split
    - If 'multiply' or '×' present -> detect multiplicand/multiplier and product lines
    - If fractions present -> treat as fraction comparison
    - Else fallback to returning candidate_text as question and None as answer
    """
    text = candidate_text.strip()
    # normalize whitespace
    text_norm = re.sub(r'\s+', ' ', text)
    # 1) Answer:
    m = re.search(r'answer\s*[:\-]\s*(.+)', text_norm, flags=re.IGNORECASE)
    if m:
        q = re.sub(r'answer\s*[:\-].*', '', text_norm, flags=re.IGNORECASE).strip()
        a = m.group(1).strip()
        return q, a, "answer_colon"
    # 2) equals sign
    if "=" in text_norm:
        parts = text_norm.split("=")
        q = parts[0].strip()
        a = "=".join(parts[1:]).strip()
        return q, a, "equals"
    # 3) multiplication layout: look at raw lines to find a pattern like:
    #    35
    #   x 4
    #   140
    # We'll search for a line containing 'multiply' or '×' or 'x' and then numeric neighbors
    joined_lines = raw_text_lines
    for i, ln in enumerate(joined_lines):
        if re.search(r'\bmultiply\b|×|\bx\b', ln, flags=re.IGNORECASE):
            # look around for numeric lines
            nums_before = []
            nums_after = []
            # collect up to 3 lines before and after
            for j in range(max(0, i-3), i):
                nums_before.extend(re.findall(r'\d+', joined_lines[j]))
            for j in range(i+1, min(len(joined_lines), i+4)):
                nums_after.extend(re.findall(r'\d+', joined_lines[j]))
            all_nums = nums_before + nums_after
            if len(all_nums) >= 2:
                # assume first two are multiplicand and multiplier, third (if any) is product
                q = f"{all_nums[0]} × {all_nums[1]}"
                a = all_nums[2] if len(all_nums) >= 3 else None
                return q, a, "multiplication_layout"
    # 4) fractions
    fracs = extract_fractions(text_norm)
    if fracs:
        # try to find answer fraction in text
        m2 = re.search(r'answer\s*[:\-]?\s*(\d+\s*/\s*\d+)', text_norm, flags=re.IGNORECASE)
        a = m2.group(1).strip() if m2 else None
        q = " ".join(fracs)
        return q, a, "fractions"
    # 5) simple arithmetic detection
    m_ar = re.search(r'(\d+\s*[\+\-]\s*\d+)', text_norm)
    if m_ar:
        q = m_ar.group(1).strip()
        # try to find numeric answer after it
        m_after = re.search(re.escape(q) + r'.*?=\s*([-\d\.]+)', text_norm)
        a = m_after.group(1).strip() if m_after else None
        return q, a, "arithmetic"
    # fallback
    return text_norm, None, "unknown"

def evaluate_and_explain(question, student_answer):
    """
    Return dict: {ok:bool/None, correct_answer:str, explanation:list[str]}
    """
    explanation = []
    try:
        # fractions
        if re.search(r'\d+\s*/\s*\d+', question):
            fracs = extract_fractions(question)
            frac_objs = [(f, Fraction(int(re.findall(r'\d+', f)[0]), int(re.findall(r'\d+', f)[1]))) for f in fracs]
            smallest = min(frac_objs, key=lambda x: x[1])
            correct = smallest[0]
            explanation.append(f"Fractions compared: {', '.join([f for f,_ in frac_objs])}")
            explanation.append(f"Smallest is {correct} (value {float(smallest[1]):.3f})")
            if student_answer:
                m = re.search(r'(\d+\s*/\s*\d+)', student_answer)
                if m:
                    stud = Fraction(*map(int, re.findall(r'\d+', m.group(1))))
                    ok = (stud == smallest[1])
                    return {"ok": ok, "correct_answer": correct, "explanation": explanation}
                else:
                    # try numeric compare
                    try:
                        stud_val = float(student_answer)
                        ok = abs(stud_val - float(smallest[1])) < 1e-6
                        return {"ok": ok, "correct_answer": correct, "explanation": explanation}
                    except:
                        return {"ok": None, "correct_answer": correct, "explanation": explanation}
            return {"ok": None, "correct_answer": correct, "explanation": explanation}
        # multiplication or arithmetic
        if "×" in question or "x" in question or re.search(r'\d+\s*\*\s*\d+', question):
            nums = extract_numbers(question)
            if len(nums) >= 2:
                correct = nums[0] * nums[1]
                explanation.append(f"Computed {nums[0]} × {nums[1]} = {correct}")
                if student_answer and re.search(r'\d+', student_answer):
                    stud = int(re.search(r'\d+', student_answer).group())
                    return {"ok": stud == correct, "correct_answer": str(correct), "explanation": explanation}
                return {"ok": None, "correct_answer": str(correct), "explanation": explanation}
        if re.search(r'\d+\s*[\+\-]\s*\d+', question):
            nums = extract_numbers(question)
            if len(nums) >= 2:
                if "+" in question:
                    correct = nums[0] + nums[1]
                    explanation.append(f"Computed {nums[0]} + {nums[1]} = {correct}")
                else:
                    correct = nums[0] - nums[1]
                    explanation.append(f"Computed {nums[0]} - {nums[1]} = {correct}")
                if student_answer and re.search(r'-?\d+', student_answer):
                    stud = int(re.search(r'-?\d+', student_answer).group())
                    return {"ok": stud == correct, "correct_answer": str(correct), "explanation": explanation}
                return {"ok": None, "correct_answer": str(correct), "explanation": explanation}
        # fallback: try sympy
        try:
            val = sympify(question).evalf()
            correct = float(val)
            explanation.append(f"Sympy evaluated question to {correct}")
            if student_answer:
                try:
                    stud = float(student_answer)
                    return {"ok": abs(stud - correct) < 1e-6, "correct_answer": str(correct), "explanation": explanation}
                except:
                    return {"ok": None, "correct_answer": str(correct), "explanation": explanation}
            return {"ok": None, "correct_answer": str(correct), "explanation": explanation}
        except Exception:
            return {"ok": None, "correct_answer": None, "explanation": ["Could not evaluate automatically."]}
    except Exception as e:
        return {"ok": None, "correct_answer": None, "explanation": [f"Error during evaluation: {e}"]}

# -------------------------
# Streamlit UI
# -------------------------
st.set_page_config(page_title="Robust Koobits Helper", layout="centered")
st.title("Robust Koobits Screenshot Helper (Copilot style)")

uploaded = st.file_uploader("Upload Koobits screenshot", type=["png", "jpg", "jpeg"])
if not uploaded:
    st.info("Upload a screenshot. The app will run multiple OCR passes and attempt to parse question and answer.")
    st.stop()

img = Image.open(uploaded).convert("RGB")
st.image(img, caption="Uploaded image", use_column_width=True)

# 1) Generate preprocessing variants
variants = preprocess_variants(img)

# 2) OCR configs to try
configs = [
    ("digits_ops", "-c tessedit_char_whitelist=0123456789+-×x*/=/: --psm 6"),
    ("digits_only", "-c tessedit_char_whitelist=0123456789 -l eng --psm 6"),
    ("default", "--psm 3")
]

ocr_results = []
for vname, vimg in variants:
    for cname, cfg in configs:
        text, conf, data = ocr_with_config(vimg, cfg)
        ocr_results.append({"variant": vname, "config": cname, "text": text, "conf": conf, "data": data})

# 3) Aggregate best candidate
candidate_text, candidate_conf, sorted_results = aggregate_ocr_results(ocr_results)

st.subheader("OCR candidates (top 5)")
for r in sorted_results[:5]:
    st.write(f"- Variant **{r['variant']}** config **{r['config']}** conf **{r['conf']:.1f}** -> {r['text'][:200]}")

st.markdown("---")
st.write("**Chosen OCR candidate (best)**")
st.write(candidate_text)
st.write(f"Confidence score: **{candidate_conf:.1f}**")

# 4) Also show raw lines for layout parsing
raw_text = "\n".join([r['text'] for r in sorted_results])
raw_lines = [ln.strip() for ln in raw_text.splitlines() if ln.strip()]
st.subheader("Filtered OCR lines (for layout detection)")
st.text_area("Lines", "\n".join(raw_lines), height=180)

# 5) Parse question and answer
question, student_answer, mode = parse_question_answer(candidate_text, raw_lines)
st.write("Detected mode:", mode)
st.write("Parsed question:", question or "None")
st.write("Parsed student answer:", student_answer or "None")

# 6) Manual overrides
st.markdown("---")
st.subheader("Manual overrides")
q_override = st.text_input("Question (edit if OCR is wrong)", value=question or "")
a_override = st.text_input("Student answer (edit if OCR is wrong)", value=student_answer or "")
question = q_override.strip() if q_override.strip() else question
student_answer = a_override.strip() if a_override.strip() else student_answer

# 7) Evaluate and explain
st.markdown("---")
st.subheader("Evaluation")
result = evaluate_and_explain(question or "", student_answer or "")
if result["correct_answer"] is not None:
    st.write("Correct answer:", f"**{result['correct_answer']}**")
if result["ok"] is True:
    st.success("✅ Student answer is correct")
elif result["ok"] is False:
    st.error("❌ Student answer is incorrect")
else:
    st.info("⚠️ Could not determine correctness automatically")

st.write("Explanation / steps:")
for line in result["explanation"]:
    st.write("-", line)

# 8) Confidence and logs
st.markdown("---")
st.subheader("Diagnostics")
st.write(f"Chosen OCR confidence: **{candidate_conf:.1f}** (0-100 scale)")
st.write("Top OCR candidates (brief):")
for r in sorted_results[:6]:
    txt = r['text'].replace("\n", " ")[:180]
    st.write(f"- {r['variant']}/{r['config']} conf={r['conf']:.1f} -> {txt}")

st.info("If OCR is noisy, use the override boxes. For better OCR, try cropping the question area or increasing contrast.")
