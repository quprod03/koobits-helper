import streamlit as st
from PIL import Image
import pytesseract
import re
from sympy import sympify

# --- Helper to safely extract numbers ---
def extract_numbers(text):
    # Find all sequences of digits in the text
    return [int(n) for n in re.findall(r'\d+', text)]

# --- Explanation helpers ---
def explain_addition(num1, num2):
    tens1, ones1 = divmod(num1, 10)
    tens2, ones2 = divmod(num2, 10)
    steps = []
    steps.append(f"Step 1: Add the ones → {ones1} + {ones2} = {ones1 + ones2}")
    if ones1 + ones2 >= 10:
        steps.append("Step 2: Since the ones are 10 or more, carry over 1 to the tens.")
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

uploaded_file = st.file_uploader("Upload Koobits Screenshot", type=["png","jpg","jpeg"])
if uploaded_file:
    img = Image.open(uploaded_file)
    st.image(img, caption="Uploaded Screenshot", use_column_width=True)
    text = pytesseract.image_to_string(img).strip()
    st.write("OCR Detected:", text)

    question = None
    student_answer = None

    # --- Flexible parsing ---
    if "=" in text:
        parts = text.split("=")
        question = parts[0].strip()
        student_answer = parts[1].strip()
    elif "Answer:" in text:
        parts = text.split("Answer:")
        question = parts[0].strip()
        student_answer = parts[1].strip()
    else:
        question = text.strip()
        student_answer = None
        st.warning("OCR did not detect an answer. Please type it below.")

    # --- Manual input fallback ---
    if student_answer is None:
        student_answer = st.text_input("Enter your answer manually:")

    # --- Answer checking ---
    if question:
        try:
            if "×" in question or "x" in question:
                nums = extract_numbers(question)
                if len(nums) >= 2:
                    num1, num2 = nums[0], nums[1]
                    correct_answer = num1 * num2
                    if student_answer and student_answer.isdigit() and int(student_answer) == correct_answer:
                        st.success("✅ Correct!")
                    else:
                        st.error("❌ Wrong")
                        steps = explain_multiplication(num1, num2)
                        for step in steps:
                            st.write(step)
            elif "+" in question:
                nums = extract_numbers(question)
                if len(nums) >= 2:
                    num1, num2 = nums[0], nums[1]
                    correct_answer = num1 + num2
                    if student_answer and student_answer.isdigit() and int(student_answer) == correct_answer:
                        st.success("✅ Correct!")
                    else:
                        st.error("❌ Wrong")
                        steps = explain_addition(num1, num2)
                        for step in steps:
                            st.write(step)
            elif "-" in question:
                nums = extract_numbers(question)
                if len(nums) >= 2:
                    num1, num2 = nums[0], nums[1]
                    correct_answer = num1 - num2
                    if student_answer and student_answer.isdigit() and int(student_answer) == correct_answer:
                        st.success("✅ Correct!")
                    else:
                        st.error("❌ Wrong")
                        steps = explain_subtraction(num1, num2)
                        for step in steps:
                            st.write(step)
            else:
                # Fallback to sympy for fractions or other math
                correct_answer = sympify(question).evalf()
                if student_answer:
                    try:
                        if float(student_answer) == float(correct_answer):
                            st.success("✅ Correct!")
                        else:
                            st.error("❌ Wrong")
                            st.write(f"Correct answer is {correct_answer}, your answer was {student_answer}.")
                    except:
                        st.write(f"Correct answer is {correct_answer}, your answer was {student_answer}.")
                else:
                    st.info(f"OCR detected only the question: {question}. Correct answer is {correct_answer}.")
        except Exception as e:
            st.warning(f"Error while solving: {e}")
