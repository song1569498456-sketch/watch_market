"""M00 批量合并脚本：把研究子 agent 的本轮产出并入登记表与批次清单。

用法：python merge_batch.py <batch_no> <ROLE1> <ROLE2> ...
前置：子 agent 已写 reports/evidence/state 三类文件，且未改其它路径。
输出：更新 registry/{agents,findings,markets,coverage-gaps}.json、生成 findings/<id>/<run>-<role>.json、
      更新 runs/<run>/manifest.json 的 batches；不 commit/push（由 M00 执行）。
"""
import json
import os
import subprocess
import sys
import datetime

RUN_ID = "live-20261109T141903Z"
REPO = r"D:\ds-arb-test\watch_market"
DATE_BJ = "2026-11-09"

ALLOWED_PREFIXES = ("reports/", "evidence/", "state/agents/", "findings/")
REQUIRED_RECORD_KEYS = [
    "agent_id", "run_id", "chain", "scope", "started_at", "finished_at", "duration_seconds",
    "execution_status", "status", "as_of", "block_or_slot", "market_ids", "asset_ids",
    "discovery_source", "mechanism", "observations", "quotes", "net_result", "capacity",
    "permissions", "liabilities", "waiting_time", "invalidation_conditions", "evidence_urls",
    "coverage_gaps", "next_check", "handoff_to", "markets", "findings", "rejections",
    "observed_cursor",
]


def load(rel):
    with open(os.path.join(REPO, rel), encoding="utf-8") as f:
        return json.load(f)


def save(rel, data):
    with open(os.path.join(REPO, rel), "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write("\n")


def now_utc():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def check_worktree():
    out = subprocess.run(["git", "status", "--porcelain"], cwd=REPO, capture_output=True, text=True,
                         encoding="utf-8").stdout.splitlines()
    bad = []
    for line in out:
        path = line[3:].strip().strip('"')
        if not any(path.startswith(p) for p in ALLOWED_PREFIXES):
            bad.append(path)
    return bad


def main():
    batch_no = int(sys.argv[1])
    roles = sys.argv[2:]
    if not roles:
        print("ERROR: no roles")
        sys.exit(2)

    bad = check_worktree()
    if bad:
        print("ERROR: 子 agent 修改了不允许的路径:")
        for p in bad:
            print("  -", p)
        sys.exit(3)

    agents = load("registry/agents.json")
    findings = load("registry/findings.json")
    markets = load("registry/markets.json")
    gaps = load("registry/coverage-gaps.json")
    manifest = load(f"runs/{RUN_ID}/manifest.json")

    agent_by_id = {a["agent_id"]: a for a in agents["agents"]}
    finding_by_id = {f["finding_id"]: f for f in findings["items"]}
    market_by_id = {m["market_id"]: m for m in markets["items"]}

    summary = []
    for role in roles:
        report = f"reports/agents/{role}/{DATE_BJ}/{RUN_ID}.md"
        record = f"evidence/{role}/{RUN_ID}/record.json"
        state = f"state/agents/{role}.json"
        for p in (report, record, state):
            if not os.path.exists(os.path.join(REPO, p)):
                print(f"ERROR: {role} 缺少文件 {p}")
                sys.exit(4)
        rec = load(record)
        missing = [k for k in REQUIRED_RECORD_KEYS if k not in rec]
        if missing:
            print(f"ERROR: {role} record 缺字段: {missing}")
            sys.exit(5)
        if rec.get("agent_id") != role or rec.get("run_id") != RUN_ID:
            print(f"ERROR: {role} record 的 agent_id/run_id 不匹配")
            sys.exit(6)

        st = load(state)
        st["last_attempt_storage"] = "PENDING_REMOTE_VERIFY"
        st["last_research_run_id"] = RUN_ID
        st["last_attempt_at"] = rec.get("finished_at")
        st["report"] = report
        st["record"] = record
        st["last_verified_attempt"] = None
        save(state, st)

        # agents registry
        a = agent_by_id.get(role)
        if a is None:
            print(f"ERROR: registry 缺少岗位 {role}")
            sys.exit(7)
        a["status"] = rec.get("execution_status", "PARTIAL")
        a["last_attempt_at"] = rec.get("finished_at")
        a["last_success_at"] = rec.get("finished_at") if rec.get("execution_status") in ("COMPLETED", "PARTIAL") else None
        a["actual_coverage"] = rec.get("observations", [])[:8]
        a["coverage_gaps"] = rec.get("coverage_gaps", [])
        a["report"] = report
        a["actual_capabilities"] = {
            "public_http_requests": len(rec.get("discovery_source", [])),
            "current_quote_obtained": bool(rec.get("quotes")),
            "block_or_slot_obtained": rec.get("block_or_slot") is not None,
            "broadcast_or_signing_used": False,
            "background_schedule_created": False,
        }
        a["last_verified_attempt"] = None

        # markets
        for m in rec.get("markets", []):
            mid = m["market_id"]
            entry = market_by_id.get(mid)
            is_new = entry is None
            if is_new:
                entry = {"market_id": mid}
            entry.update({
                "chain": m.get("chain"),
                "protocol": m.get("protocol"),
                "asset_ids": m.get("asset_ids", []),
                "evidence_urls": m.get("evidence_urls", []),
                "identity_status": m.get("identity_status", "UNVERIFIED"),
                "next_check": m.get("next_check"),
                "owner": role,
                "last_observed_run": RUN_ID,
                "source_record": record,
            })
            obs = entry.setdefault("observations_by_role", {})
            obs[role] = dict(m)
            if rec.get("block_or_slot"):
                entry["current_onchain_verified"] = True
            entry.setdefault("current_onchain_verified", False)
            entry.setdefault("monitoring_status", "BASELINE_PARTIAL")
            if is_new:
                market_by_id[mid] = entry
                markets["items"].append(entry)

        # findings
        for f in rec.get("findings", []):
            fid = f["finding_id"]
            entry = finding_by_id.get(fid)
            is_new = entry is None
            if is_new:
                entry = {"finding_id": fid, "first_seen_at": rec.get("finished_at")}
            entry.update({
                "status": f.get("status", "UNVERIFIED"),
                "market_id": f.get("market_id"),
                "mechanism": f.get("mechanism"),
                "evidence_urls": f.get("evidence_urls", []),
                "net_result": f.get("net_result", "unknown"),
                "unknown_costs": f.get("unknown_costs", []),
                "handoff_to": f.get("handoff_to", []),
                "invalidation_conditions": f.get("invalidation_conditions", []),
                "owner": entry.get("owner", role),
                "last_observed_run": RUN_ID,
                "source_record": record,
                "last_observed_at": rec.get("finished_at"),
                "last_verified_onchain_at": rec.get("finished_at") if rec.get("block_or_slot") else None,
                "capacity": rec.get("capacity"),
            })
            obs = entry.setdefault("observations_by_role", {})
            obs[role] = dict(f)
            if is_new:
                entry.setdefault("q00_review", None)
                entry.setdefault("initial_research_status", f.get("status", "UNVERIFIED"))
                finding_by_id[fid] = entry
                findings["items"].append(entry)
            save(f"findings/{fid}/{RUN_ID}-{role}.json", {
                **f,
                "owner": role,
                "last_observed_run": RUN_ID,
                "source_record": record,
            })

        # coverage gaps: replace this role's items
        gaps["items"] = [g for g in gaps["items"] if not (g.get("agent_id") == role and g.get("run_id") == RUN_ID)]
        for g in rec.get("coverage_gaps", []):
            gaps["items"].append({"agent_id": role, "run_id": RUN_ID, "gap": g,
                                  "next_check": rec.get("next_check", [])})

        # changes registry: record status change entry
        prev_status = None
        for c in load("registry/changes.json")["items"]:
            if c.get("agent_id") == role and c.get("type") == "ROUND_STATUS_UPDATE":
                prev_status = c.get("new_status")
        summary.append({
            "role": role,
            "execution_status": rec.get("execution_status"),
            "status": rec.get("status"),
            "block_or_slot": rec.get("block_or_slot"),
            "quotes": len(rec.get("quotes", [])),
            "findings": [f["finding_id"] for f in rec.get("findings", [])],
            "markets": len(rec.get("markets", [])),
            "coverage_gaps": len(rec.get("coverage_gaps", [])),
        })

    # batch record
    manifest.setdefault("batches", [])
    manifest["batches"].append({
        "batch": batch_no,
        "agents": roles,
        "merged_at": now_utc(),
        "storage_status": "PUSH_PENDING",
        "evidence_commit": None,
        "notes": "M00 merge_batch.py",
    })
    manifest["researcher_batches"] = {"planned": 16, "completed": len(manifest["batches"])}
    manifest["phase"] = "phase3_research"

    agents["agents"] = [agent_by_id[a["agent_id"]] for a in agents["agents"]]
    agents["status"] = "LIVE_ROUND_IN_PROGRESS"
    findings["status"] = "LIVE_ROUND_IN_PROGRESS"
    markets["status"] = "LIVE_ROUND_IN_PROGRESS"
    gaps["status"] = "OPEN"

    save("registry/agents.json", agents)
    save("registry/findings.json", findings)
    save("registry/markets.json", markets)
    save("registry/coverage-gaps.json", gaps)
    save(f"runs/{RUN_ID}/manifest.json", manifest)

    print(json.dumps({"batch": batch_no, "roles": summary}, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
