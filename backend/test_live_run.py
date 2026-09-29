import httpx
import json
import time

def main():
    client = httpx.Client(timeout=60)

    # 1. Post a real objective to the backend
    obj = "Calculate 25 * 25, create a file named result.txt with the answer, and tell me the result."
    print("===> 1. Dispatching Objective to backend (port 8006):", obj)
    res = client.post("http://localhost:8006/api/runs/", json={"objective": obj})
    print("HTTP POST Status:", res.status_code)
    run_data = res.json()
    print("Run Response:", run_data)
    run_id = run_data.get("run_id")
    if not run_id:
        print("ERROR: No run_id returned!")
        return

    # 2. Stream all SSE events
    print("\n===> 2. Listening to Live SSE Event Stream for run:", run_id)
    with client.stream("GET", f"http://localhost:8006/api/runs/{run_id}/events") as stream:
        for line in stream.iter_lines():
            if line.startswith("data:"):
                data_str = line[5:].strip()
                if data_str:
                    ev = json.loads(data_str)
                    ev_name = ev.get("event")
                    ev_node = ev.get("node", "agent")
                    ev_data = ev.get("data", {})
                    print(f"[{ev_node.upper()}] Event: {ev_name} | Data: {ev_data}")
                    if ev_name in ("run_completed", "run_failed"):
                        break

    # 3. Fetch final run result
    print("\n===> 3. Fetching Final Run Result:")
    res_final = client.get(f"http://localhost:8006/api/runs/{run_id}/result")
    print("Final Result HTTP Status:", res_final.status_code)
    if res_final.status_code == 200:
        result_json = res_final.json()
        print("Final Status:", result_json.get("status"))
        print("Objective:", result_json.get("objective"))
        print("Final Reply:", result_json.get("reply"))
        print("Summary:", result_json.get("summary"))
        print("Actions Count:", len(result_json.get("actions", [])))
        print("Files Created:", result_json.get("files_created", []))
    else:
        print("Raw result:", res_final.text)

if __name__ == "__main__":
    main()
