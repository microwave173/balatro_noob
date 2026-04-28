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

from v1_2.core.deepseek_policy import DeepSeekPolicy
from v1_2.core.memory import SkillMemory, read_jsonl


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Reflect on v1.2 memories and update structured skills")
    p.add_argument("--out-dir", default="v1_2/out")
    p.add_argument("--max-play", type=int, default=120)
    p.add_argument("--max-shop", type=int, default=80)
    p.add_argument("--samples-per-group", type=int, default=1)
    p.add_argument("--max-groups", type=int, default=6)
    p.add_argument("--max-prompt-chars", type=int, default=45000)
    p.add_argument("--death-runs", type=int, default=6)
    p.add_argument("--death-tail-events", type=int, default=8)
    p.add_argument("--model", default=os.getenv("DEEPSEEK_MODEL", "deepseek-v4-flash"))
    p.add_argument("--deepseek-url", default=os.getenv("DEEPSEEK_BASE_URL", os.getenv("DEEPSEEK_URL", "https://api.deepseek.com")))
    p.add_argument("--deepseek-api-key", default=os.getenv("DEEPSEEK_API_KEY", ""))
    p.add_argument("--llm-timeout", type=float, default=90.0)
    p.add_argument("--llm-log-io", action="store_true")
    p.add_argument("--no-thinking", dest="thinking", action="store_false", default=True)
    return p.parse_args()


def main() -> None:
    args = parse_args()
    if not args.deepseek_api_key:
        print("[fatal] DEEPSEEK_API_KEY is empty")
        return

    out_dir = Path(args.out_dir)
    memory_dir = out_dir / "memory"
    play_items = read_jsonl(memory_dir / "play_memory.jsonl", limit=args.max_play)
    shop_items = read_jsonl(memory_dir / "shop_memory.jsonl", limit=args.max_shop)

    play_samples = _select_grouped_samples(play_items, args.samples_per_group, args.max_groups)
    shop_samples = _select_grouped_samples(shop_items, args.samples_per_group, args.max_groups)
    death_focus_samples = _select_death_focus_samples(out_dir, args.death_runs, args.death_tail_events)
    prompt = {
        "task": "reflect on Balatro v1.2 play/shop memories and produce structured reusable skills",
        "selection_policy": {
            "play": "one high-chip and one low-chip example per joker_signature; death_focus carries the detailed losing trajectory",
            "shop": "small sample preserving current jokers, next boss, shop contents, and future result",
            "death_focus": "for lost runs, focus on the last events, boss, Jokers, money, final plays, and last shop decisions; these outweigh long early trajectory",
        },
        "play_samples": play_samples,
        "shop_samples": shop_samples,
        "death_focus_samples": death_focus_samples,
        "requirements": [
            "Produce specific Joker-aware play/discard skills.",
            "Produce boss-aware shop/reroll skills.",
            "Pay special attention to death runs: the final few PLAY events, the boss effect, current Jokers, money left, and the last SHOP decisions before death are more important than long early trajectory.",
            "If a run dies with a lot of unspent money or weak late-game scoring, produce shop skills about rolling for high-impact Jokers, XMult, scaling, and boss counters.",
            "Keep skills natural language but with structured triggers.",
            "Focus on whether play decisions preserved hands, used discards purposefully, and scored enough rather than too little.",
            "Mention concrete mistakes when a bad action was likely avoidable.",
        ],
    }
    prompt = _trim_prompt(prompt, args.max_prompt_chars)

    policy = DeepSeekPolicy(
        api_key=args.deepseek_api_key,
        model=args.model,
        url=args.deepseek_url,
        timeout=args.llm_timeout,
        log_io=args.llm_log_io,
    )
    try:
        reflected = policy.reflect(prompt, thinking=args.thinking, max_tokens=2600)
    except Exception as e:
        reflected = {
            "play_skills": [],
            "shop_skills": [],
            "mistakes": [],
            "rules": [],
            "llm_error": str(e),
        }
    if not _has_reflection_content(reflected):
        retry_prompt = dict(prompt)
        retry_prompt["requirements"] = list(prompt["requirements"]) + [
            "The previous reflection returned no useful content. Return non-empty arrays when samples exist.",
            "At minimum, produce one play skill or one mistake from the provided samples.",
        ]
        retry_prompt = _trim_prompt(retry_prompt, max(18000, args.max_prompt_chars // 2))
        try:
            reflected = policy.reflect(retry_prompt, thinking=False, max_tokens=2200)
        except Exception as e:
            reflected = {
                "play_skills": [],
                "shop_skills": [],
                "mistakes": [],
                "rules": [],
                "llm_error": str(e),
            }
    if not _has_reflection_content(reflected):
        reflected = _fallback_reflection(play_samples, shop_samples)

    play_skills = _clean_skills(_as_list(reflected.get("play_skills")), "PLAY")
    shop_skills = _clean_skills(_as_list(reflected.get("shop_skills")), "SHOP")
    mistakes = _clean_mistakes(_as_list(reflected.get("mistakes")))
    new_rules = [str(r).strip() for r in _as_list(reflected.get("rules")) if str(r).strip()]
    rules = _merge_rules(_read_existing_rules(out_dir / "rulebook.md"), new_rules)

    memory = SkillMemory(memory_dir)
    if play_skills or shop_skills:
        memory.save_skills(play_skills, shop_skills)
    if mistakes:
        memory.append_mistakes(mistakes)

    report_dir = out_dir / "reflection_reports"
    report_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    report_path = report_dir / f"reflection_{ts}.json"
    report_path.write_text(json.dumps(reflected, ensure_ascii=False, indent=2), encoding="utf-8")
    _write_rulebook(out_dir / "rulebook.md", rules, memory.play_skills, memory.shop_skills)

    print(
        f"reflected play_samples={len(play_items)} shop_samples={len(shop_items)} "
        f"selected_play={len(play_samples)} selected_shop={len(shop_samples)} "
        f"death_focus={len(death_focus_samples)} "
        f"play_skills={len(play_skills)} shop_skills={len(shop_skills)} mistakes={len(mistakes)}"
    )
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
        "used_skills": item.get("used_skills") or [],
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


def _has_reflection_content(reflected: Dict[str, Any]) -> bool:
    if not isinstance(reflected, dict):
        return False
    return any(_as_list(reflected.get(k)) for k in ("play_skills", "shop_skills", "mistakes", "rules"))


def _clean_skills(items: List[Any], phase: str) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    now = datetime.now().strftime("%Y%m%d%H%M%S")
    for i, item in enumerate(items):
        if not isinstance(item, dict):
            continue
        text = str(item.get("policy_text") or item.get("rule") or item.get("text") or "").strip()
        if not text:
            continue
        sid = str(item.get("id") or "").strip()
        if not sid:
            sid = f"reflected_{phase.lower()}_{now}_{i}"
        trigger = item.get("trigger") if isinstance(item.get("trigger"), dict) else {}
        trigger = dict(trigger)
        trigger.setdefault("phase", phase)
        try:
            confidence = float(item.get("confidence", 0.55) or 0.55)
        except Exception:
            confidence = 0.55
        severity = str(item.get("severity") or "medium").lower()
        if severity not in {"low", "medium", "high", "critical"}:
            severity = "medium"
        out.append(
            {
                "id": sid,
                "trigger": trigger,
                "policy_text": text,
                "confidence": max(0.0, min(1.0, confidence)),
                "severity": severity,
            }
        )
    return out


def _clean_mistakes(items: List[Any]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        pattern = str(item.get("pattern") or item.get("mistake") or "").strip()
        better = str(item.get("better_action") or item.get("better") or "").strip()
        if not pattern and not better:
            continue
        kind = str(item.get("kind") or "play").lower()
        if kind not in {"play", "shop"}:
            kind = "play"
        severity = str(item.get("severity") or "medium").lower()
        if severity not in {"low", "medium", "high", "critical"}:
            severity = "medium"
        out.append({"kind": kind, "pattern": pattern, "better_action": better, "severity": severity})
    return out


def _fallback_reflection(play_samples: List[Dict[str, Any]], shop_samples: List[Dict[str, Any]]) -> Dict[str, Any]:
    mistakes: List[Dict[str, Any]] = []
    rules: List[str] = []
    play_skills: List[Dict[str, Any]] = []
    shop_skills: List[Dict[str, Any]] = []

    bad_play = [s for s in play_samples if not ((s.get("result") or {}).get("survived_step"))]
    wasted_discards = [
        s
        for s in play_samples
        if ((s.get("result") or {}).get("after") or {}).get("state") == "GAME_OVER"
        and ((_res_before(s).get("discards_left") or 0) > 0)
    ]
    no_joker = [s for s in play_samples if s.get("joker_signature") == "NO_JOKERS"]

    if no_joker:
        play_skills.append(
            {
                "id": "fallback_no_joker_use_discards_for_real_hand",
                "trigger": {"phase": "PLAY", "jokers_any": [], "boss_effect_contains": ""},
                "policy_text": "With no Jokers, do not spend repeated hands on weak High Card or small Pair scoring. Use early discards toward a realistic Flush, Straight, Full House, Trips, or Two Pair, then play the strongest available hand before hands run out.",
                "confidence": 0.65,
                "severity": "high",
            }
        )
        rules.append("Without scoring Jokers, preserve hands by using purposeful discards toward realistic higher-value poker hands.")

    if wasted_discards or bad_play:
        mistakes.append(
            {
                "kind": "play",
                "pattern": "Run died while discards or setup opportunities remained, often after low-chip plays.",
                "better_action": "Before each play, compare the best current score against the blind target; discard only with a concrete improvement target, otherwise play the strongest scoring hand.",
                "severity": "high",
            }
        )
        rules.append("Before discarding or playing, estimate whether the best current hand can clear or make enough progress toward the blind.")

    if shop_samples:
        shop_skills.append(
            {
                "id": "fallback_shop_buy_immediate_scoring_when_weak",
                "trigger": {"phase": "SHOP", "jokers_any": [], "next_boss_effect_contains": ""},
                "policy_text": "When the build lacks stable scoring, prioritize affordable immediate Chips or Mult Jokers and useful Buffoon packs over speculative rerolls or low-impact purchases.",
                "confidence": 0.6,
                "severity": "medium",
            }
        )
        rules.append("In early shops, buy immediate scoring before speculative value when survival is not secure.")
        shop_skills.append(
            {
                "id": "fallback_shop_roll_with_bank_for_power_jokers",
                "trigger": {"phase": "SHOP", "jokers_any": [], "next_boss_effect_contains": ""},
                "policy_text": "If money is high and the build still lacks late-game power, spend part of the bank rerolling for high-impact Jokers: XMult, strong scaling Chips/Mult, Joker-copy effects, or boss-countering utility. Do not leave a shop with a large bank and a weak build just to preserve interest.",
                "confidence": 0.68,
                "severity": "high",
            }
        )
        rules.append("With a large bank and weak or incomplete scoring, actively reroll for high-performance Jokers and boss counters instead of only hoarding money.")

    return {
        "play_skills": play_skills,
        "shop_skills": shop_skills,
        "mistakes": mistakes,
        "rules": rules,
        "fallback": True,
        "reason": "LLM reflection returned no usable content; generated conservative local reflection from samples.",
    }


def _res_before(sample: Dict[str, Any]) -> Dict[str, Any]:
    return (((sample.get("result") or {}).get("before")) or {})


def _write_rulebook(path: Path, rules: List[str], play_skills: List[Dict[str, Any]], shop_skills: List[Dict[str, Any]]) -> None:
    lines = [
        "# Balatro v1.2 Rulebook",
        "",
        f"Updated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        "",
        "## Summary Rules",
    ]
    if rules:
        lines.extend(f"- {r}" for r in rules)
    else:
        lines.append("- No reflected summary rules yet.")
    lines.extend(["", "## Play Skills"])
    lines.extend(f"- {s.get('id', 'skill')}: {s.get('policy_text', '')}" for s in play_skills[:20])
    lines.extend(["", "## Shop Skills"])
    lines.extend(f"- {s.get('id', 'skill')}: {s.get('policy_text', '')}" for s in shop_skills[:20])
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


def _merge_rules(existing: List[str], new: List[str], limit: int = 80) -> List[str]:
    seen = set()
    merged = []
    for rule in existing + new:
        key = " ".join(str(rule).lower().split())
        if not key or key in seen:
            continue
        seen.add(key)
        merged.append(str(rule).strip())
    return merged[-limit:]


def _as_list(value: Any) -> List[Any]:
    return value if isinstance(value, list) else []


if __name__ == "__main__":
    main()
