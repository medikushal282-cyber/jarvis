with open("backend/app/api/workers.py", "r", encoding="utf-8") as f:
    text = f.read()

text = text.replace('    new_w.pop("api_key", None)', '    new_w.pop("api_key", None)\n    new_w.pop("credential_env", None)')
text = text.replace('    updated.pop("api_key", None)', '    updated.pop("api_key", None)\n    updated.pop("credential_env", None)')

with open("backend/app/api/workers.py", "w", encoding="utf-8") as f:
    f.write(text)
