with open("backend/app/llm/workers.py", "r", encoding="utf-8") as f:
    text = f.read()

# Add credential_env support to add_worker
text = text.replace('"api_key": data.get("api_key", ""),', '"api_key": data.get("api_key", ""),\n        "credential_env": data.get("credential_env", ""),')

# Add credential_env support to update_worker
text = text.replace('if "api_key" in data and data["api_key"].strip():', 'if "credential_env" in data:\n                w["credential_env"] = data["credential_env"].strip()\n            if "api_key" in data and data["api_key"].strip():')

# Mask credential_env in get_public_workers
text = text.replace('# Remove raw key before returning to UI\n        w.pop("api_key", None)', '# Remove raw key before returning to UI\n        w.pop("api_key", None)\n        w.pop("credential_env", None)')

with open("backend/app/llm/workers.py", "w", encoding="utf-8") as f:
    f.write(text)
