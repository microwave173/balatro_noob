from collections import Counter
from itertools import combinations
from typing import Any, Dict, Iterable, List, Tuple

from .effect_catalog import EffectCatalog


SUIT_NAMES = {
    "H": "Hearts",
    "D": "Diamonds",
    "C": "Clubs",
    "S": "Spades",
}

RANK_NAMES = {
    "A": "Ace",
    "K": "King",
    "Q": "Queen",
    "J": "Jack",
    "T": "10",
}


def build_observation(
    state: Dict[str, Any],
    catalog: EffectCatalog,
    *,
    phase: str,
    run_plan: str = "",
    phase_plan: str = "",
    long_term_context: Dict[str, List[str]] | None = None,
    include_deck_detail: bool = False,
    recent_play_results: List[Dict[str, Any]] | None = None,
    action_history_summary: str = "",
    recent_actions: List[str] | None = None,
) -> Dict[str, Any]:
    enriched = _enrich_state_cards(state, catalog)
    compact = render_compact_observation(
        enriched,
        phase=phase,
        run_plan=run_plan,
        phase_plan=phase_plan,
        long_term_context=long_term_context or {},
        include_deck_detail=include_deck_detail,
        recent_play_results=recent_play_results or [],
        action_history_summary=action_history_summary,
        recent_actions=recent_actions or [],
    )
    return {
        "phase": phase,
        "compact": compact,
        "state": enriched,
        "joker_signature": joker_signature(enriched),
        "boss": _boss_summary(enriched),
    }


def render_compact_observation(
    state: Dict[str, Any],
    *,
    phase: str,
    run_plan: str,
    phase_plan: str,
    long_term_context: Dict[str, List[str]],
    include_deck_detail: bool = False,
    recent_play_results: List[Dict[str, Any]] | None = None,
    action_history_summary: str = "",
    recent_actions: List[str] | None = None,
) -> str:
    obs: Dict[str, Any] = {
        "phase": phase,
        "plan": {"run": _clean(run_plan) or "none", "phase": _clean(phase_plan) or "none"},
        "run": _run_obj(state),
        "round": _round_obj(state),
        "jokers": _area_items(state.get("jokers"), kind="joker"),
        "cons": _area_items(state.get("consumables"), kind="card"),
        "history": {
            "summary": _clean(action_history_summary) or "none",
            "recent": recent_actions or [],
        },
    }
    if phase == "SHOP":
        obs["next"] = _next_obj(state)
        obs["recent_play_results"] = _recent_play_result_items(recent_play_results or [])
    else:
        obs["blind"] = _blind_obj(state)
    if state.get("hand"):
        obs["hand"] = _hand_items(state.get("hand"))
        if phase == "PLAY":
            obs["play_options"] = _play_option_items(state)
    if state.get("cards"):
        obs["deck_left"] = _deck_left_obj(state.get("cards"))
        if include_deck_detail:
            obs["deck_detail"] = _deck_detail_items(state.get("cards"))
    if state.get("hands"):
        obs["poker"] = _poker_items(state.get("hands") or {})
        if phase == "PLAY":
            obs["poker_score_table"] = _poker_score_table_items(state.get("hands") or {})
    if state.get("shop"):
        obs["shop"] = _shop_items(state.get("shop"), "card")
    if state.get("packs"):
        obs["packs"] = _shop_items(state.get("packs"), "pack")
    if state.get("vouchers"):
        obs["vouchers"] = _shop_items(state.get("vouchers"), "voucher")
    if state.get("pack"):
        obs["pack_cards"] = _shop_items(state.get("pack"), "card")

    obs["rules"] = long_term_context.get("rules") or []
    obs["legal"] = _legal_obj(state, phase)
    return render_observation_text(obs)


def render_observation_text(obs: Dict[str, Any]) -> str:
    phase = obs.get("phase", "UNKNOWN")
    plan = obs.get("plan") or {}
    run = obs.get("run") or {}
    rnd = obs.get("round") or {}
    lines = [
        f"Current stage: {phase}",
        "",
        "You can see this game state:",
        (
            f"- Run: ante {run.get('ante')}, round {run.get('round')}, money ${run.get('money')}, "
            f"stake {run.get('stake')}, deck {run.get('deck')}, won={run.get('won')}."
        ),
    ]

    if obs.get("blind"):
        blind = obs.get("blind") or {}
        lines.append(
            f"- Current blind: {blind.get('current')} ({blind.get('type')}), "
            f"needs {blind.get('required')} chips, effect: {blind.get('effect')}."
        )
        lines.append(
            f"- Upcoming boss: {blind.get('next_boss')}, effect: {blind.get('next_boss_effect')}."
        )
    if obs.get("next"):
        nxt = obs.get("next") or {}
        lines.append(
            f"- Next boss: {nxt.get('boss')}, needs {nxt.get('required')} chips, effect: {nxt.get('effect')}."
        )

    lines.append(
        f"- Round resources: current chips {rnd.get('chips')}, hands left {rnd.get('hands_left')}, "
        f"discards left {rnd.get('discards_left')}, hands played {rnd.get('hands_played')}, "
        f"discards used {rnd.get('discards_used')}, selection limit {rnd.get('select_limit')}."
    )
    lines.append(f"- Jokers: {_list_text(obs.get('jokers'), 'none')}.")
    lines.append(f"- Consumables: {_list_text(obs.get('cons'), 'none')}.")
    if "hand" in obs:
        lines.append("- Hand cards:")
        lines.extend(f"  - {item}" for item in (obs.get("hand") or []))
    if obs.get("deck_left"):
        deck = obs.get("deck_left") or {}
        lines.append(
            f"- Remaining deck counts, not draw order: total {deck.get('total')}, "
            f"suits {deck.get('suits')}, ranks {deck.get('ranks')}."
        )
    if obs.get("deck_detail"):
        lines.append("- Inspected remaining deck detail, still not draw order:")
        lines.extend(f"  - {item}" for item in (obs.get("deck_detail") or []))
    if obs.get("poker"):
        lines.append("- Poker hand levels:")
        lines.extend(f"  - {item}" for item in (obs.get("poker") or []))
    if obs.get("poker_score_table"):
        lines.append("- BalatroBot poker hand score table for this run:")
        lines.append("  - These are BalatroBot API hand-level values only; include selected card chips, Jokers, xMult, enhancements, retriggers, and boss effects separately when estimating final score.")
        lines.extend(f"  - {item}" for item in (obs.get("poker_score_table") or []))
    if obs.get("play_options"):
        lines.append("- Current playable made hands from non-debuffed hand cards:")
        lines.extend(f"  - {item}" for item in (obs.get("play_options") or []))
    if obs.get("shop"):
        lines.append("- Shop cards:")
        lines.extend(f"  - {item}" for item in (obs.get("shop") or []))
    if obs.get("packs"):
        lines.append("- Packs:")
        lines.extend(f"  - {item}" for item in (obs.get("packs") or []))
    if obs.get("vouchers"):
        lines.append("- Vouchers:")
        lines.extend(f"  - {item}" for item in (obs.get("vouchers") or []))
    if obs.get("recent_play_results"):
        lines.append("- Recent scoring results before this shop:")
        lines.append("  - Use these actual scores to judge whether the current Joker lineup is strong enough or still needs Joker upgrades.")
        lines.extend(f"  - {item}" for item in (obs.get("recent_play_results") or []))
    history = obs.get("history") or {}
    if history.get("summary") and history.get("summary") != "none":
        lines.append(f"- Current-run compressed operation history: {history.get('summary')}")
    if history.get("recent"):
        lines.append("- Recent operations in this run:")
        lines.extend(f"  - {item}" for item in (history.get("recent") or []))
    if obs.get("pack_cards"):
        lines.append("- Open pack choices:")
        lines.extend(f"  - {item}" for item in (obs.get("pack_cards") or []))
    lines.append(f"- Rulebook guidance from reflection: {_list_text(obs.get('rules'), 'none')}.")
    lines.append(f"- Legal actions: {obs.get('legal')}.")

    if plan.get("run") and plan.get("run") != "none":
        lines.extend(["", f"Previous run-level plan: {plan.get('run')}"])
    if plan.get("phase") and plan.get("phase") != "none":
        lines.append(f"Previous phase plan: {plan.get('phase')}")
    return "\n".join(lines)


def joker_signature(state: Dict[str, Any]) -> List[str]:
    cards = (((state.get("jokers") or {}).get("cards")) or [])
    labels = [str(c.get("label") or c.get("key") or "?") for c in cards]
    return labels


def current_blind_key(state: Dict[str, Any]) -> str:
    blinds = state.get("blinds") or {}
    for key in ("small", "big", "boss"):
        b = blinds.get(key) or {}
        if b.get("status") in ("CURRENT", "SELECT", "SELECTED"):
            return key
    return "unknown"


def _enrich_state_cards(state: Dict[str, Any], catalog: EffectCatalog) -> Dict[str, Any]:
    out = dict(state)
    for area_name in ("jokers", "consumables", "hand", "cards", "shop", "vouchers", "packs", "pack"):
        area = out.get(area_name)
        if isinstance(area, dict):
            out[area_name] = _enrich_area(area, catalog)
    return out


def _enrich_area(area: Dict[str, Any], catalog: EffectCatalog) -> Dict[str, Any]:
    out = dict(area)
    cards = []
    for card in area.get("cards") or []:
        if isinstance(card, dict):
            cards.append(catalog.enrich_card(card))
    out["cards"] = cards
    out["count"] = len(cards)
    return out


def _run_line(state: Dict[str, Any]) -> str:
    return (
        "RUN: "
        f"ante={state.get('ante_num', 0)}, round={state.get('round_num', 0)}, "
        f"money={state.get('money', 0)}, stake={state.get('stake', '')}, "
        f"deck={state.get('deck', '')}, won={bool(state.get('won'))}"
    )


def _run_obj(state: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "ante": state.get("ante_num", 0),
        "round": state.get("round_num", 0),
        "money": state.get("money", 0),
        "stake": state.get("stake", ""),
        "deck": state.get("deck", ""),
        "won": bool(state.get("won")),
    }


def _blind_line(state: Dict[str, Any], phase: str) -> str:
    blinds = state.get("blinds") or {}
    cur_key = current_blind_key(state)
    cur = blinds.get(cur_key) or {}
    boss = blinds.get("boss") or {}
    if phase == "SHOP":
        return (
            "NEXT: "
            f"boss={_clean(boss.get('name'))}, required={boss.get('score', 0)}, "
            f"effect={_clean(boss.get('effect')) or 'none'}"
        )
    return (
        "BLIND: "
        f"current={_clean(cur.get('name')) or cur_key}, type={_clean(cur.get('type'))}, "
        f"required={cur.get('score', 0)}, effect={_clean(cur.get('effect')) or 'none'}, "
        f"next_boss={_clean(boss.get('name'))}, next_boss_effect={_clean(boss.get('effect')) or 'none'}"
    )


def _blind_obj(state: Dict[str, Any]) -> Dict[str, Any]:
    blinds = state.get("blinds") or {}
    cur_key = current_blind_key(state)
    cur = blinds.get(cur_key) or {}
    boss = blinds.get("boss") or {}
    return {
        "current": _clean(cur.get("name")) or cur_key,
        "type": _clean(cur.get("type")),
        "required": cur.get("score", 0),
        "effect": _clean(cur.get("effect")) or "none",
        "next_boss": _clean(boss.get("name")),
        "next_boss_effect": _clean(boss.get("effect")) or "none",
    }


def _next_obj(state: Dict[str, Any]) -> Dict[str, Any]:
    boss = ((state.get("blinds") or {}).get("boss")) or {}
    return {
        "boss": _clean(boss.get("name")),
        "required": boss.get("score", 0),
        "effect": _clean(boss.get("effect")) or "none",
    }


def _round_line(state: Dict[str, Any]) -> str:
    rnd = state.get("round") or {}
    return (
        "ROUND: "
        f"chips={rnd.get('chips', 0)}, hands_left={rnd.get('hands_left', 0)}, "
        f"discards_left={rnd.get('discards_left', 0)}, hands_played={rnd.get('hands_played', 0)}, "
        f"discards_used={rnd.get('discards_used', 0)}, reroll_cost={rnd.get('reroll_cost', 0)}, "
        f"select_limit={((state.get('hand') or {}).get('highlighted_limit') or 5)}"
    )


def _round_obj(state: Dict[str, Any]) -> Dict[str, Any]:
    rnd = state.get("round") or {}
    return {
        "chips": rnd.get("chips", 0),
        "hands_left": rnd.get("hands_left", 0),
        "discards_left": rnd.get("discards_left", 0),
        "hands_played": rnd.get("hands_played", 0),
        "discards_used": rnd.get("discards_used", 0),
        "reroll_cost": rnd.get("reroll_cost", 0),
        "select_limit": ((state.get("hand") or {}).get("highlighted_limit") or 5),
    }


def _area_items(area: Dict[str, Any] | None, *, kind: str) -> List[str]:
    cards = (area or {}).get("cards") or []
    return [_card_item(i, card, kind=kind) for i, card in enumerate(cards)]


def _hand_items(area: Dict[str, Any] | None) -> List[str]:
    cards = (area or {}).get("cards") or []
    return [_hand_item(i, card) for i, card in enumerate(cards)]


def _shop_items(area: Dict[str, Any] | None, slot_prefix: str) -> List[str]:
    cards = (area or {}).get("cards") or []
    return [_shop_item(i, card, slot_prefix) for i, card in enumerate(cards)]


def _area_line(label: str, area: Dict[str, Any] | None, *, kind: str) -> str:
    cards = (area or {}).get("cards") or []
    if not cards:
        return f"{label}: none"
    return f"{label}: " + " ; ".join(_card_item(i, card, kind=kind) for i, card in enumerate(cards))


def _hand_line(area: Dict[str, Any] | None) -> str:
    cards = (area or {}).get("cards") or []
    if not cards:
        return "HAND: none"
    return "HAND: " + " ; ".join(_hand_item(i, card) for i, card in enumerate(cards))


def _shop_area_line(label: str, area: Dict[str, Any] | None, slot_prefix: str) -> str:
    cards = (area or {}).get("cards") or []
    if not cards:
        return f"{label}: none"
    return f"{label}: " + " ; ".join(_shop_item(i, card, slot_prefix) for i, card in enumerate(cards))


def _card_item(index: int, card: Dict[str, Any], *, kind: str) -> str:
    value = card.get("value") or {}
    status = _card_status(card)
    cost = card.get("cost") or {}
    sell = cost.get("sell", 0)
    return ",".join(
        [
            str(index),
            _clean(card.get("label")) or "?",
            _clean(card.get("key")) or "?",
            _clean(value.get("effect")) or "no effect text",
            f"sell={sell}",
            status,
        ]
    )


def _hand_item(index: int, card: Dict[str, Any]) -> str:
    value = card.get("value") or {}
    rank = _rank_name(value.get("rank"))
    suit = SUIT_NAMES.get(str(value.get("suit")), str(value.get("suit") or "?"))
    modifier = _modifier_text(card.get("modifier") or {})
    state = _state_text(card.get("state") or {})
    effect = _clean(value.get("effect")) or ""
    return ",".join([str(index), rank, suit, modifier, state or effect or "base"])


def _shop_item(index: int, card: Dict[str, Any], slot_prefix: str) -> str:
    value = card.get("value") or {}
    cost = (card.get("cost") or {}).get("buy", 0)
    return ",".join(
        [
            f"{slot_prefix}{index}",
            _clean(card.get("label")) or "?",
            _clean(card.get("key")) or "?",
            _clean(value.get("effect")) or "no effect text",
            f"cost={cost}",
            _card_status(card),
        ]
    )


def _deck_left_line(area: Dict[str, Any]) -> str:
    cards = area.get("cards") or []
    suits: Counter[str] = Counter()
    ranks: Counter[str] = Counter()
    for c in cards:
        value = c.get("value") or {}
        suit = SUIT_NAMES.get(str(value.get("suit")), str(value.get("suit") or "?"))
        rank = _rank_name(value.get("rank"))
        suits[suit] += 1
        ranks[rank] += 1
    suit_text = "/".join(f"{k}{v}" for k, v in sorted(suits.items()))
    rank_order = ["Ace", "King", "Queen", "Jack", "10", "9", "8", "7", "6", "5", "4", "3", "2"]
    rank_text = "/".join(f"{r}x{ranks[r]}" for r in rank_order if ranks[r])
    return f"DECK_LEFT: total={len(cards)}, suits={suit_text}, ranks={rank_text}"


def _deck_left_obj(area: Dict[str, Any]) -> Dict[str, Any]:
    cards = area.get("cards") or []
    suits: Counter[str] = Counter()
    ranks: Counter[str] = Counter()
    for c in cards:
        value = c.get("value") or {}
        suit = SUIT_NAMES.get(str(value.get("suit")), str(value.get("suit") or "?"))
        rank = _rank_name(value.get("rank"))
        suits[suit] += 1
        ranks[rank] += 1
    rank_order = ["Ace", "King", "Queen", "Jack", "10", "9", "8", "7", "6", "5", "4", "3", "2"]
    return {
        "total": len(cards),
        "suits": {k: suits[k] for k in sorted(suits)},
        "ranks": {r: ranks[r] for r in rank_order if ranks[r]},
    }


def _deck_detail_line(area: Dict[str, Any]) -> str:
    cards = area.get("cards") or []
    if not cards:
        return "DECK_DETAIL: none"
    parts = []
    for i, c in enumerate(cards):
        value = c.get("value") or {}
        rank = _rank_name(value.get("rank"))
        suit = SUIT_NAMES.get(str(value.get("suit")), str(value.get("suit") or "?"))
        modifier = _modifier_text(c.get("modifier") or {})
        state = _state_text(c.get("state") or {})
        effect = _clean(value.get("effect")) or ""
        parts.append(",".join([str(i), rank, suit, modifier, state or effect or "base"]))
    return "DECK_DETAIL: " + " ; ".join(parts)


def _deck_detail_items(area: Dict[str, Any]) -> List[str]:
    cards = area.get("cards") or []
    parts = []
    for i, c in enumerate(cards):
        value = c.get("value") or {}
        rank = _rank_name(value.get("rank"))
        suit = SUIT_NAMES.get(str(value.get("suit")), str(value.get("suit") or "?"))
        modifier = _modifier_text(c.get("modifier") or {})
        state = _state_text(c.get("state") or {})
        effect = _clean(value.get("effect")) or ""
        parts.append(",".join([str(i), rank, suit, modifier, state or effect or "base"]))
    return parts


def _poker_line(hands: Dict[str, Any]) -> str:
    important = sorted(
        hands.items(),
        key=lambda kv: (
            int((kv[1] or {}).get("played", 0) or 0),
            int((kv[1] or {}).get("level", 1) or 1),
            int((kv[1] or {}).get("chips", 0) or 0) * int((kv[1] or {}).get("mult", 0) or 0),
        ),
        reverse=True,
    )[:8]
    parts = []
    for name, h in important:
        parts.append(
            f"{name}=L{h.get('level', 1)} chips{h.get('chips', 0)} mult{h.get('mult', 0)} "
            f"played{h.get('played', 0)} round{h.get('played_this_round', 0)}"
        )
    return "POKER: " + (" ; ".join(parts) if parts else "none")


def _poker_items(hands: Dict[str, Any]) -> List[str]:
    important = sorted(
        hands.items(),
        key=lambda kv: (
            int((kv[1] or {}).get("played", 0) or 0),
            int((kv[1] or {}).get("level", 1) or 1),
            int((kv[1] or {}).get("chips", 0) or 0) * int((kv[1] or {}).get("mult", 0) or 0),
        ),
        reverse=True,
    )[:8]
    return [
        f"{name},L{h.get('level', 1)},chips{h.get('chips', 0)},mult{h.get('mult', 0)},"
        f"played{h.get('played', 0)},round{h.get('played_this_round', 0)}"
        for name, h in important
    ]


def _poker_score_table_items(hands: Dict[str, Any]) -> List[str]:
    ordered = sorted(
        hands.items(),
        key=lambda kv: (
            int((kv[1] or {}).get("order", 99) or 99),
            str(kv[0]),
        ),
    )
    items: List[str] = []
    for name, h in ordered:
        chips = int((h or {}).get("chips", 0) or 0)
        mult = int((h or {}).get("mult", 0) or 0)
        items.append(
            f"{name}: level={h.get('level', 1)}, chips={chips}, mult={mult}, "
            f"played={h.get('played', 0)}, played_this_round={h.get('played_this_round', 0)}"
        )
    return items


def _recent_play_result_items(results: List[Dict[str, Any]], limit: int = 3) -> List[str]:
    items: List[str] = []
    for result in results[-limit:]:
        jokers = result.get("jokers") or ["NO_JOKERS"]
        hand = result.get("hand") or result.get("action") or "unknown"
        chips_delta = result.get("chips_delta")
        total_chips = result.get("total_chips")
        target = result.get("blind_required")
        ante = result.get("ante")
        round_num = result.get("round")
        items.append(
            f"ante{ante}/round{round_num}, jokers={jokers}, action={hand}, "
            f"scored={chips_delta}, round_total={total_chips}, blind_required={target}"
        )
    return items


def _legal_line(state: Dict[str, Any], phase: str) -> str:
    hand = state.get("hand") or {}
    hand_count = len(hand.get("cards") or [])
    select_limit = hand.get("highlighted_limit") or 5
    rnd = state.get("round") or {}
    if phase == "PLAY":
        return (
            "LEGAL: play(cards)=1-"
            f"{min(select_limit, hand_count)} hand indexes; discard(cards)=1-{min(select_limit, hand_count)} "
            f"only if discards_left>{0}; use(consumableN,cards) for held Tarot/Spectral targets; "
            "inspect_deck asks once for DECK_DETAIL; output zero-based indexes"
        )
    if phase == "SHOP":
        return "LEGAL: buy(cardN|packN|voucherN), use(consumableN), sell(jokerN|consumableN), reroll, next_round"
    if phase == "BLIND_SELECT":
        return "LEGAL: select or skip if skip option exists"
    if phase == "PACK":
        return "LEGAL: pack cardN or skip; add targets=[hand indexes] when a Tarot/Spectral pack card requires selected hand cards"
    return "LEGAL: use only actions allowed by phase"


def _legal_obj(state: Dict[str, Any], phase: str) -> Dict[str, Any]:
    hand = state.get("hand") or {}
    hand_count = len(hand.get("cards") or [])
    select_limit = hand.get("highlighted_limit") or 5
    max_cards = min(select_limit, hand_count)
    rnd = state.get("round") or {}
    if phase == "PLAY":
        return {
            "play": f"1-{max_cards} hand indexes",
            "discard": f"1-{max_cards} if discards_left>{0}",
            "can_discard": int(rnd.get("discards_left", 0) or 0) > 0,
            "use": "use(consumableN) or use(consumableN,cards=[hand indexes])",
            "inspect_deck": "ask once for deck_detail",
            "indexing": "zero-based hand indexes",
        }
    if phase == "SHOP":
        return {"actions": "buy(cardN|packN|voucherN), use(consumableN), sell(jokerN|consumableN), reroll, next_round"}
    if phase == "BLIND_SELECT":
        return {"actions": "select or skip if skip option exists"}
    if phase == "PACK":
        return {"actions": "pack cardN or skip; targets=[hand indexes] for targeted Tarot/Spectral choices"}
    return {"actions": "use only actions allowed by phase"}


def _list_text(items: Any, empty: str) -> str:
    if not items:
        return empty
    if isinstance(items, list):
        return "; ".join(str(x) for x in items) if items else empty
    return str(items)


def _boss_summary(state: Dict[str, Any]) -> Dict[str, Any]:
    boss = ((state.get("blinds") or {}).get("boss")) or {}
    return {
        "name": boss.get("name", ""),
        "effect": boss.get("effect", ""),
        "score": boss.get("score", 0),
        "status": boss.get("status", ""),
    }


def _rank_name(rank: Any) -> str:
    r = str(rank or "?")
    return RANK_NAMES.get(r, r)


def _modifier_text(mod: Dict[str, Any]) -> str:
    if not mod:
        return "base"
    parts = []
    for key in ("enhancement", "edition", "seal", "eternal", "perishable", "rental"):
        if key in mod:
            parts.append(f"{key}={mod[key]}")
    return "|".join(parts) if parts else "base"


def _state_text(state: Dict[str, Any]) -> str:
    parts = [k for k, v in state.items() if v]
    return "|".join(parts)


def _card_status(card: Dict[str, Any]) -> str:
    parts = []
    if card.get("state"):
        parts.append(_state_text(card.get("state") or {}))
    if card.get("modifier"):
        parts.append(_modifier_text(card.get("modifier") or {}))
    return "|".join([p for p in parts if p and p != "base"]) or "normal"


def _clean(value: Any) -> str:
    return " ".join(str(value or "").replace("\n", " ").split())


RANK_VALUE = {
    "A": 14,
    "K": 13,
    "Q": 12,
    "J": 11,
    "T": 10,
}


def _play_option_items(state: Dict[str, Any]) -> List[str]:
    cards = [
        (i, c)
        for i, c in enumerate(((state.get("hand") or {}).get("cards")) or [])
        if not _is_debuffed(c)
    ]
    if not cards:
        return []

    by_rank: Dict[str, List[Tuple[int, Dict[str, Any]]]] = {}
    by_suit: Dict[str, List[Tuple[int, Dict[str, Any]]]] = {}
    for item in cards:
        value = item[1].get("value") or {}
        by_rank.setdefault(str(value.get("rank") or ""), []).append(item)
        for suit in _card_suits(item[1]):
            by_suit.setdefault(suit, []).append(item)

    options: List[Dict[str, Any]] = []

    def add(name: str, idxs: List[int], note: str = "") -> None:
        if not idxs:
            return
        score = _hand_type_score(name) * 1000 + sum(_card_rank_score_by_index(cards, i) for i in idxs)
        options.append({"name": name, "cards": idxs, "note": note, "score": score})

    rank_groups = sorted(by_rank.values(), key=lambda g: (len(g), max(_rank_score_card(c) for _, c in g)), reverse=True)
    for g in rank_groups:
        idxs = [i for i, _ in sorted(g, key=lambda item: _rank_score_card(item[1]), reverse=True)]
        for suit in SUIT_NAMES:
            suited = [item for item in g if suit in _card_suits(item[1])]
            if len(suited) >= 5:
                suited_idxs = [i for i, _ in sorted(suited, key=lambda item: _rank_score_card(item[1]), reverse=True)]
                add("Flush Five", suited_idxs[:5], f"{_rank_label(g[0][1])} {SUIT_NAMES.get(suit, suit)}")
        if len(idxs) >= 5:
            add("Five of a Kind", idxs[:5], _rank_label(g[0][1]))
        if len(idxs) >= 4:
            add("Four of a Kind", idxs[:4], _rank_label(g[0][1]))
        if len(idxs) >= 3:
            add("Three of a Kind", idxs[:3], _rank_label(g[0][1]))
        if len(idxs) >= 2:
            add("Pair", idxs[:2], _rank_label(g[0][1]))

    pairs = [g for g in rank_groups if len(g) >= 2]
    for best_two in combinations(pairs, 2):
        add("Two Pair", [i for g in best_two for i, _ in g[:2]], "/".join(_rank_label(g[0][1]) for g in best_two))
    trips = [g for g in rank_groups if len(g) >= 3]
    pair_for_full = [g for g in rank_groups if len(g) >= 2]
    for trip in trips:
        for pair in pair_for_full:
            if pair is trip:
                continue
            add("Full House", [i for i, _ in trip[:3]] + [i for i, _ in pair[:2]], f"{_rank_label(trip[0][1])} over {_rank_label(pair[0][1])}")

    for suit in SUIT_NAMES:
        suited_by_rank = {
            rank: [item for item in group if suit in _card_suits(item[1])]
            for rank, group in by_rank.items()
        }
        suited_trips = [
            g
            for g in sorted(suited_by_rank.values(), key=lambda g: (len(g), max((_rank_score_card(c) for _, c in g), default=0)), reverse=True)
            if len(g) >= 3
        ]
        suited_pairs = [
            g
            for g in sorted(suited_by_rank.values(), key=lambda g: (len(g), max((_rank_score_card(c) for _, c in g), default=0)), reverse=True)
            if len(g) >= 2
        ]
        for trip in suited_trips:
            for pair in suited_pairs:
                if not trip or not pair or _rank_label(trip[0][1]) == _rank_label(pair[0][1]):
                    continue
                add(
                    "Flush House",
                    [i for i, _ in trip[:3]] + [i for i, _ in pair[:2]],
                    f"{_rank_label(trip[0][1])} over {_rank_label(pair[0][1])} {SUIT_NAMES.get(suit, suit)}",
                )

    for suit, g in by_suit.items():
        if len(g) >= 5:
            ordered = sorted(g, key=lambda item: _rank_score_card(item[1]), reverse=True)
            add("Flush", [i for i, _ in ordered[:5]], SUIT_NAMES.get(suit, suit))
            straight_flush = _best_straight(ordered)
            if straight_flush:
                add("Straight Flush", straight_flush, SUIT_NAMES.get(suit, suit))

    straight = _best_straight(cards)
    if straight:
        add("Straight", straight)

    high = sorted(cards, key=lambda item: _rank_score_card(item[1]), reverse=True)
    add("High Card", [high[0][0]], _rank_label(high[0][1]))

    dedup: Dict[Tuple[str, Tuple[int, ...]], Dict[str, Any]] = {}
    for opt in options:
        key = (opt["name"], tuple(sorted(opt["cards"])))
        old = dedup.get(key)
        if not old or opt["score"] > old["score"]:
            dedup[key] = opt
    ranked = sorted(dedup.values(), key=lambda opt: opt["score"], reverse=True)
    return [
        f"{opt['name']}: cards={opt['cards']}"
        + (f", note={opt['note']}" if opt.get("note") else "")
        for opt in ranked[:12]
    ]


def _best_straight(items: List[Tuple[int, Dict[str, Any]]]) -> List[int]:
    best_by_value: Dict[int, Tuple[int, Dict[str, Any]]] = {}
    for item in items:
        score = _rank_score_card(item[1])
        best_by_value.setdefault(score, item)
        if score == 14:
            best_by_value.setdefault(1, item)
    for seq in ([14, 13, 12, 11, 10], [13, 12, 11, 10, 9], [12, 11, 10, 9, 8], [11, 10, 9, 8, 7],
                [10, 9, 8, 7, 6], [9, 8, 7, 6, 5], [8, 7, 6, 5, 4], [7, 6, 5, 4, 3],
                [6, 5, 4, 3, 2], [5, 4, 3, 2, 1]):
        if all(v in best_by_value for v in seq):
            return [best_by_value[v][0] for v in seq]
    return []


def _is_debuffed(card: Dict[str, Any]) -> bool:
    state = card.get("state") or {}
    if isinstance(state, dict):
        return any(bool(state.get(k)) for k in ("debuffed", "debuff", "disabled", "ban", "banned"))
    return False


def _card_suits(card: Dict[str, Any]) -> List[str]:
    value = card.get("value") or {}
    suit = str(value.get("suit") or "")
    if _is_wild(card):
        return list(SUIT_NAMES.keys())
    return [suit] if suit else []


def _is_wild(card: Dict[str, Any]) -> bool:
    for area in (card, card.get("modifier") or {}, card.get("value") or {}):
        if not isinstance(area, dict):
            continue
        text = " ".join(str(v).lower() for v in area.values())
        if "wild" in text or "wild card" in text:
            return True
    key_text = f"{card.get('key') or ''} {card.get('label') or ''}".lower()
    return "wild" in key_text


def _rank_score_card(card: Dict[str, Any]) -> int:
    rank = str(((card.get("value") or {}).get("rank")) or "")
    return RANK_VALUE.get(rank, int(rank) if rank.isdigit() else 0)


def _card_rank_score_by_index(cards: List[Tuple[int, Dict[str, Any]]], idx: int) -> int:
    for i, card in cards:
        if i == idx:
            return _rank_score_card(card)
    return 0


def _rank_label(card: Dict[str, Any]) -> str:
    return _rank_name((card.get("value") or {}).get("rank"))


def _hand_type_score(name: str) -> int:
    return {
        "Flush Five": 11,
        "Flush House": 10,
        "Straight Flush": 9,
        "Five of a Kind": 8,
        "Four of a Kind": 7,
        "Full House": 6,
        "Flush": 5,
        "Straight": 4,
        "Three of a Kind": 3,
        "Two Pair": 2,
        "Pair": 1,
        "High Card": 0,
    }.get(name, 0)

