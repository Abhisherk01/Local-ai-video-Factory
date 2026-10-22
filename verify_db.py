"""verify_db.py - read-only field evidence from the live Tauri DB.
Run from the repo root:  python verify_db.py   (or: python verify_db.py 12)
"""
import json
import os
import sqlite3
import sys
from pathlib import Path

limit = 8
if len(sys.argv) > 1:
    limit = int(sys.argv[1])

db = Path(os.environ["LOCALAPPDATA"]) / "com.rajbh.localaivideofactory" / "laf.db"
print("db:", db, "| exists:", db.exists())
con = sqlite3.connect(f"file:{db.as_posix()}?mode=ro", uri=True, timeout=5.0)
con.row_factory = sqlite3.Row

rows = con.execute(
    "SELECT id, episode_id, type, status, result, error"
    " FROM jobs ORDER BY id DESC LIMIT ?",
    (limit,),
).fetchall()

print("")
print("== last jobs ==")
for r in reversed(rows):
    head = "job #" + str(r["id"]) + " ep" + str(r["episode_id"])
    head += " " + r["type"] + " -> " + r["status"]
    if r["error"]:
        head += " | error: " + str(r["error"])[:120]
    print("")
    print(head)
    raw = r["result"] or ""
    if not raw.strip():
        continue
    try:
        res = json.loads(raw)
    except Exception:
        print("  result(non-json):", raw[:120])
        continue
    for k in ("method", "bed", "style_slug", "scene_count",
              "duration_s", "bytes", "thinking_stripped",
              "think_truncated", "raw_chars"):
        if k in res:
            print("  " + k + ": " + str(res[k]))
    text = str(res.get("text", ""))
    if text:
        print("  text[" + str(len(text)) + "ch]: " + repr(text[:140]))
        low = text.lower()
        if "think>" in low:
            print("  think-leak: LEAK")
        else:
            print("  think-leak: clean")

eps = con.execute(
    "SELECT id, title, status, script_text FROM episodes"
    " ORDER BY id DESC LIMIT ?",
    (limit,),
).fetchall()
con.close()

print("")
print("== episode scripts (stored narration - eyeball these) ==")
for e in reversed(eps):
    st = e["script_text"] or ""
    head = "ep" + str(e["id"]) + " " + str(e["title"])
    head += " [" + e["status"] + "] script[" + str(len(st)) + "ch]"
    print("")
    print(head)
    if not st.strip():
        continue
    print("  " + repr(st[:200]))
    low = st.lower()
    if "think>" in low:
        print("  script-leak: LEAK")
    else:
        print("  script-leak: clean")

print("")
print("hints: script job wants think_truncated present + text clean")
print("       render job wants method=local_piper + bed=procedural:drone")
print("       ep row: read the snippet - pure narration = green")
