from __future__ import annotations

import argparse

from agent.orchestrator import ask_sync


def main() -> None:
    ap = argparse.ArgumentParser(description="Ask the fund-evaluation agent")
    ap.add_argument("question", help="질문 (한국어)")
    args = ap.parse_args()

    result = ask_sync(args.question)

    print("=" * 60)
    print("[추론 단계]")
    for i, s in enumerate(result.steps, 1):
        print(f"  {i}. {s.tool}(\"{s.query}\") -> {s.n_hits} hits")
    print("=" * 60)
    print("[답변]")
    print(result.answer)
    print("=" * 60)
    print("[근거]")
    for s in result.sources:
        print(f"  [출처 {s.n}] ({s.index}) {s.section_path} p.{s.page_physical}")


if __name__ == "__main__":
    main()
