from __future__ import annotations

import argparse
from pathlib import Path

from eval.golden import GOLDEN_QA
from eval.report import build_report
from eval.runner import run_eval_sync


def main() -> None:
    ap = argparse.ArgumentParser(description="Run Foundry evaluation over the golden Q&A set")
    ap.add_argument("--limit", type=int, default=None, help="평가할 최대 문항 수")
    ap.add_argument("--out", default="reports/eval-report.md")
    args = ap.parse_args()

    items = GOLDEN_QA[: args.limit] if args.limit else GOLDEN_QA
    rows = run_eval_sync(items)
    report = build_report(rows)

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(report, encoding="utf-8")
    print(report)
    print(f"\n리포트 저장: {out}")


if __name__ == "__main__":
    main()
