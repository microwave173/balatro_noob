import json
from typing import Any, Dict, List, Optional, Tuple


BLIND_NAMES = {1: "SMALL", 2: "BIG", 3: "BOSS"}


def ante_review_outcome(event: Dict[str, Any]) -> Optional[Tuple[int, bool]]:
    """Return (ante, failed) when an action finishes an ante or loses the run."""
    before = event.get("before") or {}
    after = event.get("after") or {}
    try:
        ante = int(before.get("ante") or 0)
    except Exception:
        return None
    if ante <= 0:
        return None
    if after.get("state") == "GAME_OVER" and not bool(after.get("won")):
        return ante, True
    try:
        next_ante = int(after.get("ante") or ante)
    except Exception:
        next_ante = ante
    if event.get("action") == "play" and next_ante > ante:
        return ante, False
    return None


def event_ante(event: Dict[str, Any]) -> int:
    before = event.get("before") or event.get("state") or {}
    try:
        return int(before.get("ante") or 0)
    except Exception:
        return 0


def build_ante_trajectory(ante: int, events: List[Dict[str, Any]], *, failed: bool) -> Dict[str, Any]:
    ante_events = [e for e in events if event_ante(e) == ante and e.get("stage") != "ANTE_REVIEW"]
    rounds: Dict[str, Dict[str, Any]] = {}
    shop_actions: List[Dict[str, Any]] = []
    joker_snapshots: List[List[str]] = []
    compact_events: List[Dict[str, Any]] = []
    boss: Dict[str, Any] = {}

    for event in ante_events:
        before = event.get("before") or {}
        after = event.get("after") or {}
        observation = event.get("observation") or {}
        state = observation.get("state") or {}
        decision = event.get("decision") or {}
        stage = str(event.get("stage") or "?")
        action = str(event.get("action") or decision.get("action") or "error")
        round_num = _as_int(before.get("round"))
        blind = blind_name_for_round(ante, round_num)
        jokers = [str(x) for x in (event.get("joker_signature") or [])]
        if jokers and (not joker_snapshots or joker_snapshots[-1] != jokers):
            joker_snapshots.append(jokers)

        boss_info = observation.get("boss") or {}
        if boss_info.get("name"):
            boss = {
                "name": boss_info.get("name"),
                "effect": boss_info.get("effect"),
                "score": boss_info.get("score"),
            }

        item: Dict[str, Any] = {
            "step": event.get("step"),
            "stage": stage,
            "blind": blind,
            "action": action,
            "target": decision.get("target"),
            "cards": decision.get("cards") or decision.get("targets"),
            "before": _effort_state(before),
            "after": _effort_state(after),
        }
        if decision.get("reason"):
            item["reason"] = _clip(decision.get("reason"), 220)
        if event.get("action_error") or event.get("error"):
            item["error"] = _clip(event.get("action_error") or event.get("error"), 180)
        if action == "play":
            item["score_delta"] = _score_delta(before, after)
            item["hand"] = _played_hand(decision)
        compact_events.append({k: v for k, v in item.items() if v not in (None, "", [], {})})

        if blind in BLIND_NAMES.values() and stage == "PLAY":
            summary = rounds.setdefault(
                blind,
                {
                    "round": round_num,
                    "plays": 0,
                    "discards": 0,
                    "uses": 0,
                    "score_deltas": [],
                    "hands_started": before.get("hands_left"),
                    "hands_left": after.get("hands_left"),
                    "discards_started": before.get("discards_left"),
                    "discards_left": after.get("discards_left"),
                    "required_score": _current_blind_required(state),
                    "final_score": after.get("chips"),
                    "failed": False,
                },
            )
            if action == "play":
                summary["plays"] += 1
                summary["score_deltas"].append(_score_delta(before, after))
            elif action == "discard":
                summary["discards"] += 1
            elif action == "use":
                summary["uses"] += 1
            if summary.get("hands_started") is None:
                summary["hands_started"] = before.get("hands_left")
            if summary.get("discards_started") is None:
                summary["discards_started"] = before.get("discards_left")
            summary["hands_left"] = after.get("hands_left")
            summary["discards_left"] = after.get("discards_left")
            summary["final_score"] = after.get("chips")
            if not summary.get("required_score"):
                summary["required_score"] = _current_blind_required(state)
            if after.get("state") == "GAME_OVER":
                summary["failed"] = True

        if stage in ("SHOP", "PACK"):
            shop_actions.append(
                {
                    "stage": stage,
                    "action": action,
                    "target": decision.get("target"),
                    "money_before": before.get("money"),
                    "money_after": after.get("money"),
                    "reason": _clip(decision.get("reason"), 180) if decision.get("reason") else None,
                }
            )

    totals = {
        "actions": len(ante_events),
        "plays": sum(int(r.get("plays") or 0) for r in rounds.values()),
        "discards": sum(int(r.get("discards") or 0) for r in rounds.values()),
        "shop_actions": len(shop_actions),
        "blinds_completed": sum(1 for r in rounds.values() if not r.get("failed") and r.get("plays")),
    }
    return {
        "ante": ante,
        "outcome": "LOSS" if failed else "CLEARED",
        "failed": bool(failed),
        "boss": boss,
        "jokers_over_time": joker_snapshots,
        "rounds": [dict({"blind": name}, **rounds[name]) for name in ("SMALL", "BIG", "BOSS") if name in rounds],
        "totals": totals,
        "shop_actions": [{k: v for k, v in item.items() if v is not None} for item in shop_actions],
        "events": compact_events,
    }


def normalize_effort_review(raw: Dict[str, Any], trajectory: Dict[str, Any]) -> Dict[str, Any]:
    failed = bool(trajectory.get("failed"))
    fallback = heuristic_effort_score(trajectory)
    score = _as_int(raw.get("effort_score")) or fallback
    score = 10 if failed else max(1, min(9, score))
    luck = str(raw.get("luck_dependence") or "unknown").lower()
    if luck not in ("low", "medium", "high", "unknown"):
        luck = "unknown"
    evidence = _string_list(raw.get("evidence"), limit=5, item_chars=260)
    factors = _string_list(raw.get("difficulty_factors"), limit=5, item_chars=220)
    if failed and not evidence:
        evidence = ["The run ended during this ante, so its effort score is forced to 10."]
    return {
        "ante": int(trajectory.get("ante") or 0),
        "outcome": trajectory.get("outcome"),
        "effort_score": score,
        "luck_dependence": luck,
        "difficulty_factors": factors,
        "evidence": evidence,
        "summary": _clip(raw.get("summary") or _fallback_summary(trajectory, score), 700),
        "improvement": _clip(raw.get("improvement"), 500),
        "forced_loss_score": failed,
    }


def heuristic_effort_score(trajectory: Dict[str, Any]) -> int:
    if trajectory.get("failed"):
        return 10
    rounds = trajectory.get("rounds") or []
    plays = sum(_as_int(r.get("plays")) for r in rounds)
    discards = sum(_as_int(r.get("discards")) for r in rounds)
    score = 2
    score += min(3, max(0, plays - max(1, len(rounds))))
    score += min(2, discards // 3)
    if any(_as_int(r.get("hands_left")) <= 0 for r in rounds):
        score += 2
    elif any(_as_int(r.get("hands_left")) == 1 for r in rounds):
        score += 1
    return max(1, min(9, score))


def compact_ante_reviews(reviews: List[Dict[str, Any]], limit: int = 8) -> List[str]:
    out = []
    for item in reviews[-limit:]:
        factors = ", ".join((item.get("difficulty_factors") or [])[:2]) or "none noted"
        out.append(
            f"Ante {item.get('ante')} {item.get('outcome')}: effort={item.get('effort_score')}/10, "
            f"luck={item.get('luck_dependence')}, factors={factors}; {item.get('summary') or ''}"
        )
    return out


def select_extreme_reviews(items: List[Dict[str, Any]], n: int = 3) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    valid = [x for x in items if 1 <= _as_int(((x.get("review") or {}).get("effort_score"))) <= 10]
    hardest = sorted(
        valid,
        key=lambda x: (
            _as_int((x.get("review") or {}).get("effort_score")),
            bool((x.get("trajectory") or {}).get("failed")),
            _as_int(((x.get("trajectory") or {}).get("totals") or {}).get("actions")),
        ),
        reverse=True,
    )[: max(0, n)]
    hard_ids = {_review_id(x) for x in hardest}
    easiest_pool = [x for x in valid if _review_id(x) not in hard_ids]
    easiest = sorted(
        easiest_pool,
        key=lambda x: (
            _as_int((x.get("review") or {}).get("effort_score")),
            _as_int(((x.get("trajectory") or {}).get("totals") or {}).get("actions")),
        ),
    )[: max(0, n)]
    return hardest, easiest


def _review_id(item: Dict[str, Any]) -> str:
    return f"{item.get('run_file', '')}:{(item.get('review') or {}).get('ante', '')}:{item.get('created_at', '')}"


def blind_name_for_round(ante: int, round_num: int) -> str:
    position = round_num - (max(1, ante) - 1) * 3
    return BLIND_NAMES.get(position, "SETUP")


def _current_blind_required(state: Dict[str, Any]) -> Any:
    blinds = state.get("blinds") or {}
    for key in ("small", "big", "boss"):
        blind = blinds.get(key) or {}
        if blind.get("status") in ("CURRENT", "SELECT", "SELECTED"):
            return blind.get("score")
    return None


def _played_hand(decision: Dict[str, Any]) -> str:
    cards = decision.get("cards")
    return f"cards={cards}" if isinstance(cards, list) else "unknown"


def _effort_state(state: Dict[str, Any]) -> Dict[str, Any]:
    keys = ("state", "ante", "round", "money", "chips", "hands_left", "discards_left", "won")
    return {k: state.get(k) for k in keys if state.get(k) is not None}


def _score_delta(before: Dict[str, Any], after: Dict[str, Any]) -> int:
    return _as_int(after.get("chips")) - _as_int(before.get("chips"))


def _as_int(value: Any) -> int:
    try:
        return int(value or 0)
    except Exception:
        return 0


def _clip(value: Any, limit: int) -> str:
    text = " ".join(str(value or "").split())
    return text if len(text) <= limit else text[: max(0, limit - 3)] + "..."


def _string_list(value: Any, *, limit: int, item_chars: int) -> List[str]:
    if not isinstance(value, list):
        return []
    return [_clip(x, item_chars) for x in value if str(x or "").strip()][:limit]


def _fallback_summary(trajectory: Dict[str, Any], score: int) -> str:
    totals = trajectory.get("totals") or {}
    return (
        f"Ante {trajectory.get('ante')} {trajectory.get('outcome')} with effort {score}/10; "
        f"plays={totals.get('plays', 0)}, discards={totals.get('discards', 0)}, "
        f"shop_actions={totals.get('shop_actions', 0)}."
    )


def serialized_chars(value: Any) -> int:
    return len(json.dumps(value, ensure_ascii=False, default=str))
