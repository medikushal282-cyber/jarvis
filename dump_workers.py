import json
import time

try:
    with open('backend/data/workers.json', 'r') as f:
        workers = json.load(f)
    print('WORKERS.JSON:')
    now = time.time()
    for w in workers:
        print(f"worker_id: {w.get('worker_id')}, provider: {w.get('provider')}, model: {w.get('model')}, enabled: {w.get('enabled')}, priority: {w.get('priority')}, cooldown_until: {w.get('cooldown_until')} (now={now})")
except Exception as e:
    print('Error loading workers:', e)
