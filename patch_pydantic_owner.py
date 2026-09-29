with open("backend/app/api/workers.py", "r", encoding="utf-8") as f:
    text = f.read()

text = text.replace('    priority: Optional[int] = 1', '    priority: Optional[int] = 1\n    owner: Optional[str] = ""')

with open("backend/app/api/workers.py", "w", encoding="utf-8") as f:
    f.write(text)
