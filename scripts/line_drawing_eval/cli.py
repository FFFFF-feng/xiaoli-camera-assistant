"""Command line entry point for the independent line-drawing evaluation."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from .acceptance import budget_plan, build_matrix
from .evidence import discover_runs, index_root, load_json, write_json
from .gallery import build_gallery
from .ledger import Ledger
from .timing import analyze_layouts, analyze_run


def _print(payload: object) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def command_index(args: argparse.Namespace) -> int:
    payload = index_root(args.evidence)
    write_json(args.out / "index.json", payload)
    layouts = {(layout.run, layout.case_id): layout for layout in discover_runs(args.evidence)}
    for record in payload["runs"]:
        layout = layouts[(record["run"], record["case_id"])]
        run_dir = args.out / "runs" / f"{layout.run}-{layout.case_id}"
        write_json(
            run_dir / "run-record.json",
            {
                **record,
                "timing": analyze_run(layout.root, run=layout.run, case_id=layout.case_id),
                "record_policy": (
                    "Read-only index of a stored attempt. Missing facts (model id, dirty state, "
                    "raw mask) stay marked unknown; nothing is regenerated or inferred."
                ),
            },
        )
    _print({"runs": payload["run_count"], "gateway_posts": payload["gateway_posts_represented"],
            "out": str(args.out / "index.json")})
    return 0


def command_timing(args: argparse.Namespace) -> int:
    payload = analyze_layouts(discover_runs(args.evidence))
    write_json(args.out / "timing.json", payload)
    summary = {
        "runs": [
            {
                "run": run["run"],
                "case": run["case_id"],
                "wall": run["wall_seconds"],
                "critical_branch": run["critical_branch"],
                "top": [item["stage"] for item in run["ranked_segments"][:3]],
                "ready_lead": run["ready_lead_seconds"],
            }
            for run in payload["runs"]
        ],
        "cloud": payload["cloud_call_summary"],
        "out": str(args.out / "timing.json"),
    }
    _print(summary)
    return 0


def command_gallery(args: argparse.Namespace) -> int:
    receipt = build_gallery(discover_runs(args.evidence), args.out)
    write_json(args.out / "gallery-receipt.json", receipt)
    _print({"page": receipt["page"], "cases": len(receipt["cases"])})
    return 0


def command_acceptance(args: argparse.Namespace) -> int:
    ledger = Ledger.load(args.ledger)
    payload = {
        "matrix": build_matrix(),
        "budget": budget_plan(ledger.remaining),
        "ledger": {
            "used": ledger.data["budget"]["used_gateway_posts"],
            "remaining": ledger.remaining,
            "internal_request_starts": ledger.data["internal_request_starts"]["used"],
            "protocol_repairs": ledger.data["observation_protocol_repairs"]["used"],
            "outer_retries": ledger.data["outer_retries"]["used"],
        },
    }
    write_json(args.out / "acceptance-plan.json", payload)
    _print(payload["budget"])
    return 0


def command_init_ledger(args: argparse.Namespace) -> int:
    if args.out.exists():
        raise SystemExit(f"refusing to overwrite existing ledger {args.out}")
    handoff = load_json(args.handoff)
    ledger = Ledger.create_inherited(
        args.out,
        handoff,
        total_budget=args.total,
        used=args.used,
        internal_starts=args.internal_starts,
        protocol_repairs=args.protocol_repairs,
        outer_retries=args.outer_retries,
    )
    ledger.save()
    _print(
        {
            "ledger": str(args.out),
            "used": ledger.data["budget"]["used_gateway_posts"],
            "remaining": ledger.remaining,
        }
    )
    return 0


def command_ledger(args: argparse.Namespace) -> int:
    ledger = Ledger.load(args.path)
    _print(ledger.data["budget"] | {"reservations": len(ledger.data["reservations"])})
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Independent offline line-drawing evaluation")
    sub = parser.add_subparsers(dest="command", required=True)

    def evidence_args(item: argparse.ArgumentParser) -> None:
        item.add_argument("--evidence", type=Path, required=True)
        item.add_argument("--out", type=Path, required=True)

    index = sub.add_parser("index", help="index stored attempts and verify original hashes")
    evidence_args(index)
    index.set_defaults(func=command_index)

    timing = sub.add_parser("timing", help="reconstruct critical paths from events and timings")
    evidence_args(timing)
    timing.set_defaults(func=command_timing)

    gallery = sub.add_parser("gallery", help="build the static offline replay gallery")
    evidence_args(gallery)
    gallery.set_defaults(func=command_gallery)

    acceptance = sub.add_parser("acceptance", help="write the acceptance matrix and budget plan")
    acceptance.add_argument("--ledger", type=Path, required=True)
    acceptance.add_argument("--out", type=Path, required=True)
    acceptance.set_defaults(func=command_acceptance)

    init = sub.add_parser("init-ledger", help="create the E ledger from A's handoff (once)")
    init.add_argument("--handoff", type=Path, required=True)
    init.add_argument("--out", type=Path, required=True)
    init.add_argument("--total", type=int, default=8)
    init.add_argument("--used", type=int, default=5)
    init.add_argument("--internal-starts", type=int, default=22)
    init.add_argument("--protocol-repairs", type=int, default=2)
    init.add_argument("--outer-retries", type=int, default=0)
    init.set_defaults(func=command_init_ledger)

    ledger = sub.add_parser("ledger", help="show the current E ledger")
    ledger.add_argument("--path", type=Path, required=True)
    ledger.set_defaults(func=command_ledger)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
