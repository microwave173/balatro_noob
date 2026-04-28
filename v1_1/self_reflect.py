import argparse
import json
import os
import re
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional
import urllib.request


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Reflect on Balatro run logs and update rulebook")
    p.add_argument("--runs-dir", default=os.getenv("AGENT_RUNS_DIR", "runs"))
    p.add_argument("--max-runs", type=int, default=50)
    p.add_argument("--output-skill-file", default=os.getenv("AGENT_SKILL_FILE", "agent_core/rulebook.md"))
    p.add_argument("--output-report-dir", default="reflection_reports")
    p.add_argument("--max-rules", type=int, default=24)
    p.add_argument("--merge-existing", dest="merge_existing", action="store_true", default=True)
    p.add_argument("--replace-rules", dest="merge_existing", action="store_false")

    p.add_argument("--use-llm", dest="use_llm", action="store_true", default=True)
    p.add_argument("--no-llm", dest="use_llm", action="store_false")
    p.add_argument("--provider", choices=["ollama", "deepseek"], default=os.getenv("LLM_PROVIDER", "deepseek"))
    p.add_argument("--model", default="")
    p.add_argument("--llm-timeout", type=float, default=45.0)
    p.add_argument("--ollama-url", default=os.getenv("OLLAMA_URL", "http://127.0.0.1:11434/api/chat"))
    p.add_argument("--deepseek-url", default=os.getenv("DEEPSEEK_URL", "https://api.deepseek.com/chat/completions"))
    p.add_argument("--deepseek-api-key", default=os.getenv("DEEPSEEK_API_KEY", ""))
    p.add_argument("--verbose", action="store_true")
    return p.parse_args()


def _resolve_model(provider: str, model: str) -> str:
    if model:
        return model
    if provider == "ollama":
        return os.getenv("OLLAMA_MODEL", "gemma4:e2b-it-q4_K_M")
    return os.getenv("DEEPSEEK_MODEL", "deepseek-v4-flash")


def _load_run_records(runs_dir: str, max_runs: int) -> List[Dict[str, Any]]:
    p = Path(runs_dir)
    if not p.exists():
        return []
    files = sorted([f for f in p.glob("*.json") if f.is_file()], key=lambda x: x.stat().st_mtime, reverse=True)
    records: List[Dict[str, Any]] = []
    for f in files[:max_runs]:
        try:
            records.append(json.loads(f.read_text(encoding="utf-8")))
        except Exception:
            continue
    return records


def _extract_score_from_why(why_text: str) -> Optional[int]:
    m = re.search(r"score=(\d+)", str(why_text or ""))
    if not m:
        return None
    try:
        return int(m.group(1))
    except Exception:
        return None


def _aggregate(records: List[Dict[str, Any]]) -> Dict[str, Any]:
    total = len(records)
    if total == 0:
        return {"games": 0}

    wins = 0
    ante_sum = 0
    round_sum = 0
    money_sum = 0
    early_death = 0
    stage_action = Counter()
    buy_counter = Counter()
    joker_counter = Counter()
    error_events = 0
    selecting_hand_events = 0
    selected_play_events = 0
    selected_discard_events = 0
    missed_best_play_events = 0
    total_play_gap = 0
    discard_with_play_available_events = 0

    for rec in records:
        result = rec.get("result") or {}
        wins += 1 if result.get("won") else 0
        ante = int(result.get("ante", 0) or 0)
        rnd = int(result.get("round", 0) or 0)
        money = int(result.get("money", 0) or 0)
        ante_sum += ante
        round_sum += rnd
        money_sum += money
        if ante <= 1:
            early_death += 1

        for b in (result.get("buy_examples") or []):
            buy_counter[b] += 1

        for e in (result.get("events") or []):
            if e.get("error"):
                error_events += 1
            st = e.get("stage", "UNKNOWN")
            state_obj = e.get("state") or {}
            for j in (state_obj.get("jokers") or []):
                joker_counter[str(j)] += 1
            action = (e.get("selected") or {}).get("action")
            if action:
                stage_action[f"{st}:{action}"] += 1

            if st == "SELECTING_HAND":
                selecting_hand_events += 1
                candidates = e.get("candidates") or []
                play_scores: List[int] = []
                for c in candidates:
                    if c.get("action") == "play":
                        score = _extract_score_from_why(c.get("why", ""))
                        if score is not None:
                            play_scores.append(score)
                best_play_score = max(play_scores) if play_scores else None

                selected = e.get("selected") or {}
                sel_action = selected.get("action")
                if sel_action == "play":
                    selected_play_events += 1
                    sel_score = _extract_score_from_why(selected.get("why", ""))
                    if best_play_score is not None and sel_score is not None and sel_score < best_play_score:
                        missed_best_play_events += 1
                        total_play_gap += (best_play_score - sel_score)
                elif sel_action == "discard":
                    selected_discard_events += 1
                    if best_play_score is not None:
                        discard_with_play_available_events += 1

    top_actions = stage_action.most_common(15)
    top_buys = buy_counter.most_common(15)
    top_jokers = joker_counter.most_common(12)
    missed_best_play_rate = (
        (missed_best_play_events / selected_play_events) if selected_play_events > 0 else 0.0
    )
    discard_rate_in_hand_stage = (
        (selected_discard_events / selecting_hand_events) if selecting_hand_events > 0 else 0.0
    )
    discard_with_play_available_rate = (
        (discard_with_play_available_events / selected_discard_events) if selected_discard_events > 0 else 0.0
    )
    avg_play_gap_when_missed = (
        (total_play_gap / missed_best_play_events) if missed_best_play_events > 0 else 0.0
    )

    return {
        "games": total,
        "win_rate": wins / total,
        "avg_ante": ante_sum / total,
        "avg_round": round_sum / total,
        "avg_money": money_sum / total,
        "early_death_rate": early_death / total,
        "error_events": error_events,
        "top_actions": top_actions,
        "top_buys": top_buys,
        "top_jokers": top_jokers,
        "selecting_hand_events": selecting_hand_events,
        "selected_play_events": selected_play_events,
        "selected_discard_events": selected_discard_events,
        "missed_best_play_events": missed_best_play_events,
        "missed_best_play_rate": missed_best_play_rate,
        "avg_play_gap_when_missed": avg_play_gap_when_missed,
        "discard_rate_in_hand_stage": discard_rate_in_hand_stage,
        "discard_with_play_available_rate": discard_with_play_available_rate,
    }


def _heuristic_rules(summary: Dict[str, Any]) -> List[str]:
    rules: List[str] = []
    if summary.get("games", 0) == 0:
        return [
            "Prioritize stable scoring hands over risky lines.",
            "In shop, prefer value Jokers first, then Planet/Tarot/Spectral.",
            "Avoid spending all money in a single shop unless power spike is obvious.",
            "Early game baseline: prefer easy Flush/Pair lines over forced high-variance lines.",
            "If no clear buy improves scoring this round, keep money and advance.",
            "Avoid chain rerolls before core scoring engine is online.",
        ]

    early = summary.get("early_death_rate", 0.0)
    avg_ante = summary.get("avg_ante", 0.0)
    top_actions = dict(summary.get("top_actions", []))
    missed_play_rate = summary.get("missed_best_play_rate", 0.0)
    avg_play_gap = summary.get("avg_play_gap_when_missed", 0.0)
    discard_with_play_rate = summary.get("discard_with_play_available_rate", 0.0)
    top_jokers = [name for name, _ in (summary.get("top_jokers") or [])[:3]]

    if early > 0.5 or avg_ante < 2.0:
        rules.append("During early antes, avoid skipping Small/Big blind unless economy is very strong.")
        rules.append("If current hand estimated score is weak and discards remain, prioritize one discard before play.")
        rules.append("Reduce early pack purchases when money is below 8; prefer reliable Joker value.")
        rules.append("Before Ante 3, prioritize at least one immediate scoring Joker over niche setup pieces.")

    shop_buy_ratio = sum(v for k, v in top_actions.items() if k.startswith("SHOP:buy"))
    shop_next_ratio = sum(v for k, v in top_actions.items() if k.startswith("SHOP:next_round"))
    if shop_buy_ratio > shop_next_ratio * 2:
        rules.append("Be more selective in shop: skip low-impact buys to preserve economy for stronger spikes.")
    else:
        rules.append("When shop has no clear value buy, choose next_round instead of forcing spend.")

    if summary.get("error_events", 0) > 0:
        rules.append("Prefer conservative actions when uncertain to avoid invalid-action loops.")
        rules.append("Avoid edge-case action sequences; prefer one-step safe actions to maintain stability.")

    if missed_play_rate >= 0.20:
        rules.append("In SELECTING_HAND, evaluate all play candidates and choose the highest estimated score unless survival needs a setup discard.")
        rules.append("When current Jokers reward specific traits (pair/flush/face/high-card), prioritize the hand that triggers the most active Joker bonuses.")
        if avg_play_gap >= 20:
            rules.append("Avoid low-value autopilot plays; if best candidate materially exceeds selected line, always prefer the higher-scoring line.")

    if discard_with_play_rate >= 0.40:
        rules.append("Discard only when current best playable line is unlikely to clear the blind and discards_left > 0.")
        rules.append("If a playable line is already strong, preserve discard resources for later draws.")

    if top_jokers:
        rules.append(f"Frequent Joker context seen: {', '.join(top_jokers)}. Add explicit hand-choice bias to activate these Jokers each round.")

    if not rules:
        rules.append("Keep current policy stable; prioritize incremental economy and consistent hand value.")
        rules.append("Continue preferring Jokers with broad utility over narrow synergy traps.")

    rules.append("When a blind is already mathematically beatable, avoid unnecessary discard risk.")
    rules.append("Target a balanced scaling profile by mid game: chips source + mult source + at least one xmult path.")
    rules.append("Preserve emergency economy buffer unless the current buy is a clear power spike.")
    return rules


def _call_ollama(ollama_url: str, model: str, timeout: float, prompt_obj: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    payload = {
        "model": model,
        "stream": False,
        "format": "json",
        "messages": [
            {
                "role": "system",
                "content": (
                    "You are a Balatro strategy reflection assistant. "
                    "Prioritize actionable hand-play/discard/Joker-synergy improvements. "
                    "Return strict JSON: {\"rules\": [\"...\"], \"notes\": \"...\"}."
                ),
            },
            {"role": "user", "content": json.dumps(prompt_obj, ensure_ascii=False)},
        ],
        "options": {"num_ctx": 4096, "num_thread": 8, "num_gpu": 999},
    }
    req = urllib.request.Request(
        ollama_url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        out = json.loads(resp.read().decode("utf-8"))
    raw = ((out.get("message") or {}).get("content") or "").strip()
    if not raw:
        return None
    parsed = json.loads(raw)
    return parsed if isinstance(parsed, dict) else None


def _call_deepseek(
    deepseek_url: str,
    deepseek_api_key: str,
    model: str,
    timeout: float,
    prompt_obj: Dict[str, Any],
) -> Optional[Dict[str, Any]]:
    if not deepseek_api_key:
        return None
    payload = {
        "model": model,
        "messages": [
            {
                "role": "system",
                "content": (
                    "You are a Balatro strategy reflection assistant. "
                    "Prioritize actionable hand-play/discard/Joker-synergy improvements. "
                    "Return strict JSON only: {\"rules\": [\"...\"], \"notes\": \"...\"}."
                ),
            },
            {"role": "user", "content": json.dumps(prompt_obj, ensure_ascii=False)},
        ],
        "temperature": 0.2,
        "max_tokens": 500,
        "response_format": {"type": "json_object"},
    }
    req = urllib.request.Request(
        deepseek_url,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {deepseek_api_key}",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        out = json.loads(resp.read().decode("utf-8"))
    choices = out.get("choices") or []
    if not choices:
        return None
    raw = ((choices[0].get("message") or {}).get("content") or "").strip()
    if not raw:
        return None
    parsed = json.loads(raw)
    return parsed if isinstance(parsed, dict) else None


def _llm_rules(args: argparse.Namespace, summary: Dict[str, Any], records_count: int) -> Optional[List[str]]:
    model = _resolve_model(args.provider, args.model)
    prompt_obj = {
        "task": "generate improved short actionable rules for next Balatro runs",
        "constraints": [
            "10-16 concise rules",
            "focus on reducing early deaths and improving consistency",
            "must include at least 4 rules specifically about SELECTING_HAND play/discard decisions",
            "must explicitly include how to maximize current Joker value during hand selection",
            "avoid vague advice",
            "output must be safe fallbacks if uncertain",
        ],
        "summary": summary,
        "records_count": records_count,
    }
    try:
        if args.provider == "ollama":
            parsed = _call_ollama(args.ollama_url, model, args.llm_timeout, prompt_obj)
        else:
            parsed = _call_deepseek(
                args.deepseek_url,
                args.deepseek_api_key,
                model,
                args.llm_timeout,
                prompt_obj,
            )
        if not parsed:
            return None
        rules = parsed.get("rules") or []
        rules = [str(r).strip() for r in rules if str(r).strip()]
        return rules if rules else None
    except Exception:
        return None


def _write_rulebook(path: str, rules: List[str], summary: Dict[str, Any], source: str) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# Balatro Agent Rulebook",
        "",
        f"Version: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"Source: {source}",
        "",
        "## Performance Snapshot",
        f"- Games analyzed: {summary.get('games', 0)}",
        f"- Win rate: {summary.get('win_rate', 0):.2%}",
        f"- Avg ante: {summary.get('avg_ante', 0):.2f}",
        f"- Avg round: {summary.get('avg_round', 0):.2f}",
        f"- Early death rate (ante<=1): {summary.get('early_death_rate', 0):.2%}",
        f"- Missed best play rate: {summary.get('missed_best_play_rate', 0):.2%}",
        f"- Avg play gap when missed: {summary.get('avg_play_gap_when_missed', 0):.2f}",
        f"- Discard-with-play-available rate: {summary.get('discard_with_play_available_rate', 0):.2%}",
        f"- Rules count: {len(rules)}",
        "",
        "## Rules",
    ]
    for r in rules:
        lines.append(f"- {r}")
    lines.append("")
    p.write_text("\n".join(lines), encoding="utf-8")


def _normalize_rule(r: str) -> str:
    return " ".join((r or "").strip().lower().split())


def _load_existing_rules(path: str) -> List[str]:
    p = Path(path)
    if not p.exists() or not p.is_file():
        return []
    try:
        lines = p.read_text(encoding="utf-8").splitlines()
    except Exception:
        return []

    in_rules = False
    out: List[str] = []
    for line in lines:
        if line.strip() == "## Rules":
            in_rules = True
            continue
        if in_rules and line.startswith("- "):
            txt = line[2:].strip()
            if txt:
                out.append(txt)
    return out


def _merge_rules(existing_rules: List[str], new_rules: List[str], max_rules: int) -> List[str]:
    # Keep newest insights first, then backfill from prior stable rules.
    merged_order = list(new_rules) + list(existing_rules)
    seen = set()
    merged: List[str] = []
    for r in merged_order:
        nr = _normalize_rule(r)
        if not nr or nr in seen:
            continue
        seen.add(nr)
        merged.append(r.strip())
        if len(merged) >= max(1, max_rules):
            break
    return merged


def _write_report(report_dir: str, summary: Dict[str, Any], rules: List[str], source: str) -> str:
    p = Path(report_dir)
    p.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out = p / f"reflection_{ts}.json"
    out.write_text(
        json.dumps(
            {
                "timestamp": ts,
                "source": source,
                "summary": summary,
                "rules": rules,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    return str(out)


def main() -> None:
    args = parse_args()
    records = _load_run_records(args.runs_dir, args.max_runs)
    summary = _aggregate(records)

    if summary.get("games", 0) == 0:
        print(f"[warn] no run records found in {args.runs_dir}")

    existing_rules = _load_existing_rules(args.output_skill_file) if args.merge_existing else []
    rules: Optional[List[str]] = None
    source = "heuristic"
    if args.use_llm:
        rules = _llm_rules(args, summary, len(records))
        if rules:
            source = f"llm:{args.provider}"

    if not rules:
        rules = _heuristic_rules(summary)

    rules = _merge_rules(existing_rules, rules, args.max_rules)
    if args.merge_existing:
        source = f"{source}+merge"

    _write_rulebook(args.output_skill_file, rules, summary, source)
    report_path = _write_report(args.output_report_dir, summary, rules, source)

    print(f"games={summary.get('games', 0)} win_rate={summary.get('win_rate', 0):.2%} avg_ante={summary.get('avg_ante', 0):.2f}")
    print(f"wrote skill file: {args.output_skill_file}")
    print(f"wrote report: {report_path}")
    if args.verbose:
        print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
