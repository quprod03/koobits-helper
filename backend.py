# backend.py
from fastapi import FastAPI, File, UploadFile, Form, HTTPException
from fastapi.responses import JSONResponse
import uvicorn
from PIL import Image
import pytesseract
import io, os, re, json
from fractions import Fraction
import requests

# Optional: OpenAI / Azure OpenAI client usage
# This example uses the OpenAI REST chat completions endpoint.
# For Azure OpenAI, set AZURE_OPENAI_ENDPOINT and AZURE_OPENAI_KEY and use the Azure endpoint format.

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
AZURE_OPENAI_ENDPOINT = os.getenv("AZURE_OPENAI_ENDPOINT")  # e.g., https://your-resource.openai.azure.com/
AZURE_OPENAI_KEY = os.getenv("AZURE_OPENAI_KEY")
AZURE_DEPLOYMENT_NAME = os.getenv("AZURE_DEPLOYMENT_NAME")  # model deployment name

app = FastAPI(title="Koobits-forwarding backend")

def extract_numbers(text):
    return [int(n) for n in re.findall(r'\d+', text)]

def extract_fractions(text):
    return re.findall(r'\d+\s*/\s*\d+', text)

def quick_parse(text):
    t = re.sub(r'\s+', ' ', text).strip()
    if re.search(r'answer\s*[:\-]', t, flags=re.IGNORECASE):
        parts = re.split(r'answer\s*[:\-]\s*', t, flags=re.IGNORECASE)
        return parts[0].strip(), parts[1].strip() if len(parts) > 1 else None
    if "=" in t:
        parts = t.split("=")
        return parts[0].strip(), "=".join(parts[1:]).strip()
    fr = extract_fractions(t)
    if fr:
        return " ".join(fr), None
    nums = extract_numbers(t)
    if len(nums) >= 2:
        return f"{nums[0]} × {nums[1]}", (nums[2] if len(nums) >= 3 else None)
    return t, None

def evaluate_simple(question, student_answer):
    try:
        if re.search(r'\d+\s*/\s*\d+', question):
            fracs = extract_fractions(question)
            frac_objs = [(f, Fraction(*map(int, re.findall(r'\d+', f)))) for f in fracs]
            smallest = min(frac_objs, key=lambda x: x[1])
            correct = smallest[0]
            ok = None
            if student_answer:
                m = re.search(r'(\d+\s*/\s*\d+)', student_answer)
                if m:
                    stud = Fraction(*map(int, re.findall(r'\d+', m.group(1))))
                    ok = (stud == smallest[1])
            return ok, correct, [f"Compared: {', '.join([f for f,_ in frac_objs])}", f"Smallest: {correct}"]
        if "×" in question or "x" in question:
            nums = extract_numbers(question)
            if len(nums) >= 2:
                correct = nums[0] * nums[1]
                ok = None
                if student_answer and re.search(r'\d+', student_answer):
                    ok = int(re.search(r'\d+', student_answer).group()) == correct
                return ok, str(correct), [f"Computed {nums[0]} × {nums[1]} = {correct}"]
        if re.search(r'\d+\s*[\+\-]\s*\d+', question):
            nums = extract_numbers(question)
            if len(nums) >= 2:
                if "+" in question:
                    correct = nums[0] + nums[1]
                else:
                    correct = nums[0] - nums[1]
                ok = None
                if student_answer and re.search(r'-?\d+', student_answer):
                    ok = int(re.search(r'-?\d+', student_answer).group()) == correct
                return ok, str(correct), [f"Computed result = {correct}"]
    except Exception:
        pass
    return None, None, ["Could not evaluate with simple rules"]

def call_llm_openai(prompt, api_key=None):
    # Uses OpenAI Chat Completions (replace with your Copilot/Azure call if needed)
    key = api_key or OPENAI_API_KEY
    if not key:
        return None
    url = "https://api.openai.com/v1/chat/completions"
    headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
    payload = {
        "model": "gpt-4o-mini",  # choose a model you have access to
        "messages": [
            {"role": "system", "content": "You are a helpful assistant that extracts math question and student answer from OCR text and checks correctness. Return JSON."},
            {"role": "user", "content": prompt}
        ],
        "temperature": 0.0,
        "max_tokens": 800
    }
    r = requests.post(url, headers=headers, json=payload, timeout=30)
    if r.status_code != 200:
        return None
    j = r.json()
    # Extract assistant text
    return j["choices"][0]["message"]["content"]

def call_llm_azure(prompt, api_key=None, endpoint=None, deployment=None):
    key = api_key or AZURE_OPENAI_KEY
    ep = endpoint or AZURE_OPENAI_ENDPOINT
    dep = deployment or AZURE_DEPLOYMENT_NAME
    if not (key and ep and dep):
        return None
    url = f"{ep}/openai/deployments/{dep}/chat/completions?api-version=2023-10-01-preview"
    headers = {"api-key": key, "Content-Type": "application/json"}
    payload = {
        "messages": [
            {"role": "system", "content": "You are a helpful assistant that extracts math question and student answer from OCR text and checks correctness. Return JSON."},
            {"role": "user", "content": prompt}
        ],
        "temperature": 0.0,
        "max_tokens": 800
    }
    r = requests.post(url, headers=headers, json=payload, timeout=30)
    if r.status_code != 200:
        return None
    j = r.json()
    return j["choices"][0]["message"]["content"]

@app.post("/parse")
async def parse_image(file: UploadFile = File(...), question_override: str = Form(None), answer_override: str = Form(None), llm_provider: str = Form(None), llm_api_key: str = Form(None)):
    try:
        contents = await file.read()
        img = Image.open(io.BytesIO(contents)).convert("RGB")
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid image: {e}")

    raw_text = pytesseract.image_to_string(img)
    q_parsed, a_parsed = quick_parse(raw_text)
    question = (question_override.strip() if question_override else (q_parsed or "")).strip()
    student_answer = (answer_override.strip() if answer_override else (a_parsed or None))

    ok, correct_answer, explanation = evaluate_simple(question, student_answer)

    # If simple rules couldn't decide, call LLM
    if ok is None and (correct_answer is None):
        prompt = (
            "Extract the math question and the student's answer from the OCR text below. "
            "Return a JSON object with keys: question (string), student_answer (string or null), "
            "correct (true/false/null), correct_answer (string or null), explanation (array of strings).\n\n"
            f"OCR_TEXT:\n{raw_text}\n\n"
            "If you cannot determine correctness, set correct to null and provide best guess in explanation."
        )
        llm_text = None
        if llm_provider == "azure":
            llm_text = call_llm_azure(prompt, api_key=llm_api_key)
        else:
            llm_text = call_llm_openai(prompt, api_key=llm_api_key)
        if llm_text:
            # Try to parse JSON from LLM response
            try:
                # LLM may return JSON or text; attempt to find JSON substring
                json_start = llm_text.find("{")
                json_end = llm_text.rfind("}")
                if json_start != -1 and json_end != -1:
                    json_blob = llm_text[json_start:json_end+1]
                    parsed = json.loads(json_blob)
                    return JSONResponse(content=parsed)
            except Exception:
                # fallback: return LLM text in explanation
                return JSONResponse(content={
                    "question": question,
                    "student_answer": student_answer,
                    "correct": None,
                    "correct_answer": None,
                    "explanation": [llm_text]
                })

    # Return simple-eval result
    return JSONResponse(content={
        "question": question,
        "student_answer": student_answer,
        "correct": ok,
        "correct_answer": correct_answer,
        "explanation": explanation
    })

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
