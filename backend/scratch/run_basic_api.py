import requests
import json
import time
import sys

# 1. Run agent
try:
    r = requests.post('http://localhost:8006/api/runs/', json={
        'objective': 'Create a file called hello.txt containing Hello JARVIS.'
    })
    r.raise_for_status()
    run_id = r.json()['run_id']
    print(flush=True, f'Run ID: {run_id}')
except Exception as e:
    print(flush=True, 'Failed to start run:', e)
    if 'r' in locals():
        print(flush=True, r.text)
    sys.exit(1)

# 2. Poll for completion
while True:
    try:
        r = requests.get(f'http://localhost:8006/api/runs/{run_id}')
        if r.status_code == 200:
            status = r.json().get('status')
            print(flush=True, f'Status: {status}')
            if status in ['completed', 'failed', 'cancelled']:
                print(flush=True, json.dumps(r.json(), indent=2))
                break
        else:
            print(flush=True, f'Get run failed: {r.status_code} {r.text}')
    except Exception as e:
        print(flush=True, 'Poll error:', e)
    time.sleep(2)
