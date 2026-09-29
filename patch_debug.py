with open("backend/app/llm/router.py", "r", encoding="utf-8") as f:
    text = f.read()

text = text.replace('if 0 < wait_time <= 60:', 'logger.info(f"Evaluating wait_time: {wait_time} for retry.")\n                    if 0 < wait_time <= 60:')
text = text.replace('raise Exception("JARVIS couldn\'t complete this task because all configured execution workers are currently unavailable or rate-limited.")', 'raise Exception(f"JARVIS couldn\'t complete task. last_err: {last_err}")')

with open("backend/app/llm/router.py", "w", encoding="utf-8") as f:
    f.write(text)
