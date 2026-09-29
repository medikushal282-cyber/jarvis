with open("backend/app/llm/router.py", "r", encoding="utf-8") as f:
    text = f.read()

text = text.replace('if any(k in err_msg for k in ["rate_limit", "429", "timeout", "connection", "overloaded", "groqexception"]):', 'if any(k in err_msg for k in ["rate_limit", "429", "too many requests"]):')

with open("backend/app/llm/router.py", "w", encoding="utf-8") as f:
    f.write(text)
