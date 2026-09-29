with open("backend/app/api/workers.py", "r", encoding="utf-8") as f:
    text = f.read()

text = text.replace('    api_key: str', '    api_key: str = ""\n    credential_env: str = ""')
text = text.replace('    api_key: Optional[str] = None', '    api_key: Optional[str] = None\n    credential_env: Optional[str] = None')

with open("backend/app/api/workers.py", "w", encoding="utf-8") as f:
    f.write(text)
