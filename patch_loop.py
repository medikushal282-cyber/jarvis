with open("backend/app/agent/loop.py", "r", encoding="utf-8") as f:
    text = f.read()

text = text.replace('os.environ.get("JARVIS_MAX_AGENT_CONTEXT_TOKENS", "5500")', 'os.environ.get("JARVIS_MAX_AGENT_CONTEXT_TOKENS", "1500")')
text = text.replace('emit=emit,\n            )', 'emit=emit,\n                run_id=run_id,\n                turn_idx=turn_idx,\n            )')

with open("backend/app/agent/loop.py", "w", encoding="utf-8") as f:
    f.write(text)
