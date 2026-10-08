"""Run every scenario k times against the real model and report pass^k, per-check pass
rates, groundedness and cost/latency. Writes one JSONL row per run for diffing over time.

    python -m evals.run_evals --k 3
    python -m evals.run_evals --k 5 --cases bad-deploy-01 injection-01 --no-judge
"""
from __future__ import annotations

import argparse
import asyncio
import json
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean

from evals.checks import load_cases, run_checks
from evals.judges import judge_groundedness
from triage_copilot.app import triage
from triage_copilot.llm import AnthropicLLM
from triage_copilot.rag import BM25Retriever


async def run_once(case: dict, llm, retriever, judge: bool) -> dict:
    start = time.perf_counter()
    try:
        result, trace = await triage(case["request"], scenario=case["scenario"], llm=llm,
                                     retriever=retriever, transport="inproc")
    except Exception as e:  # a crash is a failed run, not a crashed eval
        return {"case": case["id"], "passed": False, "error": repr(e), "checks": {}}
    checks = run_checks(case, result, trace)
    row = {
        "case": case["id"],
        "passed": all(c.passed for c in checks),
        "checks": {c.name: c.passed for c in checks},
        "failed_details": {c.name: c.detail for c in checks if not c.passed},
        "wall_s": round(time.perf_counter() - start, 2),
        **trace.totals(),
        "root_cause": result.report.root_cause_category if result.report else None,
        "confidence": result.report.confidence if result.report else None,
    }
    if judge and result.report is not None:
        verdict = await judge_groundedness(llm, result, retriever)
        row["groundedness"], row["unsupported_claims"] = verdict.score, verdict.unsupported
    return row


def summarize(rows: list[dict], k: int) -> None:
    by_case = defaultdict(list)
    for r in rows:
        by_case[r["case"]].append(r)
    print(f"\n{'case':22} {'pass^k':>7} {'pass rate':>10} {'tools':>6} {'tokens':>8} {'wall s':>7}  failures")
    for case, runs in by_case.items():
        fails = sorted({name for r in runs for name, ok in r["checks"].items() if not ok}
                       | {"crash" for r in runs if "error" in r})
        ok = [r for r in runs if "error" not in r]
        print(f"{case:22} {'PASS' if all(r['passed'] for r in runs) else 'FAIL':>7} "
              f"{sum(r['passed'] for r in runs)}/{len(runs):<8} "
              f"{mean(r['tool_calls'] for r in ok) if ok else 0:6.1f} "
              f"{mean(r['input_tokens'] + r['output_tokens'] for r in ok) if ok else 0:8.0f} "
              f"{mean(r['wall_s'] for r in ok) if ok else 0:7.1f}  {', '.join(fails)}")

    check_totals = defaultdict(list)
    for r in rows:
        for name, ok in r["checks"].items():
            check_totals[name.split(":")[0]].append(ok)
    print("\nper-check pass rate:")
    for name, oks in sorted(check_totals.items()):
        print(f"  {name:26} {sum(oks)}/{len(oks)}")
    grounded = [r["groundedness"] for r in rows if "groundedness" in r]
    if grounded:
        print(f"\nmean groundedness: {mean(grounded):.2f} (min {min(grounded):.2f})")
    cases_pass_k = sum(all(r["passed"] for r in runs) for runs in by_case.values())
    print(f"\npass^{k}: {cases_pass_k}/{len(by_case)} cases passed every run")


async def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--k", type=int, default=3, help="runs per case")
    p.add_argument("--cases", nargs="*", help="case ids (default: all)")
    p.add_argument("--no-judge", action="store_true")
    p.add_argument("--out", default="evals/results")
    args = p.parse_args()

    cases = [c for c in load_cases() if not args.cases or c["id"] in args.cases]
    llm, retriever = AnthropicLLM(), BM25Retriever.from_dir()
    rows = []
    for case in cases:
        for i in range(args.k):
            row = await run_once(case, llm, retriever, judge=not args.no_judge)
            rows.append({**row, "run": i})
            print(f"{case['id']} run {i + 1}/{args.k}: {'pass' if row['passed'] else 'FAIL'}", flush=True)

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    path = out / f"{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}.jsonl"
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n")
    summarize(rows, args.k)
    print(f"\nwrote {path}")


if __name__ == "__main__":
    asyncio.run(main())
