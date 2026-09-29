import urllib.request
import json
import time

def run():
    print("Fetching initial workers...")
    req_get = urllib.request.Request('http://localhost:8006/api/workers')
    with urllib.request.urlopen(req_get) as res:
        initial = json.loads(res.read().decode())
        print(f"Initial: {len(initial)}")

    print("\nCreating worker with credential_env...")
    data = {
        "provider": "groq",
        "model": "llama-3.3-70b-versatile",
        "credential_env": "GROQ_API_KEY",
        "priority": 5,
        "owner": "IntegrationTest"
    }
    req_post = urllib.request.Request('http://localhost:8006/api/workers', data=json.dumps(data).encode('utf-8'), headers={'Content-Type': 'application/json'})
    
    worker_id = None
    with urllib.request.urlopen(req_post) as res:
        created = json.loads(res.read().decode())
        print("Created:", created)
        worker_id = created.get("worker_id")
        
        # Verify masks
        if "api_key" in created:
            print("ERROR: API key was returned!")
        if "credential_env" in created:
            print("ERROR: credential_env was returned!")
            
    print("\nFetching workers after creation...")
    with urllib.request.urlopen(req_get) as res:
        current = json.loads(res.read().decode())
        print(f"Current length: {len(current)}")
        for w in current:
            if w["worker_id"] == worker_id:
                print(f"Found our worker: {w['worker_id']}, owner: {w['owner']}, priority: {w['priority']}")
                if "api_key" in w or "credential_env" in w:
                    print("ERROR: Secure fields leaked in GET request!")
                    
    print("\nDeleting worker...")
    req_del = urllib.request.Request(f'http://localhost:8006/api/workers/{worker_id}', method='DELETE')
    with urllib.request.urlopen(req_del) as res:
        print("Deleted:", json.loads(res.read().decode()))
        
    print("\nFetching workers after deletion...")
    with urllib.request.urlopen(req_get) as res:
        final = json.loads(res.read().decode())
        print(f"Final length: {len(final)}")
        
if __name__ == '__main__':
    run()
