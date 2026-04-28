from typing import Any, Dict, List, Tuple


def validate_blind_action(action: Dict[str, Any], state: Dict[str, Any]) -> Tuple[str, Dict[str, Any] | None]:
    action = _effective_action(action)
    choice = str(action.get("action") or "").lower()
    if choice == "skip" and _can_skip(state):
        return "skip", None
    return "select", None


def validate_play_action(action: Dict[str, Any], state: Dict[str, Any]) -> Tuple[str, Dict[str, Any]]:
    action = _effective_action(action)
    act = str(action.get("action") or "").lower()
    cards = _clean_indexes(action.get("cards"), _hand_count(state), _select_limit(state))
    rnd = state.get("round") or {}

    if act == "use":
        target = str(action.get("target") or "").lower()
        parsed = _parse_target(target)
        if parsed and parsed[0] == "consumable":
            consumables = ((state.get("consumables") or {}).get("cards")) or []
            idx = parsed[1]
            if 0 <= idx < len(consumables):
                params = _validated_use_params(idx, consumables[idx], cards, state, allow_card_targets=True)
                if params:
                    return "use", params

    if act == "discard" and cards and int(rnd.get("discards_left", 0) or 0) > 0:
        return "discard", {"cards": cards}
    if act == "play" and cards:
        return "play", {"cards": cards}

    return "play", {"cards": _fallback_play_cards(state)}


def validate_shop_action(action: Dict[str, Any], state: Dict[str, Any]) -> Tuple[str, Dict[str, Any] | None]:
    action = _effective_action(action)
    act = str(action.get("action") or "").lower()
    target = str(action.get("target") or "").lower()
    money = int(state.get("money", 0) or 0)

    if act == "buy":
        parsed = _parse_target(target)
        if parsed:
            kind, idx = parsed
            area_name = {"card": "shop", "pack": "packs", "voucher": "vouchers"}.get(kind)
            area = state.get(area_name or "") or {}
            cards = area.get("cards") or []
            if 0 <= idx < len(cards):
                cost = int(((cards[idx].get("cost") or {}).get("buy")) or 0)
                if cost <= money:
                    return "buy", {kind: idx}

    if act == "use":
        parsed = _parse_target(target)
        if parsed and parsed[0] == "consumable":
            cards = ((state.get("consumables") or {}).get("cards")) or []
            if 0 <= parsed[1] < len(cards):
                params = _validated_use_params(parsed[1], cards[parsed[1]], action.get("cards"), state, allow_card_targets=False)
                if params:
                    return "use", params

    if act == "sell":
        parsed = _parse_target(target)
        if parsed:
            kind, idx = parsed
            if kind == "joker":
                cards = ((state.get("jokers") or {}).get("cards")) or []
                if 0 <= idx < len(cards) and not _has_flag(cards[idx], "eternal"):
                    return "sell", {"joker": idx}
            if kind == "consumable":
                cards = ((state.get("consumables") or {}).get("cards")) or []
                if 0 <= idx < len(cards):
                    return "sell", {"consumable": idx}

    if act == "reroll":
        reroll_cost = int(((state.get("round") or {}).get("reroll_cost")) or 5)
        if money >= reroll_cost:
            return "reroll", None

    return "next_round", None


def validate_pack_action(action: Dict[str, Any], state: Dict[str, Any]) -> Tuple[str, Dict[str, Any]]:
    action = _effective_action(action)
    target = str(action.get("target") or "").lower()
    if target == "skip":
        return "pack", {"skip": True}
    parsed = _parse_target(target)
    if parsed and parsed[0] == "card":
        cards = ((state.get("pack") or {}).get("cards")) or []
        if 0 <= parsed[1] < len(cards):
            params: Dict[str, Any] = {"card": parsed[1]}
            req = _target_requirement(cards[parsed[1]])
            if req.get("requires_joker"):
                if len(((state.get("jokers") or {}).get("cards")) or []) == 0:
                    return "pack", {"skip": True}
            if req.get("requires_cards"):
                raw_targets = action.get("targets")
                if raw_targets is None:
                    raw_targets = action.get("cards")
                targets = _clean_indexes(raw_targets, _hand_count(state), int(req.get("max", 5) or 5))
                if not _target_count_ok(targets, req):
                    return "pack", {"skip": True}
                params["targets"] = targets
            return "pack", params
    return "pack", {"skip": True}


def _effective_action(action: Dict[str, Any]) -> Dict[str, Any]:
    if isinstance(action, dict) and action.get("_parse_error") and isinstance(action.get("_raw_decision"), dict):
        merged = dict(action)
        for key, value in (action.get("_raw_decision") or {}).items():
            if value not in (None, "", [], {}):
                merged[key] = value
        return merged
    return action


def _can_skip(state: Dict[str, Any]) -> bool:
    blinds = state.get("blinds") or {}
    for key in ("small", "big"):
        b = blinds.get(key) or {}
        if b.get("status") in ("CURRENT", "SELECT"):
            return True
    return False


def _parse_target(target: str) -> Tuple[str, int] | None:
    for prefix in ("consumable", "joker", "card", "pack", "voucher"):
        if target.startswith(prefix):
            try:
                return prefix, int(target[len(prefix) :])
            except Exception:
                return None
    return None


def _has_flag(card: Dict[str, Any], flag: str) -> bool:
    for area in (card, card.get("state") or {}, card.get("modifier") or {}):
        if isinstance(area, dict) and bool(area.get(flag)):
            return True
    return False


def _validated_use_params(
    consumable_idx: int,
    card: Dict[str, Any],
    raw_cards: Any,
    state: Dict[str, Any],
    *,
    allow_card_targets: bool,
) -> Dict[str, Any] | None:
    req = _target_requirement(card)
    if req.get("requires_joker") and len(((state.get("jokers") or {}).get("cards")) or []) == 0:
        return None
    if req.get("requires_cards"):
        if not allow_card_targets:
            return None
        cards = _clean_indexes(raw_cards, _hand_count(state), int(req.get("max", 5) or 5))
        if not _target_count_ok(cards, req):
            return None
        return {"consumable": consumable_idx, "cards": cards}
    return {"consumable": consumable_idx}


def _target_count_ok(cards: List[int], req: Dict[str, Any]) -> bool:
    count = len(cards)
    return int(req.get("min", 0) or 0) <= count <= int(req.get("max", 99) or 99)


def _target_requirement(card: Dict[str, Any]) -> Dict[str, Any]:
    key = str(card.get("key") or "").lower()
    if key == "c_aura":
        return {"requires_cards": True, "min": 1, "max": 1}
    if key == "c_ankh":
        return {"requires_joker": True}
    if key in TARGETED_CONSUMABLES:
        min_cards, max_cards = TARGETED_CONSUMABLES[key]
        return {"requires_cards": True, "min": min_cards, "max": max_cards}
    return {}


TARGETED_CONSUMABLES: Dict[str, Tuple[int, int]] = {
    "c_magician": (1, 2),
    "c_empress": (1, 2),
    "c_heirophant": (1, 2),
    "c_lovers": (1, 1),
    "c_chariot": (1, 1),
    "c_justice": (1, 1),
    "c_strength": (1, 2),
    "c_hanged_man": (1, 2),
    "c_death": (2, 2),
    "c_devil": (1, 1),
    "c_tower": (1, 1),
    "c_star": (1, 3),
    "c_moon": (1, 3),
    "c_sun": (1, 3),
    "c_world": (1, 3),
    "c_talisman": (1, 1),
    "c_deja_vu": (1, 1),
    "c_trance": (1, 1),
    "c_medium": (1, 1),
    "c_cryptid": (1, 1),
}


def _clean_indexes(raw: Any, hand_count: int, limit: int) -> List[int]:
    if not isinstance(raw, list):
        return []
    out: List[int] = []
    for x in raw:
        try:
            idx = int(x)
        except Exception:
            continue
        if 0 <= idx < hand_count and idx not in out:
            out.append(idx)
        if len(out) >= max(1, limit):
            break
    return out


def _hand_count(state: Dict[str, Any]) -> int:
    return len(((state.get("hand") or {}).get("cards")) or [])


def _select_limit(state: Dict[str, Any]) -> int:
    return int(((state.get("hand") or {}).get("highlighted_limit")) or 5)


def _fallback_play_cards(state: Dict[str, Any]) -> List[int]:
    cards = ((state.get("hand") or {}).get("cards")) or []
    if not cards:
        return [0]
    limit = _select_limit(state)
    ranks: Dict[str, List[int]] = {}
    suits: Dict[str, List[int]] = {}
    for i, c in enumerate(cards):
        value = c.get("value") or {}
        rank = str(value.get("rank") or "")
        suit = str(value.get("suit") or "")
        ranks.setdefault(rank, []).append(i)
        suits.setdefault(suit, []).append(i)

    groups = sorted(
        (idxs for idxs in ranks.values() if len(idxs) >= 2),
        key=lambda idxs: (len(idxs), max(_rank_score(cards[i]) for i in idxs)),
        reverse=True,
    )
    if groups:
        first = groups[0][:limit]
        if len(first) >= 3:
            return first
        if len(groups) >= 2 and limit >= 4:
            return (groups[0][:2] + groups[1][:2])[:limit]
        return first

    flushes = sorted((idxs for idxs in suits.values() if len(idxs) >= 5), key=len, reverse=True)
    if flushes:
        return sorted(flushes[0], key=lambda i: _rank_score(cards[i]), reverse=True)[: min(5, limit)]

    return sorted(range(len(cards)), key=lambda i: _rank_score(cards[i]), reverse=True)[:1]


def _rank_score(card: Dict[str, Any]) -> int:
    rank = str(((card.get("value") or {}).get("rank")) or "")
    return {
        "A": 14,
        "K": 13,
        "Q": 12,
        "J": 11,
        "T": 10,
    }.get(rank, int(rank) if rank.isdigit() else 0)

