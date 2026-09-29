import re

with open("backend/app/llm/router.py", "r", encoding="utf-8") as f:
    text = f.read()

new_fallback = '''    if not workers:
        # Fallback to standard environment keys if NO workers configured at all
        try:
            raw_response = call_litellm(system, user, model, provider, tools=tools, run_id=run_id, turn_idx=turn_idx)
            return extract_thoughts(raw_response)
        except Exception as e:
            err_str = str(e).lower()
            if any(k in err_str for k in ["rate_limit", "429", "too many requests"]):
                import re
                cooldown_s = 30
                try:
                    match = re.search(r'try again in (\\d+\\.?\\d*)s', err_str)
                    if match:
                        cooldown_s = int(float(match.group(1))) + 2
                except Exception:
                    pass
                    
                if 0 < cooldown_s <= 60:
                    if emit:
                        emit("worker_switching", {"message": f"Rate limited. Waiting {cooldown_s}s for retry-after to expire before trying again..."}, node="agent")
                    logger.info(f"Fallback rate limited. Waiting {cooldown_s}s.")
                    import time
                    time.sleep(cooldown_s)
                    try:
                        raw_response = call_litellm(system, user, model, provider, tools=tools, run_id=run_id, turn_idx=turn_idx)
                        if emit:
                            emit("worker_connected", {"message": "Resumed successfully after rate limit cooldown."}, node="agent")
                        return extract_thoughts(raw_response)
                    except Exception as retry_e:
                        raise Exception(f"LLM provider error (after rate-limit retry): {retry_e}")
                
            raise Exception(f"LLM provider error: {e}")'''

# Replace the old fallback block
old_fallback = '''    if not workers:
        # Fallback to standard environment keys if NO workers configured at all
        try:
            raw_response = call_litellm(system, user, model, provider, tools=tools, run_id=run_id, turn_idx=turn_idx)
            return extract_thoughts(raw_response)
        except Exception as e:
            raise Exception(f"LLM provider error: {e}")'''

text = text.replace(old_fallback, new_fallback)

with open("backend/app/llm/router.py", "w", encoding="utf-8") as f:
    f.write(text)
