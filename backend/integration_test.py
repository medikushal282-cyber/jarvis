import urllib.request
import json
import time
import uuid
import sys

def run_test(objective):
    print(f"\n--- RUNNING OBJECTIVE: {objective} ---")
    data = {
        'objective': objective,
        'model': 'openai/gpt-oss-120b',
        'provider': 'groq'
    }
    req = urllib.request.Request('http://localhost:8006/api/runs/', data=json.dumps(data).encode('utf-8'), headers={'Content-Type': 'application/json'})
    
    try:
        with urllib.request.urlopen(req) as response:
            res_data = json.loads(response.read().decode('utf-8'))
            run_id = res_data.get("run_id")
            print(f"Started run: {run_id}")
    except Exception as e:
        print("Failed to start run:", e)
        return
        
    # Poll events
    events_url = f'http://localhost:8006/api/runs/{run_id}/events'
    req_ev = urllib.request.Request(events_url)
    try:
        with urllib.request.urlopen(req_ev) as res_ev:
            while True:
                line = res_ev.readline()
                if not line: break
                line_str = line.decode('utf-8').strip()
                if line_str.startswith("data: "):
                    ev_data = json.loads(line_str[6:])
                    ev_type = ev_data.get("event")
                    if ev_type == "run_completed":
                        print("SUCCESS:", ev_data.get("data", {}).get("reply"))
                        return
                    elif ev_type == "run_failed":
                        print("FAILED:", ev_data.get("data", {}).get("message"))
                        return
                    elif ev_type == "worker_switching":
                        print("SWITCHING WORKER:", ev_data.get("data", {}).get("message"))
                    elif ev_type == "worker_cooldown":
                        print("COOLDOWN:", ev_data.get("data", {}))
                    elif ev_type == "tool_completed":
                        print("TOOL COMPLETED:", ev_data.get("data", {}).get("tool"))
    except Exception as e:
        print("Failed reading events:", e)

if __name__ == "__main__":
    objectives = [
        "Say hello.",
        "Create hello.txt containing Hello JARVIS.",
        "Read hello.txt.",
        "Create a small ecommerce website and inspect the generated files."
    ]
    for obj in objectives:
        run_test(obj)
        time.sleep(2)
