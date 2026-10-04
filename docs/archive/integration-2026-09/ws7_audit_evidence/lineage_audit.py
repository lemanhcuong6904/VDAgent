import json, sqlite3, sys
from types import SimpleNamespace
from collections import Counter
from vdagent_backend.db.artifact_store import _envelope
c = sqlite3.connect("var/backend.db"); c.row_factory = sqlite3.Row
task = sys.argv[1] if len(sys.argv) > 1 else c.execute("select id from tasks order by created_at desc limit 1").fetchone()["id"]
rows = [SimpleNamespace(**dict(r)) for r in c.execute("select * from artifacts where run_id=? order by created_at, artifact_id, version", (task,))]
envs = {(r.artifact_id, r.version): _envelope(r) for r in rows}
print("task", task, "artifact versions", len(rows))
print("recomputed content_hash mismatches:", [k for k, e in envs.items() if e.compute_content_hash() != e.content_hash])
print("owners:", {e.user_id for e in envs.values()}, "| snapshots:", {tuple(e.snapshot_refs) for e in envs.values()}, "| semantics:", {e.semantic_config_version for e in envs.values()})
latest = {}
for (aid, v), e in envs.items():
    if aid not in latest or v > latest[aid].version: latest[aid] = e
print("types:", dict(Counter(e.artifact_type.value for e in latest.values())))
print("schemas:", sorted({(e.artifact_type.value, e.schema_version, e.status.value) for e in latest.values()}))
ds = [e for e in latest.values() if e.artifact_type.value == "dataset"]; assert len(ds) == 1; ds = ds[0]
def reaches(e):
    if e.artifact_type.value == "dataset": return e.artifact_id == ds.artifact_id
    ok = False
    for r in e.input_artifact_refs:
        src = envs.get((r.artifact_id, r.version))
        if src is None or (r.content_hash and r.content_hash != src.content_hash): return False
        ok = ok or reaches(src)
    return ok
print("all non-run_state artifacts reach the one dataset:", all(reaches(e) for e in latest.values() if e.artifact_type.value != "run_state"))
print("dangling input refs:", [(e.artifact_id, r.artifact_id) for e in envs.values() for r in e.input_artifact_refs if (r.artifact_id, r.version) not in envs])
payload_by = {f"{a}@{v}": e.payload for (a, v), e in envs.items()}
def ptr(doc, p):
    for t in p.split("/")[1:]:
        t = t.replace("~1", "/").replace("~0", "~"); doc = doc[int(t)] if isinstance(doc, list) else doc[t]
    return doc
def check(src, exact):
    ref, p = src.split("#", 1)
    return ref in payload_by and str(ptr(payload_by[ref], p)) == exact
charts = [e for e in latest.values() if e.artifact_type.value == "chart_spec"]
b = [(bb["source_ref"], bb["value_exact"]) for e in charts for bb in e.payload["bindings"]]
print("chart bindings resolved:", sum(check(*x) for x in b), "/", len(b), "| chart types:", [e.payload["chart_type"] for e in charts])
rep = [e for e in latest.values() if e.artifact_type.value == "report"]
if rep:
    rep = rep[0]; st = rep.payload["statements"]
    print("report statements resolved:", sum(check(s["source_ref"], s["value_exact"]) for s in st), "/", len(st), "| missing source_ref:", sum(1 for s in st if not s.get("source_ref")))
    print("report sections:", [s["title"] for s in rep.payload["sections"]])
    print("report charts:", len(rep.payload["charts"]), "tables:", len(rep.payload["tables"]), "actions:", len(rep.payload["actions"]["items"]), "| note:", rep.payload["actions"].get("insufficient_evidence_note"))
    print("report status:", rep.status.value, "| delivery:", rep.payload.get("delivery"), "| validation:", rep.payload.get("validation"))
    r = c.execute("select id, user_id, invocation_id from reports where id=?", (rep.payload["delivery"]["report_id"],)).fetchone()
    print("rp row:", dict(r) if r else None)
cmp = [e for e in latest.values() if e.artifact_type.value == "comparison"]
if cmp:
    print("comparison:", {m["metric"]: (m["subjectValue"], m["benchmark"]["value"], m["benchmark"]["n"], m["pctGap"]) for m in cmp[0].payload["metrics"]})
pd = [e for e in latest.values() if e.artifact_type.value == "peer_definition"]
if pd:
    p = pd[0].payload; print("peers:", [x["entityCode"] for x in p["peers"]], "| areaM2:", p["subjectProfile"]["areaM2"], "| tolerance:", p["areaTolerance"])
blob = " ".join(json.dumps(e.payload, ensure_ascii=False) for e in latest.values() if e.artifact_type.value != "dataset")
print("PRJ-Y in any non-dataset payload:", "PRJ-Y" in blob, "| D12-09:", "D12-09" in blob, "| demo ids:", any(w in blob for w in ("run_vhop_demo", "metric_dom_target", "synthetic_")))
dsb = json.dumps(ds.payload); print("PRJ-Y in dataset payload:", "PRJ-Y" in dsb, "| hidden_rows:", ds.payload.get("hidden_rows"))
rs = max((e for e in envs.values() if e.artifact_type.value == "run_state"), key=lambda e: e.version)
p = rs.payload
print("run_state", rs.artifact_id, "v", rs.version, p["status"], p["waves"])
for s in p["steps"]:
    print(f"  {s['step_id']} {s['agent']:8} {s['status']:9} {(s['started_at'] or '')[11:23]}-{(s['finished_at'] or '')[11:23]} in={len(s['input_refs'])} out={len(s['output_refs'])} err={s.get('error')}")
if len(p["steps"]) >= 3:
    print("B2.in == B3.in == B1.out:", p["steps"][1]["input_refs"] == p["steps"][2]["input_refs"] == p["steps"][0]["output_refs"])
