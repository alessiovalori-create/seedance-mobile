import os, sys, requests, time, json

b = os.getenv("ARK_API_BASE", "https://ark.ap-southeast.bytepluses.com/api/v3")
k = os.getenv("ARK_API_KEY")
if len(sys.argv) < 2:
    print("USO: python3 fetch_task.py <task_id>")
    print("  es. python3 fetch_task.py cgt-abc123...")
    sys.exit(1)
t = sys.argv[1].strip()
if "TUO-TASK" in t.upper() or t.endswith("..."):
    print(f"[ERRORE] Task id placeholder: {t!r}")
    print("Sostituisci con l'id reale stampato da test_cut.py / generate_video.")
    sys.exit(1)
if not k:
    print("[ERRORE] ARK_API_KEY non impostata.")
    sys.exit(1)
h = {"Authorization": "Bearer " + k}
POLL_MAX = 120   # 120 × 6s ≈ 12 min (generate_video poll_max=120 × 5s)
POLL_SLEEP = 6
for i in range(POLL_MAX):
    r = requests.get(b + "/contents/generations/tasks/" + t, headers=h, timeout=30, verify=False)
    try:
        j = r.json()
    except Exception:
        print(f"HTTP {r.status_code} — risposta non-JSON: {r.text[:500]}")
        sys.exit(1)
    if r.status_code >= 400:
        err = j.get("error") or j
        print(f"HTTP {r.status_code}: {json.dumps(err, ensure_ascii=False)}")
        sys.exit(1)
    data = j.get("data") if isinstance(j.get("data"), dict) else j
    s = data.get("status")
    print(f"poll {i+1}: status={s}")
    if s == "succeeded":
        content = data.get("content") or {}
        url = content.get("video_url") or data.get("video_url")
        print("VIDEO URL:", url)
        break
    if s == "failed":
        print("FAILED:", data.get("error") or data.get("message"))
        break
    time.sleep(POLL_SLEEP)
else:
    mins = (POLL_MAX * POLL_SLEEP) // 60
    print(f"Timeout: task non completato entro ~{mins} minuti.")
