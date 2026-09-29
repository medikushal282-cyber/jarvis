import re

with open("backend/app/llm/router.py", "r", encoding="utf-8") as f:
    text = f.read()

replacement = 'print(f"LLM_REQUEST: worker_id={worker_id}, provider={prov}, model={model_str}, run_id={run_id}, turn={turn_idx}, prompt_tokens={p_tokens}, completion_tokens={c_tokens}, total_tokens={t_tokens}, duration_ms={duration_ms}, success={success}, rate_limit={rate_limit}")'
text = re.sub(r'logger\.info\(\s*"LLM_REQUEST:.*?rate_limit\s*\)', replacement, text, flags=re.DOTALL)

with open("backend/app/llm/router.py", "w", encoding="utf-8") as f:
    f.write(text)
