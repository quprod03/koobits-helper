import streamlit as st
from PIL import Image
import pytesseract
from sympy import sympify

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

st.title("Koobits Screenshot Helper")

uploaded_file = st.file_uploader("Upload Koobits Screenshot", type=["png","jpg","jpeg"])
if uploaded_file:
    img = Image.open(uploaded_file)
    st.image(img, caption="Uploaded Screenshot", use_column_width=True)
    text = pytesseract.image_to_string(img).strip()
    st.write("OCR Detected:", text)

    if "=" in text:
        question, student_answer = text.split("=")
        question = question.strip()
        student_answer = student_answer.strip()
        try:
            correct_answer = sympify(question).evalf()
            if float(student_answer) == float(correct_answer):
                st.success("✅ Correct!")
            else:
                st.error("❌ Wrong")
                if "+" in question:
                    num1, num2 = map(int, question.split("+"))
                    steps = explain_addition(num1, num2)
                elif "-" in question:
                    num1, num2 = map(int, question.split("-"))
                    steps = explain_subtraction(num1, num2)
                else:
                    steps = [f"Correct answer is {correct_answer}, your answer was {student_answer}."]
                for step in steps:
                    st.write(step)
        except Exception as e:
            st.warning(f"Error: {e}")
    else:
        st.warning("Could not detect question and answer format")
