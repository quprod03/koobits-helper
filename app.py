# app.py
import streamlit as st
from PIL import Image
import pytesseract
import requests
import re

st.set_page_config(page_title="Forward-to-LLM Koobits Helper", layout="centered")
st.title("Upload screenshot → Forward to LLM / Copilot-style backend")

st.markdown("Upload a Koobits screenshot. The app will show a quick OCR preview and forward the image to your backend endpoint which calls an LLM (OpenAI/Azure or your Copilot endpoint).")

# Backend endpoint config (set your backend URL here or in the UI)
DEFAULT_BACKEND = ""
backend_url = st.text_input("Backend endpoint URL (POST)", value=DEFAULT_BACKEND, placeholder="https://your-backend.example.com/parse")
api_key = st.text_input("Backend API key (optional)", type="password")

uploaded = st.file_uploader("Upload screenshot (png/jpg/jpeg)", type=["png","jpg","jpeg"])
if not uploaded:
    st.info("Upload a screenshot to continue.")
    st.stop()

img = Image.open(uploaded).convert("RGB")
st.image(img, caption="Uploaded image", use_column_width=True)

# Quick local OCR preview
st.subheader("Local OCR preview")
raw_text = pytesseract.image_to_string(img)
st.text_area("Raw OCR output", raw_text, height=200)

# Quick heuristic parse preview
def quick_parse(text):
    t = re.sub(r'\s+', ' ', text).strip()
    if re.search(r'answer\s*[:\-]', t, flags=re.IGNORECASE):
        parts = re.split(r'answer\s*[:\-]\s*', t, flags=re.IGNORECASE)
        return parts[0].strip(), parts[1].strip() if len(parts) > 1 else None
    if "=" in t:
        parts = t.split("=")
        return parts[0].strip(), "=".join(parts[1:]).strip()
    fr = re.findall(r'\d+\s*/\s*\d+', t)
    if fr:
        return " ".join(fr), None
    nums = re.findall(r'\d+', t)
    if len(nums) >= 2:
        return f"{nums[0]} × {nums[1]}", (nums[2] if len(nums) >= 3 else None)
    return t, None

q_preview, a_preview = quick_parse(raw_text)
st.write("Parsed preview question:", q_preview or "None")
st.write("Parsed preview student answer:", a_preview or "None")

st.markdown("---")
st.subheader("Edit before sending (optional)")
q_override = st.text_input("Question (edit if OCR is wrong)", value=q_preview or "")
a_override = st.text_input("Student answer (edit if OCR missed it)", value=a_preview or "")

st.markdown("---")
st.subheader("Send to backend")
if not backend_url:
    st.warning("Set a backend endpoint URL above.")
else:
    if st.button("Send image to backend"):
        files = {"file": (uploaded.name, uploaded.getvalue(), uploaded.type)}
        data = {"question_override": q_override, "answer_override": a_override}
        headers = {}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        try:
            resp = requests.post(backend_url, files=files, data=data, headers=headers, timeout=60)
            resp.raise_for_status()
            result = resp.json()
            st.success("Backend returned a response.")
            st.json(result)

            st.markdown("---")
            st.subheader("Result summary")
            st.write("**Question:**", result.get("question") or "None")
            st.write("**Student answer:**", result.get("student_answer") or "None")
            correct = result.get("correct")
            if correct is True:
                st.success("✅ Student answer is correct")
            elif correct is False:
                st.error("❌ Student answer is incorrect")
            else:
                st.info("⚠️ Could not determine correctness automatically")
            if result.get("correct_answer"):
                st.write("**Correct answer:**", result.get("correct_answer"))
            if result.get("explanation"):
                st.subheader("Explanation")
                expl = result.get("explanation")
                if isinstance(expl, list):
                    for line in expl:
                        st.write("-", line)
                else:
                    st.write(expl)
        except Exception as e:
            st.error(f"Error sending to backend: {e}")
