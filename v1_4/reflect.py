import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

if __package__ is None or __package__ == "":
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from v1_4.core.deepseek_policy import DeepSeekPolicy
from v1_4.core.effort import (
    build_ante_trajectory,
    heuristic_effort_score,
    normalize_effort_review,
    select_extreme_reviews,
)
from v1_4.core.env import load_dotenv
from v1_4.core.memory import read_jsonl

load_dotenv()


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Incrementally edit v1.4 rulebook from easiest/hardest Ante trajectories")
    p.add_argument("--out-dir", default="v1_4/out")
    p.add_argument("--max-prompt-chars", type=int, default=45000)
    p.add_argument("--extreme-count", type=int, default=3, help="Number of hardest and easiest Ante trajectories to compare")
    p.add_argument("--max-rule-edits", type=int, default=6, help="Maximum add/update/delete operations per reflection")
    p.add_argument("--provider", default=os.getenv("LLM_PROVIDER", "deepseek"), choices=["deepseek", "qwen", "visioncoder"])
    p.add_argument("--model", default=os.getenv("DEEPSEEK_MODEL", "deepseek-v4-pro"))
    p.add_argument("--deepseek-url", default=os.getenv("DEEPSEEK_BASE_URL", os.getenv("DEEPSEEK_URL", "https://api.deepseek.com")))
    p.add_argument("--deepseek-api-key", default=os.getenv("DEEPSEEK_API_KEY", ""))
    p.add_argument("--qwen-url", default=os.getenv("QWEN_BASE_URL", os.getenv("DASHSCOPE_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1")))
    p.add_argument("--qwen-api-key", default=os.getenv("QWEN_API_KEY", os.getenv("DASHSCOPE_API_KEY", "")))
    p.add_argument("--visioncoder-url", default=os.getenv("VISIONCODER_BASE_URL", "https://coder.api.visioncoder.cn/v1"))
    p.add_argument("--visioncoder-api-key", default=os.getenv("VISIONCODER_API_KEY", ""))
    p.add_argument("--llm-timeout", type=float, default=90.0)
    p.add_argument("--llm-log-io", action="store_true", help="Print LLM outputs only; prompts are not printed")
    p.add_argument("--no-thinking", dest="thinking", action="store_false", default=True)
    p.add_argument("--reasoning-effort", default="high", choices=["low", "medium", "high", "max"], help="Thinking strength when reflection thinking is enabled; DeepSeek uses high|max")
    p.add_argument("--thinking-budget", type=int, default=0, help="Qwen thinking token budget during reflection; 0 maps reasoning effort to a default budget")
    p.add_argument("--decision-format", default="auto", choices=["auto", "json", "tool"], help="Structured reflection transport: auto uses JSON output for DeepSeek and tool calls for Qwen")
    return p.parse_args()


def main() -> None:
    args = parse_args()
    if args.provider == "qwen" and args.model == "deepseek-v4-flash":
        args.model = "qwen3.6-plus"
    if args.provider == "visioncoder" and args.model == "deepseek-v4-pro":
        args.model = os.getenv("VISIONCODER_MODEL", "gpt-5.6-sol")
    api_key = _provider_api_key(args)
    base_url = _provider_base_url(args)
    if not api_key:
        env_name = _provider_key_name(args.provider)
        print(f"[fatal] {env_name} is empty")
        return

    out_dir = Path(args.out_dir)
    review_items = _load_ante_review_items(out_dir)
    hardest, easiest = select_extreme_reviews(review_items, n=args.extreme_count)
    rulebook_path = out_dir / "rulebook.md"
    existing_rules = _read_existing_rules(rulebook_path)
    seeded_from = None
    if not existing_rules:
        seed_path = Path(__file__).resolve().parent / "bak" / "rulebook.md"
        existing_rules = _read_existing_rules(seed_path)
        seeded_from = str(seed_path) if existing_rules else None
    indexed_rules = [{"id": f"R{i}", "rule": rule} for i, rule in enumerate(existing_rules, 1)]

    prompt = {
        "task": "Compare the hardest and easiest complete Ante trajectories, then incrementally edit the existing Balatro rulebook.",
        "output_contract": {
            "operations": "Return only add/update/delete operations against the indexed existing rules.",
            "incremental_only": f"Make 0-{args.max_rule_edits} focused edits. Never return or restate the complete rulebook.",
        },
        "existing_rules": indexed_rules,
        "selection_policy": {
            "hardest": f"Top {args.extreme_count} complete Antes by LLM effort score; losses are always 10.",
            "easiest": f"Bottom {args.extreme_count} non-overlapping complete Antes by effort score.",
            "contrast": "Prefer lessons that explain why similar resources or decisions led to different effort, not generic Balatro advice.",
        },
        "hardest_antes": hardest,
        "easiest_antes": easiest,
        "requirements": [
            "Every operation must cite concrete contrasting trajectory evidence in reason.",
            "Use update when an existing rule is directionally right but needs a condition or correction; use delete only when selected trajectories contradict or duplicate it.",
            "Use add only for a reusable decision rule absent from the indexed rulebook.",
            "Do not edit a rule merely because wording could be nicer.",
            "Rules must be actionable during PLAY or SHOP and must not mention these sampled run IDs.",
            "An empty operations list is valid when the selected evidence does not justify a rule change.",
        ],
    }
    prompt = _trim_prompt(prompt, args.max_prompt_chars)

    policy = DeepSeekPolicy(
        api_key=api_key,
        model=args.model,
        url=base_url,
        timeout=args.llm_timeout,
        log_io=args.llm_log_io,
        reasoning_effort=args.reasoning_effort,
        thinking_budget=args.thinking_budget,
        provider=args.provider,
        decision_format=args.decision_format,
    )
    try:
        reflected = policy.reflect(prompt, thinking=args.thinking, max_tokens=2600)
    except Exception as e:
        reflected = {"operations": [], "llm_error": str(e)}

    rules, applied, rejected = _apply_rule_operations(existing_rules, reflected.get("operations"), args.max_rule_edits)
    _write_rulebook(rulebook_path, rules)

    report_dir = out_dir / "reflection_reports"
    report_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    report_path = report_dir / f"reflection_{ts}.json"
    report = {
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "selection": {"hardest": hardest, "easiest": easiest, "extreme_count": args.extreme_count},
        "rules_before": existing_rules,
        "requested_operations": reflected.get("operations") or [],
        "applied_operations": applied,
        "rejected_operations": rejected,
        "rules_after": rules,
        "commentary": reflected.get("commentary"),
        "llm_error": reflected.get("llm_error"),
        "seeded_from": seeded_from,
    }
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print(
        f"reflected ante_reviews={len(review_items)} hardest={len(hardest)} easiest={len(easiest)} "
        f"applied_edits={len(applied)} rejected_edits={len(rejected)} rules={len(rules)}"
    )
    print(f"wrote rulebook={out_dir / 'rulebook.md'}")
    print(f"wrote report={report_path}")


def _load_ante_review_items(out_dir: Path) -> List[Dict[str, Any]]:
    items = read_jsonl(out_dir / "memory" / "ante_reviews.jsonl")
    if items:
        return items
    return _backfill_legacy_ante_reviews(out_dir)


def _backfill_legacy_ante_reviews(out_dir: Path) -> List[Dict[str, Any]]:
    """Make old runs selectable; new runs use LLM-generated reviews at play time."""
    out: List[Dict[str, Any]] = []
    for path in sorted((out_dir / "runs").glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8-sig"))
        except Exception:
            continue
        result = data.get("result") or {}
        events = result.get("events") or []
        max_ante = int(result.get("ante") or 0)
        for ante in range(1, max_ante + 1):
            failed = bool(result.get("state") == "GAME_OVER" and not result.get("won") and ante == max_ante)
            trajectory = build_ante_trajectory(ante, events, failed=failed)
            if not trajectory.get("events"):
                continue
            score = heuristic_effort_score(trajectory)
            review = normalize_effort_review(
                {
                    "effort_score": score,
                    "luck_dependence": "unknown",
                    "summary": f"Legacy trajectory backfill using objective play/discard/resource metrics; heuristic effort={score}/10.",
                    "evidence": [
                        f"plays={trajectory['totals']['plays']}, discards={trajectory['totals']['discards']}, actions={trajectory['totals']['actions']}"
                    ],
                },
                trajectory,
            )
            out.append(
                {
                    "run_file": str(path),
                    "created_at": path.stem,
                    "review_source": "legacy_heuristic",
                    "review": review,
                    "trajectory": trajectory,
                }
            )
    return out


def _apply_rule_operations(
    existing_rules: List[str], operations: Any, max_edits: int
) -> tuple[List[str], List[Dict[str, Any]], List[Dict[str, Any]]]:
    rules = list(existing_rules)
    applied: List[Dict[str, Any]] = []
    rejected: List[Dict[str, Any]] = []
    original_ids = {f"R{i}": rule for i, rule in enumerate(existing_rules, 1)}
    touched = set()
    values = operations if isinstance(operations, list) else []
    for raw in values[: max(0, max_edits)]:
        op = dict(raw) if isinstance(raw, dict) else {}
        kind = str(op.get("op") or "").lower()
        target_id = str(op.get("target_id") or "").upper()
        rule = " ".join(str(op.get("rule") or "").split())
        reason = " ".join(str(op.get("reason") or "").split())
        error = ""
        if kind not in ("add", "update", "delete"):
            error = "invalid op"
        elif not reason:
            error = "missing evidence reason"
        elif kind == "add":
            if not rule:
                error = "add requires rule"
            elif rule.lower() in {x.lower() for x in rules}:
                error = "duplicate rule"
            else:
                rules.append(rule)
        elif target_id not in original_ids:
            error = "unknown target_id"
        elif target_id in touched:
            error = "target already edited"
        else:
            old = original_ids[target_id]
            try:
                index = rules.index(old)
            except ValueError:
                error = "target no longer present"
            else:
                if kind == "delete":
                    rules.pop(index)
                elif not rule:
                    error = "update requires replacement rule"
                else:
                    rules[index] = rule
                touched.add(target_id)
        record = {"op": kind, "target_id": target_id, "rule": rule, "reason": reason}
        if error:
            record["rejected"] = error
            rejected.append(record)
        else:
            applied.append(record)
    return _clean_rules(rules), applied, rejected


def _provider_api_key(args: argparse.Namespace) -> str:
    if args.provider == "qwen":
        return args.qwen_api_key
    if args.provider == "visioncoder":
        return args.visioncoder_api_key
    return args.deepseek_api_key


def _provider_base_url(args: argparse.Namespace) -> str:
    if args.provider == "qwen":
        return args.qwen_url
    if args.provider == "visioncoder":
        return args.visioncoder_url
    return args.deepseek_url


def _provider_key_name(provider: str) -> str:
    if provider == "qwen":
        return "QWEN_API_KEY or DASHSCOPE_API_KEY"
    if provider == "visioncoder":
        return "VISIONCODER_API_KEY"
    return "DEEPSEEK_API_KEY"


def _trim_prompt(prompt: Dict[str, Any], max_chars: int) -> Dict[str, Any]:
    out = dict(prompt)
    hardest = [_compact_ante_for_reflect(x) for x in (out.get("hardest_antes") or [])]
    easiest = [_compact_ante_for_reflect(x) for x in (out.get("easiest_antes") or [])]
    if hardest or easiest:
        out["hardest_antes"] = hardest
        out["easiest_antes"] = easiest
        while len(json.dumps(out, ensure_ascii=False)) > max_chars:
            candidates = [
                item
                for item in hardest + easiest
                if len((((item.get("trajectory") or {}).get("events")) or [])) > 4
            ]
            if not candidates:
                break
            largest = max(candidates, key=lambda item: len(((item.get("trajectory") or {}).get("events")) or []))
            trajectory = dict(largest.get("trajectory") or {})
            events = list(trajectory.get("events") or [])
            keep_each = max(2, len(events) // 3)
            trajectory["events"] = events[:keep_each] + events[-keep_each:]
            trajectory["events_trimmed"] = len(events) - len(trajectory["events"])
            largest["trajectory"] = trajectory
        return out
    play = list(out.get("play_samples") or [])
    shop = list(out.get("shop_samples") or [])
    death = list(out.get("death_focus_samples") or [])
    while len(json.dumps(out, ensure_ascii=False)) > max_chars and (play or shop or len(death) > 2):
        if play:
            play.pop()
        elif len(shop) > 2:
            shop.pop()
        elif len(death) > 2:
            death.pop()
        elif shop:
            shop.pop()
        out["play_samples"] = play
        out["shop_samples"] = shop
        out["death_focus_samples"] = death
    return out


def _compact_ante_for_reflect(item: Dict[str, Any]) -> Dict[str, Any]:
    trajectory = item.get("trajectory") or {}
    events = list(trajectory.get("events") or [])
    if len(events) > 12:
        events = events[:4] + events[-8:]
    compact_events = []
    for event in events:
        compact_events.append(
            {
                key: event.get(key)
                for key in ("step", "stage", "blind", "action", "target", "cards", "score_delta", "hand", "before", "after", "error")
                if event.get(key) not in (None, "", [], {})
            }
        )
    return {
        "run_file": item.get("run_file"),
        "review_source": item.get("review_source", "llm"),
        "review": item.get("review") or {},
        "trajectory": {
            "ante": trajectory.get("ante"),
            "outcome": trajectory.get("outcome"),
            "failed": trajectory.get("failed"),
            "boss": trajectory.get("boss") or {},
            "jokers_over_time": trajectory.get("jokers_over_time") or [],
            "rounds": trajectory.get("rounds") or [],
            "totals": trajectory.get("totals") or {},
            "shop_actions": [
                {k: action.get(k) for k in ("stage", "action", "target", "money_before", "money_after") if action.get(k) is not None}
                for action in (trajectory.get("shop_actions") or [])
            ],
            "events": compact_events,
            "events_omitted": max(0, len(trajectory.get("events") or []) - len(compact_events)),
        },
    }


def _clean_rules(value: Any, limit: int = 80) -> List[str]:
    if not isinstance(value, list):
        return []
    seen = set()
    rules: List[str] = []
    for item in value:
        text = " ".join(str(item or "").split())
        key = text.lower()
        if not text or key in seen:
            continue
        seen.add(key)
        rules.append(text)
    return rules[:limit]


def _write_rulebook(path: Path, rules: List[str]) -> None:
    lines = [
        "# Balatro v1.4 Rulebook",
        "",
        f"Updated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        "",
        "## Summary Rules",
    ]
    if rules:
        lines.extend(f"- {r}" for r in rules)
    else:
        lines.append("- No reflected summary rules yet.")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _read_existing_rules(path: Path) -> List[str]:
    if not path.exists():
        return []
    out = []
    in_summary = False
    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw.strip()
        if line.startswith("## "):
            in_summary = line == "## Summary Rules"
            continue
        if not in_summary:
            continue
        if line.startswith("- "):
            text = line[2:].strip()
            if text and not text.startswith("No reflected"):
                out.append(text)
    return out


if __name__ == "__main__":
    main()
