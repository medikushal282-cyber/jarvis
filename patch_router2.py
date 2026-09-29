import os
import re

with open("backend/app/llm/router.py", "r", encoding="utf-8") as f:
    text = f.read()

# Make sure time and logging are imported globally so tests can patch them
if "import time" not in text:
    text = "import time\nimport logging\n" + text

with open("backend/app/llm/router.py", "w", encoding="utf-8") as f:
    f.write(text)
