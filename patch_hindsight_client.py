import re

with open('backend/app/memory/hindsight/client.py', 'r') as f:
    text = f.read()

post_replacement = '''        if self.endpoint_url:
            import urllib.request
            try:
                data = {
                    "user_id": user_id,
                    "content": content,
                    "metadata": metadata,
                    "timestamp": time.time()
                }
                req = urllib.request.Request(
                    f"{self.endpoint_url}/api/v1/experiences",
                    data=json.dumps(data).encode("utf-8"),
                    headers={"Content-Type": "application/json"}
                )
                with urllib.request.urlopen(req, timeout=5.0) as res:
                    resp_data = json.loads(res.read().decode())
                    return resp_data.get("id", "")
            except Exception as e:
                logger.warning(f"Real Hindsight HTTP store failed, falling back to mock: {e}")'''

text = re.sub(
    r'if self\.endpoint_url:\s+# TODO: Implement real HTTP POST to Hindsight\s+logger\.info\("Real Hindsight HTTP store not fully implemented, using mock\."\)',
    post_replacement,
    text
)

get_replacement = '''        if self.endpoint_url:
            import urllib.request
            import urllib.parse
            try:
                params = {"user_id": user_id, "query": query, "limit": limit}
                if filters:
                    params["filters"] = json.dumps(filters)
                qs = urllib.parse.urlencode(params)
                req = urllib.request.Request(f"{self.endpoint_url}/api/v1/search?{qs}")
                with urllib.request.urlopen(req, timeout=5.0) as res:
                    resp_data = json.loads(res.read().decode())
                    return resp_data.get("results", [])
            except Exception as e:
                logger.warning(f"Real Hindsight HTTP search failed, falling back to mock: {e}")'''

text = re.sub(
    r'if self\.endpoint_url:\s+# TODO: Implement real HTTP GET to Hindsight\s+logger\.info\("Real Hindsight HTTP search not fully implemented, using mock\."\)',
    get_replacement,
    text
)

with open('backend/app/memory/hindsight/client.py', 'w') as f:
    f.write(text)
