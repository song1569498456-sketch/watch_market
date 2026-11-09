"""M00 收尾脚本：把本轮（live-20261109T141903Z）研究+Q00复核并入状态、登记表与运行清单。

用法：python finalize_run.py <output_commit_hint>
说明：output_commit_hint 是本脚本产出提交之前的最近一次已验证远端提交；不把提交自身 SHA 写进文件。
"""
import json
import os
import sys
import datetime

RUN_ID = "live-20261109T141903Z"
REPO = r"D:\ds-arb-test\watch_market"
DATE_BJ = "2026-11-09"
BATCH_COMMITS = {
    1: "b9209173d6e592aead19672cd4bc05c384024894",
    2: "37cdebd33de2d8937fffd6ade61e385c4f09cc8e",
    3: "184c8d5e29aaa99be1461d5bc6ba1f1f7854236f",
    4: "47b2ab52e6cf07ae7f0c9dba4da92a0cf39b3ffc",
    5: "992498e29fb2f736f9b8c5c316684eb7032e79e6",
    6: "220f3077b3819c90e01be36139ca2ff2fb6105e3",
    7: "84cb09586b78512ee128e4f35a9f418fc303637a",
    8: "389baef1180ca750dd4b08206c8d528adbe86dce",
    9: "6255bd94b25d632c4e269b18f2c34eafe4d659b6",
    10: "c8783839912f0e992cc409e46c70a035645f9739",
    11: "ec2399303683973882cae5400250cc80a9823b70",
    12: "e3d9a7374bbeef7e34b45ac0e55fd65c76ecd2c0",
    13: "5f58af8d17f3bf4047dacf433e837a332ac82ab2",
    14: "c71d90d93596ff9285c5a67adf49103e58b21628",
    15: "3d9fcde7b68776585190e89e937ba7db1e157782",
    16: "1f91d9c04294a28be637836f43544ebb0a1f68a0",
}


def load(rel):
    with open(os.path.join(REPO, rel), encoding="utf-8") as f:
        return json.load(f)


def save(rel, data):
    with open(os.path.join(REPO, rel), "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write("\n")


def now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def main():
    output_commit_hint = sys.argv[1] if len(sys.argv) > 1 else None
    manifest = load(f"runs/{RUN_ID}/manifest.json")
    role_batch = {}
    for b in manifest.get("batches", []):
        for r in b["agents"]:
            role_batch[r] = b["batch"]

    # ---- Q00 review ----
    q00_review = load(f"evidence/Q00/{RUN_ID}/review.json")
    gate_verdict = q00_review.get("gate", {}).get("verdict")
    reviews = {x["finding_id"]: x for x in q00_review.get("findings", [])}
    q00_counts = q00_review.get("counts", {})
    q00_report = f"reports/agents/Q00/{DATE_BJ}/{RUN_ID}.md"

    agents = load("registry/agents.json")
    agent_by_id = {a["agent_id"]: a for a in agents["agents"]}
    findings = load("registry/findings.json")
    findings_by_id = {f["finding_id"]: f for f in findings["items"]}
    markets = load("registry/markets.json")
    changes = load("registry/changes.json")

    # ---- per-role state/registry finalize ----
    finished = now()
    finalized = 0
    for role, batch_no in role_batch.items():
        commit = BATCH_COMMITS.get(batch_no, "")
        st = load(f"state/agents/{role}.json")
        rec = load(f"evidence/{role}/{RUN_ID}/record.json")
        report = f"reports/agents/{role}/{DATE_BJ}/{RUN_ID}.md"
        record = f"evidence/{role}/{RUN_ID}/record.json"
        st["last_attempt_storage"] = "REMOTE_VERIFIED"
        st["report"] = report
        st["record"] = record
        st["last_verified_attempt"] = {
            "run_id": RUN_ID,
            "evidence_commit": commit,
            "verified_at": finished,
            "record": record,
        }
        st["published_cursor"] = {
            "scope": rec.get("execution_status", "PARTIAL"),
            "observed": st.get("observed_cursor"),
            "evidence_commit": commit,
            "run_id": RUN_ID,
        }
        save(f"state/agents/{role}.json", st)
        a = agent_by_id.get(role)
        if a is not None:
            a["last_verified_attempt"] = st["last_verified_attempt"]
        finalized += 1

    # ---- M00 control role ----
    m00_rec = load(f"evidence/M00/{RUN_ID}/record.json")
    m00_report = f"reports/agents/M00/{DATE_BJ}/{RUN_ID}.md"
    m00_record = f"evidence/M00/{RUN_ID}/record.json"
    m00_st = load("state/agents/M00.json")
    m00_st.update({
        "status": "COMPLETED",
        "research_started": True,
        "last_research_run_id": RUN_ID,
        "last_success_at": finished,
        "last_attempt_at": finished,
        "observed_cursor": {
            "scope": "control-plane-live-round",
            "role_attempts": len(role_batch),
            "live_gate_passed": True,
            "history_scan_cursor": None,
        },
        "published_cursor": {
            "scope": "COMPLETED_SCOPE_WITH_GAPS",
            "observed": {"scope": "control-plane-live-round", "role_attempts": len(role_batch)},
            "evidence_commit": BATCH_COMMITS[16],
            "run_id": RUN_ID,
        },
        "last_attempt_storage": "REMOTE_VERIFIED",
        "report": m00_report,
        "record": m00_record,
        "last_verified_attempt": {
            "run_id": RUN_ID,
            "evidence_commit": BATCH_COMMITS[16],
            "verified_at": finished,
            "record": m00_record,
        },
    })
    save("state/agents/M00.json", m00_st)
    if "M00" in agent_by_id:
        agent_by_id["M00"].update({
            "status": "COMPLETED",
            "last_success_at": finished,
            "last_attempt_at": finished,
            "report": m00_report,
            "last_verified_attempt": m00_st["last_verified_attempt"],
        })

    # ---- Q00 state + registry role ----
    q00_st = load("state/agents/Q00.json")
    q00_st.update({
        "status": "PARTIAL",
        "last_research_run_id": RUN_ID,
        "last_success_at": q00_review.get("reviewed_at_utc"),
        "last_attempt_at": q00_review.get("reviewed_at_utc"),
        "last_attempt_storage": "PENDING_REMOTE_VERIFY",
        "report": q00_report,
        "record": f"evidence/Q00/{RUN_ID}/review.json",
        "last_verified_attempt": None,
        "published_cursor": {
            "scope": "INDEPENDENT_REVIEW_OF_LIVE_ROUND",
            "observed": {
                "kind": "live_gate_and_candidate_findings_independent_review",
                "reviewed_findings": len(reviews),
                "gate_verdict": gate_verdict,
            },
            "evidence_commit": BATCH_COMMITS[16],
            "run_id": RUN_ID,
        },
        "coverage": [{
            "review_counts": q00_counts,
            "gate_verdict": gate_verdict,
            "reviewed_findings": len(reviews),
            "review_file": f"evidence/Q00/{RUN_ID}/review.json",
        }],
    })
    save("state/agents/Q00.json", q00_st)
    if "Q00" in agent_by_id:
        agent_by_id["Q00"].update({
            "status": "PARTIAL",
            "last_attempt_at": q00_review.get("reviewed_at_utc"),
            "last_success_at": q00_review.get("reviewed_at_utc"),
            "report": q00_report,
            "last_verified_attempt": {
                "run_id": RUN_ID,
                "evidence_commit": BATCH_COMMITS[16],
                "verified_at": finished,
                "record": f"evidence/Q00/{RUN_ID}/review.json",
            },
        })

    # ---- findings Q00 reviews ----
    for fid, rev in reviews.items():
        f = findings_by_id.get(fid)
        if f is None:
            continue
        f["q00_review"] = {
            "finding_id": fid,
            "claim_scope": rev.get("claim_scope"),
            "verdict": rev.get("verdict"),
            "recommended_status": rev.get("recommended_status"),
            "independently_checked_at": q00_review.get("reviewed_at_utc"),
            "independently_checked_sources": rev.get("independent_checks", []),
            "notes": rev.get("notes"),
            "run_id": RUN_ID,
        }

    # ---- changes registry ----
    for role, batch_no in role_batch.items():
        rec = load(f"evidence/{role}/{RUN_ID}/record.json")
        changes["items"].append({
            "run_id": RUN_ID,
            "type": "ROUND_STATUS_UPDATE",
            "agent_id": role,
            "at": rec.get("finished_at"),
            "previous_run_id": "full-20261108T152118Z",
            "execution_status": rec.get("execution_status"),
            "new_status": rec.get("status"),
            "block_or_slot": rec.get("block_or_slot"),
            "quotes": len(rec.get("quotes", [])),
            "findings": [x.get("finding_id") for x in rec.get("findings", [])],
            "evidence_commit": BATCH_COMMITS.get(batch_no),
        })
    changes["status"] = "LIVE_ROUND_COMPLETED_WITH_GAPS"
    save("registry/changes.json", changes)

    # ---- registry top-level statuses ----
    agents["status"] = "LIVE_ROUND_COMPLETED_WITH_GAPS"
    findings["status"] = "LIVE_ROUND_COMPLETED_WITH_GAPS"
    markets["status"] = "LIVE_ROUND_COMPLETED_WITH_GAPS"
    save("registry/agents.json", agents)
    save("registry/findings.json", findings)
    save("registry/markets.json", markets)

    # ---- research history ----
    hist = load("state/research-history.json")
    hist["status"] = "COMPLETED_WITH_GAPS"
    hist["completed_research_runs"].append({
        "run_id": RUN_ID,
        "input_commit": manifest.get("input_commit"),
        "status": "COMPLETED_WITH_GAPS",
        "started_at": manifest.get("started_at_utc"),
        "finished_at": manifest.get("finished_at_utc"),
        "all_roles_attempted": True,
        "full_required_history_coverage": False,
        "manifest": f"runs/{RUN_ID}/manifest.json",
        "execution_environment": "USER_LOCAL_WINDOWS_DSH_SESSION_WITH_PROXY",
        "live_data_used": True,
        "q00_verdict_gate": gate_verdict,
    })
    hist["last_completed_research_run"] = RUN_ID
    for role in role_batch:
        rec = load(f"evidence/{role}/{RUN_ID}/record.json")
        hist["research_checkpoints"][role] = {
            "run_id": RUN_ID,
            "status": rec.get("execution_status"),
            "scope": rec.get("status"),
            "full_30d_7d_coverage": False,
            "state": f"state/agents/{role}.json",
        }
    hist["note"] = ("完成一次全岗位实网研究（本地执行环境），仍非 30 天/7 天完整回看；"
                    "经济结论以 Q00 复核与本轮区块证据为准，不构成本轮之外的保证。")
    save("state/research-history.json", hist)

    # ---- data capability ----
    cap = load("state/data-capability.json")
    cap.update({
        "last_check_run": RUN_ID,
        "gate_status": "PASS",
        "checkpoint_advanced": False,
        "live_gate_passed": True,
        "review_verdict": gate_verdict,
        "last_capability_review": f"evidence/Q00/{RUN_ID}/review.json",
        "required_configuration": "已通过本机代理环境直接满足；上一轮云端网络阻塞在本执行环境不存在",
        "storage_status": "REMOTE_VERIFIED",
        "last_capability_evidence_commit": BATCH_COMMITS[16],
        "single_market_gate": f"evidence/M00/{RUN_ID}/single-market-gate.json",
        "research_success_checkpoint_advanced": True,
        "note": "本执行环境为用户本机（非原云端实例）；gate 通过不等于云端调度或关机运行可用。",
    })
    save("state/data-capability.json", cap)

    # ---- observation pilot ----
    pilot = load("state/observation-pilot.json")
    pilot.update({
        "status": "READY_FOR_TWO_DAY_DELTA_OBSERVATION",
        "baseline_run": RUN_ID,
        "baseline_input_commit": manifest.get("input_commit"),
        "requested_observation_days": 2,
        "completed_observation_days": 0,
        "start_date": None,
        "change_only": True,
        "full_roster_repeat": False,
        "automatic_trigger_configured": False,
        "scope": ("Gate 已通过、全岗位实网轮已完成；后续两天复用本轮基线与 registry/coverage-gaps.json，"
                  "只查变化/缺口，记录实际耗时；不创建定时任务。"),
        "last_capability_review": f"evidence/Q00/{RUN_ID}/review.json",
        "last_capability_evidence_commit": BATCH_COMMITS[16],
    })
    save("state/observation-pilot.json", pilot)

    # ---- scheduler unchanged ----
    sched = load("state/scheduler.json")
    sched["note"] = ("当前手动本机研究已验证，不等于具备持久定时唤醒能力；"
                     "本机不是云端调度，未创建本地替代任务。")
    save("state/scheduler.json", sched)

    # ---- runtime config ----
    cfg = load("config/runtime.json")
    dac = cfg.setdefault("data_access_control", {})
    dac["current_mode"] = "TWO_DAY_DELTA_ONLY_PILOT_READY"
    dac["single_market_gate_passed"] = True
    dac["last_live_round"] = RUN_ID
    dac["last_live_round_commit"] = BATCH_COMMITS[16]
    dac["last_live_round_environment"] = "USER_LOCAL_WINDOWS_DSH_SESSION_WITH_PROXY"
    dac["full_roster_repeat"] = False
    save("config/runtime.json", cfg)

    # ---- manifest ----
    quotes_total = 0
    findings_new = []
    findings_updated = []
    for role in role_batch:
        rec = load(f"evidence/{role}/{RUN_ID}/record.json")
        quotes_total += len(rec.get("quotes", []))
        for f in rec.get("findings", []):
            fid = f.get("finding_id")
            if fid in reviews:
                findings_updated.append(fid)
    findings_new = sorted(set(findings_updated))
    manifest.update({
        "status": "COMPLETED_WITH_GAPS",
        "research_status": "ALL_ENABLED_ROLES_ATTEMPTED_LIVE_WITH_DOCUMENTED_GAPS",
        "storage_status": "REMOTE_VERIFIED",
        "schedule_status": "NOT_CONFIGURED",
        "finished_at_utc": finished,
        "q00_review": f"evidence/Q00/{RUN_ID}/review.json",
        "q00_gate_verdict": gate_verdict,
        "q00_counts": q00_counts,
        "roles_attempted": len(role_batch),
        "quotes_total": quotes_total,
        "candidate_findings_reviewed": len(reviews),
        "research_completed_without_gaps": 0,
        "full_roster_research_rerun": True,
        "live_gate_passed": True,
        "transaction_broadcast": False,
        "schedule_created": False,
        "model_usage": {"tokens": None, "cost": None,
                        "status": "UNAVAILABLE_NO_CURRENT_SESSION_USAGE_TOOL; no estimates substituted"},
        "output_commit_before_final_publish": output_commit_hint,
        "verification_receipts": [
            {"commit": c, "batch": b, "verified_by": "pull --ff-only fetch后 HEAD 与文件 blob 比对"}
            for b, c in sorted(BATCH_COMMITS.items())
        ],
    })
    save(f"runs/{RUN_ID}/manifest.json", manifest)

    print(json.dumps({
        "finalized_roles": finalized,
        "batches": len(BATCH_COMMITS),
        "quotes_total": quotes_total,
        "q00_gate_verdict": gate_verdict,
        "q00_counts": q00_counts,
        "findings_reviewed": len(reviews),
    }, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
