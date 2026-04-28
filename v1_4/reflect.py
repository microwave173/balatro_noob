import argparse
import json
import os
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

if __package__ is None or __package__ == "":
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from v1_4.core.deepseek_policy import DeepSeekPolicy
from v1_4.core.memory import read_jsonl


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Reflect on v1.4 memories and rewrite rulebook guidance")
    p.add_argument("--out-dir", default="v1_4/out")
    p.add_argument("--max-play", type=int, default=120)
    p.add_argument("--max-shop", type=int, default=80)
    p.add_argument("--samples-per-group", type=int, default=1)
    p.add_argument("--max-groups", type=int, default=6)
    p.add_argument("--max-prompt-chars", type=int, default=45000)
    p.add_argument("--death-runs", type=int, default=6)
    p.add_argument("--death-tail-events", type=int, default=8)
    p.add_argument("--provider", default=os.getenv("LLM_PROVIDER", "deepseek"), choices=["deepseek", "qwen"])
    p.add_argument("--model", default=os.getenv("DEEPSEEK_MODEL", "deepseek-v4-pro"))
    p.add_argument("--deepseek-url", default=os.getenv("DEEPSEEK_BASE_URL", os.getenv("DEEPSEEK_URL", "https://api.deepseek.com")))
    p.add_argument("--deepseek-api-key", default=os.getenv("DEEPSEEK_API_KEY", ""))
    p.add_argument("--qwen-url", default=os.getenv("QWEN_BASE_URL", os.getenv("DASHSCOPE_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1")))
    p.add_argument("--qwen-api-key", default=os.getenv("QWEN_API_KEY", os.getenv("DASHSCOPE_API_KEY", "")))
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
    api_key = args.qwen_api_key if args.provider == "qwen" else args.deepseek_api_key
    base_url = args.qwen_url if args.provider == "qwen" else args.deepseek_url
    if not api_key:
        env_name = "QWEN_API_KEY or DASHSCOPE_API_KEY" if args.provider == "qwen" else "DEEPSEEK_API_KEY"
        print(f"[fatal] {env_name} is empty")
        return

    out_dir = Path(args.out_dir)
    memory_dir = out_dir / "memory"
    play_items = read_jsonl(memory_dir / "play_memory.jsonl", limit=args.max_play)
    shop_items = read_jsonl(memory_dir / "shop_memory.jsonl", limit=args.max_shop)

    play_samples = _select_grouped_samples(play_items, args.samples_per_group, args.max_groups)
    shop_samples = _select_grouped_samples(shop_items, args.samples_per_group, args.max_groups)
    death_focus_samples = _select_death_focus_samples(out_dir, args.death_runs, args.death_tail_events)
    existing_rules = _read_existing_rules(out_dir / "rulebook.md")

    prompt = {
        "task": "Reflect on Balatro v1.4 play/shop memories and rewrite the complete rulebook.",
        "output_contract": {
            "rules": "Return the complete updated rulebook as an ordered list of concise, human-readable rules. Do not return skills, mistakes, triggers, confidence, or JSON files.",
            "full_update": "This is a full rewrite every time. Keep still-useful existing rules, revise outdated or misleading rules, add new lessons, and delete rules that no longer help.",
        },
        "existing_rules": existing_rules,
        "selection_policy": {
            "play": "one high-chip and one low-chip example per joker_signature; death_focus carries the detailed losing trajectory",
            "shop": "small sample preserving current jokers, next boss, shop contents, and future result",
            "death_focus": "for lost runs, focus on the last events, boss, Jokers, money, final plays, and last shop decisions; these outweigh long early trajectory",
        },
        "play_samples": play_samples,
        "shop_samples": shop_samples,
        "death_focus_samples": death_focus_samples,
        "requirements": [
            "Return only rules, as the complete rulebook.",
            "Rules should be practical guidance the agent can use directly during play and shop decisions.",
            "Keep the rulebook compact enough to fit in future prompts, roughly 20-60 rules.",
            "Pay special attention to death runs: final PLAY events, boss effect, current Jokers, money left, and last SHOP decisions before death.",
            "Include lessons about score estimation, discard-vs-play logic, Joker synergy, economy, scaling, XMult, boss counters, selling obsolete Jokers, and reroll discipline when supported by samples.",
            "Remove or rewrite rules that are too rigid, too narrow, contradicted by samples, or duplicated.",
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
        reflected = {"rules": [], "llm_error": str(e)}

    rules = _clean_rules(reflected.get("rules"))
    if not rules:
        retry_prompt = dict(prompt)
        retry_prompt["requirements"] = list(prompt["requirements"]) + [
            "The previous reflection returned no rules. Return a non-empty complete rulebook in the rules array.",
        ]
        retry_prompt = _trim_prompt(retry_prompt, max(18000, args.max_prompt_chars // 2))
        try:
            reflected = policy.reflect(retry_prompt, thinking=args.thinking, max_tokens=2200)
        except Exception as e:
            reflected = {"rules": [], "llm_error": str(e)}
        rules = _clean_rules(reflected.get("rules"))

    if not rules:
        rules = _fallback_rules(existing_rules, play_samples, shop_samples)
        reflected = dict(reflected)
        reflected["rules"] = rules
        reflected["fallback"] = True

    _write_rulebook(out_dir / "rulebook.md", rules)

    report_dir = out_dir / "reflection_reports"
    report_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    report_path = report_dir / f"reflection_{ts}.json"
    report_path.write_text(json.dumps(reflected, ensure_ascii=False, indent=2), encoding="utf-8")

    print(
        f"reflected play_samples={len(play_items)} shop_samples={len(shop_items)} "
        f"selected_play={len(play_samples)} selected_shop={len(shop_samples)} "
        f"death_focus={len(death_focus_samples)} rules={len(rules)}"
    )
    print(f"wrote rulebook={out_dir / 'rulebook.md'}")
    print(f"wrote report={report_path}")


def _select_grouped_samples(items: List[Dict[str, Any]], x: int, max_groups: int) -> List[Dict[str, Any]]:
    groups: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for item in items:
        sig = "|".join(item.get("joker_signature") or ["NO_JOKERS"])
        groups[sig].append(item)

    selected: List[Dict[str, Any]] = []
    ranked_groups = sorted(groups.items(), key=lambda kv: len(kv[1]), reverse=True)[:max_groups]
    for sig, group in ranked_groups:
        ordered = sorted(group, key=lambda it: int(((it.get("result") or {}).get("chips_delta")) or 0), reverse=True)
        death = [
            it
            for it in group
            if (((it.get("result") or {}).get("after") or {}).get("state") == "GAME_OVER")
            or not bool(((it.get("result") or {}).get("survived_step", True)))
        ]
        death = sorted(
            death,
            key=lambda it: (
                int((((it.get("result") or {}).get("before") or {}).get("ante")) or 0),
                int((((it.get("result") or {}).get("before") or {}).get("round")) or 0),
                int((((it.get("result") or {}).get("before") or {}).get("money")) or 0),
            ),
            reverse=True,
        )
        picks = death[:1] + ordered[:x] + ordered[-x:]
        seen = set()
        for p in picks:
            key = id(p)
            if key in seen:
                continue
            seen.add(key)
            selected.append(_compact_memory_for_reflect(sig, p))
    return selected


def _select_death_focus_samples(out_dir: Path, max_runs: int, tail_events: int) -> List[Dict[str, Any]]:
    runs_dir = out_dir / "runs"
    if not runs_dir.exists():
        return []
    files = sorted((p for p in runs_dir.glob("*.json") if p.is_file()), key=lambda p: p.stat().st_mtime, reverse=True)
    selected: List[Dict[str, Any]] = []
    for path in files:
        if len(selected) >= max_runs:
            break
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        result = data.get("result") or {}
        if bool(result.get("won")) or result.get("state") != "GAME_OVER":
            continue
        events = [e for e in (result.get("events") or []) if isinstance(e, dict)]
        if not events:
            continue
        tail = events[-tail_events:]
        last_shop = [e for e in events if e.get("stage") == "SHOP"][-4:]
        selected.append(
            {
                "run_file": str(path),
                "final": {
                    "ante": result.get("ante"),
                    "round": result.get("round"),
                    "money": result.get("money"),
                    "buy_count": result.get("buy_count"),
                    "buy_examples": result.get("buy_examples"),
                    "state": result.get("state"),
                },
                "last_shop_events": [_compact_event_for_death(e) for e in last_shop],
                "final_events": [_compact_event_for_death(e) for e in tail],
            }
        )
    return selected


def _compact_event_for_death(event: Dict[str, Any]) -> Dict[str, Any]:
    obs = event.get("observation") or {}
    state = obs.get("state") or {}
    return {
        "step": event.get("step"),
        "stage": event.get("stage"),
        "joker_signature": event.get("joker_signature") or [],
        "boss": obs.get("boss") or {},
        "jokers": _card_labels(state.get("jokers")),
        "hand": _hand_summary(state.get("hand")),
        "shop": _card_labels(state.get("shop")),
        "packs": _card_labels(state.get("packs")),
        "vouchers": _card_labels(state.get("vouchers")),
        "round_resources": _round_summary(state),
        "decision": event.get("decision"),
        "action": {"type": event.get("action"), "params": event.get("params")},
        "before": event.get("before"),
        "after": event.get("after"),
    }


def _compact_memory_for_reflect(signature: str, item: Dict[str, Any]) -> Dict[str, Any]:
    obs = item.get("observation") or {}
    state = obs.get("state") or {}
    before = ((item.get("result") or {}).get("before")) or {}
    after = ((item.get("result") or {}).get("after")) or {}
    return {
        "joker_signature": signature,
        "phase": obs.get("phase"),
        "run": {
            "ante": state.get("ante_num") or before.get("ante"),
            "round": state.get("round_num") or before.get("round"),
            "money": state.get("money") or before.get("money"),
            "state": state.get("state"),
        },
        "blind": obs.get("boss") or {},
        "jokers": _card_labels(state.get("jokers")),
        "hand": _hand_summary(state.get("hand")),
        "shop": _card_labels(state.get("shop")),
        "packs": _card_labels(state.get("packs")),
        "vouchers": _card_labels(state.get("vouchers")),
        "round_resources": _round_summary(state),
        "inspected_deck": bool(item.get("inspected_deck")),
        "decision": item.get("decision"),
        "action": item.get("action"),
        "result": {
            "chips_delta": ((item.get("result") or {}).get("chips_delta")),
            "survived_step": ((item.get("result") or {}).get("survived_step")),
            "before": before,
            "after": after,
        },
    }


def _card_labels(area: Any, limit: int = 8) -> List[str]:
    cards = ((area or {}).get("cards")) or []
    out = []
    for c in cards[:limit]:
        value = c.get("value") or {}
        cost = (c.get("cost") or {}).get("buy")
        text = str(c.get("label") or c.get("key") or "?")
        effect = str(value.get("effect") or "").strip()
        if effect:
            text += f": {effect[:120]}"
        if cost is not None:
            text += f" cost={cost}"
        out.append(text)
    return out


def _hand_summary(area: Any, limit: int = 8) -> List[str]:
    cards = ((area or {}).get("cards")) or []
    out = []
    for i, c in enumerate(cards[:limit]):
        value = c.get("value") or {}
        out.append(f"{i}:{value.get('rank', '?')}{value.get('suit', '?')}")
    return out


def _round_summary(state: Dict[str, Any]) -> Dict[str, Any]:
    rnd = state.get("round") or {}
    return {
        "chips": rnd.get("chips"),
        "hands_left": rnd.get("hands_left"),
        "discards_left": rnd.get("discards_left"),
        "hands_played": rnd.get("hands_played"),
        "discards_used": rnd.get("discards_used"),
    }


def _trim_prompt(prompt: Dict[str, Any], max_chars: int) -> Dict[str, Any]:
    out = dict(prompt)
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


def _fallback_rules(existing_rules: List[str], play_samples: List[Dict[str, Any]], shop_samples: List[Dict[str, Any]]) -> List[str]:
    rules = list(existing_rules)
    if play_samples:
        rules.extend(
            [
                "Before discarding or playing, estimate whether the best current hand can clear or make enough progress toward the blind.",
                "A discard does not consume a hand; with discards left, discard instead of playing a doomed weak hand when the current score is far below the blind target.",
                "Use Joker abilities deliberately, but do not force a Joker trigger when another line scores more or is safer against the boss.",
            ]
        )
    if shop_samples:
        rules.extend(
            [
                "When the build lacks stable scoring, prioritize affordable immediate Chips, Mult, or XMult over speculative value.",
                "With a large bank and weak or incomplete scoring, reroll for high-performance Jokers and boss counters instead of only hoarding interest.",
                "Scoring is Chips x Mult x XMult; identify the weakest component before buying or rerolling.",
            ]
        )
    return _clean_rules(rules)


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

