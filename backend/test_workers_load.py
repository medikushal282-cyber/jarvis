from app.llm.workers import load_workers
import time

workers = load_workers()
print("workers loaded:", len(workers))
now = time.time()
healthy_workers = [w for w in workers if w.get("enabled", True) and w.get("cooldown_until", 0) <= now]
print("healthy_workers:", len(healthy_workers))
for w in healthy_workers:
    print(w['worker_id'])
