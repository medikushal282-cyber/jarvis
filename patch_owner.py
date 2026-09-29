with open("backend/app/llm/workers.py", "r", encoding="utf-8") as f:
    text = f.read()

text = text.replace('"worker_id": worker_id,', '"worker_id": worker_id,\n        "owner": data.get("owner", ""),')
text = text.replace('if "credential_env" in data:', 'if "owner" in data:\n                w["owner"] = data["owner"].strip()\n            if "credential_env" in data:')

with open("backend/app/llm/workers.py", "w", encoding="utf-8") as f:
    f.write(text)
