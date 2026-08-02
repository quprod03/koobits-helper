import streamlit as st
from PIL import Image
import pytesseract
import re
from fractions import Fraction

# --- Helpers ---
def extract_numbers(text):
    return [int(n) for n in re.findall(r'\d+', text)]

def extract_fractions(text):
    return re.findall(r'\d+\s*/\s*\d+', text)

def parse_fraction(frac_str):
    nums = re.findall(r'\d+', frac_str)
    return Fraction(int(nums[0]), int(nums[1]))

def clean_lines(text):
    lines = [ln.strip() for ln in text.splitlines()]
    # remove obvious UI noise lines
    cleaned = []
    for ln in lines:
        if not ln:
            continue
        low = ln.lower()
        if any(skip in low for skip in ["koobits", "student.koobits", "edge_all_open_tabs", "streamlit", "multiplayer", "peer-challenge", "pageurl", "pagetitle"]):
            continue
        cleaned.append(ln)
    return cleaned

def pretty_join(lines):
    return " ".join(lines).strip()

# --- Explanation helpers ---
def explain_addition(num1, num2):
    tens1, ones1 = divmod(num1, 10)
    tens2, ones2 = divmod(num2, 10)
    steps = []
    steps.append(f"Step 1: Add the ones → {ones1} + {ones2} = {ones1 + ones2}")
    if ones1 + ones2 >= 10:
        steps.append("Step 2: Carry 1 to the tens.")
        carry = 1
        ones_sum = (ones1 + ones2) % 10
    else:
        carry = 0
        ones_sum = ones1 + ones2
    steps.append(f"Step 3: Add the tens → {tens1} + {tens2} + carry {carry} = {tens1 + tens2 + carry}")
    total = (tens1 + tens2 + carry) * 10 + ones_sum
    steps.append(f"Final Answer: {total}")
    return steps

def explain_subtraction(num1, num2):
    tens1, ones1 = divmod(num1, 10)
    tens2, ones2 = divmod(num2, 10)
    steps = []
    if ones1 < ones2:
        steps.append(f"Step 1: Borrow from tens → {tens1} becomes {tens1-1}, ones become {ones1+10}")
        ones1 += 10
        tens1 -= 1
    steps.append(f"Step 2: Subtract ones → {ones1} - {ones2} = {ones1 - ones2}")
    steps.append(f"Step 3: Subtract tens → {tens1} - {tens2} = {tens1 - tens2}")
    total = (tens1 - tens2) * 10 + (ones1 - ones2)
    steps.append(f"Final Answer: {total}")
    return steps

def explain_multiplication(num1, num2):
    steps = []
    steps.append(f"Step 1: Multiply → {num1} × {num2} = {num1 * num2}")
    steps.append(f"Final Answer: {num1 * num2}")
    return steps

# --- Streamlit UI ---
st.title("Koobits Screenshot Helper")

uploaded_file = st.file_uploader("Upload Koobits Screenshot", type=["png", "jpg", "jpeg"])
if not uploaded_file:
    st.info("Upload a screenshot from Koobits and the app will try to detect the question and answer.")
else:
    img = Image.open(uploaded_file)
    st.image(img, caption="Uploaded Screenshot", use_column_width=True)

    raw_text = pytesseract.image_to_string(img)
    st.subheader("OCR Detected")
    st.text_area("Raw OCR output", raw_text, height=200)

    # Clean and focus OCR lines
    lines = clean_lines(raw_text)
    joined = pretty_join(lines)
    st.write("Filtered OCR:", joined)

    # Try multiple parsing strategies
    question_text = None
    student_answer_text = None
    detected_mode = None  # "equals", "answer_colon", "multiplication", "fractions", "arithmetic", "unknown"

    # 1) If there's an explicit "Answer:" use that
    if "answer:" in joined.lower():
        parts = re.split(r'answer\s*:', joined, flags=re.IGNORECASE)
        question_text = parts[0].strip()
        student_answer_text = parts[1].strip() if len(parts) > 1 else None
        detected_mode = "answer_colon"

    # 2) If there's an '=' sign
    elif "=" in joined:
        parts = joined.split("=")
        question_text = parts[0].strip()
        student_answer_text = parts[1].strip() if len(parts) > 1 else None
        detected_mode = "equals"

    # 3) Multiplication layout detection (look for × or 'multiply' or 'x' between numbers)
    elif re.search(r'×|multiply', joined, flags=re.IGNORECASE) or re.search(r'\b\d+\s*x\s*\d+\b', joined, flags=re.IGNORECASE):
        detected_mode = "multiplication"
        # try to extract numbers in order of appearance
        nums = extract_numbers(joined)
        if len(nums) >= 2:
            # assume first two are multiplicand and multiplier
            question_text = f"{nums[0]} × {nums[1]}"
            # try to find a candidate answer line (a number that appears after the multiplication lines)
            # look for any standalone numeric line in the cleaned lines after the line containing multiply/x
            mul_line_index = None
            for i, ln in enumerate(lines):
                if re.search(r'×|multiply', ln, flags=re.IGNORECASE) or re.search(r'\b\d+\s*x\s*\d+\b', ln, flags=re.IGNORECASE):
                    mul_line_index = i
                    break
            candidate = None
            if mul_line_index is not None:
                for ln in lines[mul_line_index + 1:]:
                    nums_ln = extract_numbers(ln)
                    if nums_ln:
                        candidate = str(nums_ln[0])
                        break
            # fallback: if OCR included the product in the same joined text, try last number
            if not candidate and len(nums) >= 3:
                candidate = str(nums[2])
            student_answer_text = candidate

    # 4) Fractions list detection
    elif re.search(r'\d+\s*/\s*\d+', joined):
        detected_mode = "fractions"
        fracs = extract_fractions(joined)
        # question_text: list of fractions
        question_text = " ".join(fracs)
        # try to get answer after "Answer:" earlier would have caught it; try to find a fraction-like token after the list
        # search raw text for 'answer' line separately
        m = re.search(r'answer\s*[:\-]?\s*([0-9]+\s*/\s*[0-9]+|\d+)', raw_text, flags=re.IGNORECASE)
        if m:
            student_answer_text = m.group(1).strip()
        else:
            # maybe OCR wrote "Answer: 2/18" but filtered; try to find any fraction in the later lines
            if len(fracs) > 0:
                # no student answer found; leave None to allow manual input
                student_answer_text = None

    # 5) Simple arithmetic detection (+ or -)
    elif re.search(r'\d+\s*[\+\-]\s*\d+', joined):
        detected_mode = "arithmetic"
        m = re.search(r'(\d+\s*[\+\-]\s*\d+)', joined)
        if m:
            question_text = m.group(1).strip()
            # try to find answer after equals or on next numeric line
            if "=" in joined:
                parts = joined.split("=")
                if len(parts) > 1:
                    student_answer_text = parts[1].strip()
            else:
                # look for a numeric line after the arithmetic line
                arith_line_index = None
                for i, ln in enumerate(lines):
                    if re.search(r'\d+\s*[\+\-]\s*\d+', ln):
                        arith_line_index = i
                        break
                if arith_line_index is not None:
                    for ln in lines[arith_line_index + 1:]:
                        nums_ln = extract_numbers(ln)
                        if nums_ln:
                            student_answer_text = str(nums_ln[0])
                            break

    else:
        detected_mode = "unknown"
        question_text = joined
        student_answer_text = None

    st.write("Detected mode:", detected_mode)
    st.write("Parsed question:", question_text)
    st.write("Parsed student answer (if any):", student_answer_text or "None")

    # Provide manual override inputs so the user can correct OCR if needed
    st.markdown("---")
    st.subheader("Manual overrides (use if OCR is wrong)")
    q_override = st.text_input("Question (edit if OCR parsed it incorrectly)", value=question_text or "")
    a_override = st.text_input("Student answer (type if OCR missed it)", value=student_answer_text or "")

    # Use overrides if provided
    question_text = q_override.strip() if q_override.strip() else question_text
    student_answer_text = a_override.strip() if a_override.strip() else student_answer_text

    # Final evaluation
    st.markdown("---")
    st.subheader("Result")

    if not question_text:
        st.warning("No question detected. Please type the question in the override box above.")
    else:
        try:
            # Multiplication
            if detected_mode == "multiplication" or re.search(r'×|\bx\b|\bmultiply\b', question_text, flags=re.IGNORECASE):
                nums = extract_numbers(question_text)
                if len(nums) >= 2:
                    num1, num2 = nums[0], nums[1]
                    correct = num1 * num2
                    st.write(f"Computed correct answer: **{correct}**")
                    if student_answer_text and re.search(r'\d+', student_answer_text):
                        if int(re.search(r'\d+', student_answer_text).group()) == correct:
                            st.success("✅ Correct!")
                        else:
                            st.error("❌ Wrong")
                            for s in explain_multiplication(num1, num2):
                                st.write(s)
                    else:
                        st.info("No student answer detected. You can type it in the override box above.")
                else:
                    st.warning("Could not extract two numbers for multiplication. Please edit the question manually.")

            # Fractions
            elif detected_mode == "fractions" or re.search(r'\d+\s*/\s*\d+', question_text):
                fracs = extract_fractions(question_text)
                if not fracs:
                    st.warning("No fractions found to compare. Please edit the question manually.")
                else:
                    frac_objs = [(f, parse_fraction(f)) for f in fracs]
                    smallest = min(frac_objs, key=lambda x: x[1])
                    st.write("Fractions detected:", ", ".join([f for f, _ in frac_objs]))
                    st.write(f"Smallest fraction is **{smallest[0]}** (value {float(smallest[1])})")
                    if student_answer_text:
                        # normalize student answer to fraction if possible
                        m_frac = re.search(r'(\d+\s*/\s*\d+)', student_answer_text)
                        if m_frac:
                            stud_frac = parse_fraction(m_frac.group(1))
                            if stud_frac == smallest[1]:
                                st.success("✅ Correct!")
                            else:
                                st.error("❌ Wrong")
                                st.write(f"Correct answer: {smallest[0]}")
                        else:
                            # maybe student typed a simplified numeric like 0.11
                            try:
                                stud_val = float(student_answer_text)
                                if abs(stud_val - float(smallest[1])) < 1e-6:
                                    st.success("✅ Correct!")
                                else:
                                    st.error("❌ Wrong")
                                    st.write(f"Correct answer: {smallest[0]}")
                            except:
                                st.info("Student answer not recognized as a fraction or number. Please edit it in the override box.")
                    else:
                        st.info("No student answer detected. You can type it in the override box above.")

            # Addition / Subtraction / Simple arithmetic
            elif re.search(r'\d+\s*[\+\-]\s*\d+', question_text):
                nums = extract_numbers(question_text)
                if len(nums) >= 2:
                    if "+" in question_text:
                        num1, num2 = nums[0], nums[1]
                        correct = num1 + num2
                        st.write(f"Computed correct answer: **{correct}**")
                        if student_answer_text and re.search(r'\d+', student_answer_text):
                            if int(re.search(r'\d+', student_answer_text).group()) == correct:
                                st.success("✅ Correct!")
                            else:
                                st.error("❌ Wrong")
                                for s in explain_addition(num1, num2):
                                    st.write(s)
                        else:
                            st.info("No student answer detected. You can type it in the override box above.")
                    else:
                        num1, num2 = nums[0], nums[1]
                        correct = num1 - num2
                        st.write(f"Computed correct answer: **{correct}**")
                        if student_answer_text and re.search(r'-?\d+', student_answer_text):
                            if int(re.search(r'-?\d+', student_answer_text).group()) == correct:
                                st.success("✅ Correct!")
                            else:
                                st.error("❌ Wrong")
                                for s in explain_subtraction(num1, num2):
                                    st.write(s)
                        else:
                            st.info("No student answer detected. You can type it in the override box above.")
                else:
                    st.warning("Could not extract two numbers for arithmetic. Please edit the question manually.")

            # Fallback: try to evaluate a single-line numeric expression or show correct answer
            else:
                # try to extract a simple numeric expression like "35 * 4" or "35 4 140"
                nums = extract_numbers(question_text)
                if len(nums) == 1 and student_answer_text:
                    st.write("Single number detected in question; showing student answer for review.")
                    st.write("Student answer:", student_answer_text)
                    st.info("If you want the app to check correctness, edit the question to a clear expression (e.g., '35 × 4').")
                elif len(nums) >= 2:
                    # try to guess operation: if any '×' or 'x' present treat as multiply, else if 'multiply' present, multiply, else if plus/minus present handle
                    if re.search(r'×|\bx\b|\bmultiply\b', question_text, flags=re.IGNORECASE):
                        num1, num2 = nums[0], nums[1]
                        correct = num1 * num2
                        st.write(f"Computed correct answer: **{correct}**")
                        if student_answer_text and re.search(r'\d+', student_answer_text):
                            if int(re.search(r'\d+', student_answer_text).group()) == correct:
                                st.success("✅ Correct!")
                            else:
                                st.error("❌ Wrong")
                                for s in explain_multiplication(num1, num2):
                                    st.write(s)
                        else:
                            st.info("No student answer detected. You can type it in the override box above.")
                    else:
                        st.info("Multiple numbers detected but operation unclear. Please edit the question to a clear expression (e.g., '35 + 4' or '35 × 4').")
                else:
                    st.info("Could not determine a solvable math expression from OCR. Use the manual override boxes to correct the question and answer.")
        except Exception as e:
            st.warning(f"Error while solving: {e}")
