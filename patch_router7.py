with open("backend/app/llm/router.py", "r", encoding="utf-8") as f:
    text = f.read()

text = text.replace(
    'healthy_workers.sort(key=lambda x: x.get("priority", 0), reverse=True)',
    'healthy_workers.sort(key=lambda x: (-x.get("priority", 0), x.get("last_used_at", 0)))'
)

credential_logic = '''        w_prov = w["provider"]
        api_key = w.get("api_key")
        credential_env = w.get("credential_env")
        if credential_env and credential_env in os.environ:
            api_key = os.environ[credential_env]
'''

text = text.replace(
    '        w_prov = w["provider"]\n        api_key = w.get("api_key")',
    credential_logic
)

with open("backend/app/llm/router.py", "w", encoding="utf-8") as f:
    f.write(text)
