import re
with open('backend/tests/test_router_pool.py', 'r', encoding='utf-8') as f:
    text = f.read()

text = re.sub(r"@patch\('app\.llm\.router\.load_workers'\)\n", "", text)
text = re.sub(r"mock_load_r, ", "", text)
text = re.sub(r"    mock_load_r\.side_effect = loader\n", "", text)
text = re.sub(r"    mock_load_r\.side_effect = advancing_loader\n", "", text)
text = re.sub(r"    mock_load_r\.return_value = \[\]\n", "", text)

with open('backend/tests/test_router_pool.py', 'w', encoding='utf-8') as f:
    f.write(text)
