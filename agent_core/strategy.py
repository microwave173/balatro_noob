import itertools
from collections import Counter
from typing import Any, Dict, List, Optional, Tuple


RANK_VALUE = {
    "2": 2,
    "3": 3,
    "4": 4,
    "5": 5,
    "6": 6,
    "7": 7,
    "8": 8,
    "9": 9,
    "T": 10,
    "J": 11,
    "Q": 12,
    "K": 13,
    "A": 14,
}


def classify_hand(cards: List[Dict[str, Any]]) -> str:
    vals: List[int] = []
    suits: List[str] = []
    for c in cards:
        v = c.get("value") or {}
        rank = v.get("rank")
        suit = v.get("suit")
        if rank not in RANK_VALUE:
            return "High Card"
        vals.append(RANK_VALUE[rank])
        suits.append(suit)

    n = len(cards)
    cnt = Counter(vals)
    counts = sorted(cnt.values(), reverse=True)
    unique_vals = sorted(set(vals))

    is_flush = n == 5 and len(set(suits)) == 1
    is_straight = n == 5 and len(unique_vals) == 5 and (
        unique_vals[-1] - unique_vals[0] == 4 or set(unique_vals) == {14, 2, 3, 4, 5}
    )

    if n == 5:
        if is_straight and is_flush:
            return "Straight Flush"
        if counts == [4, 1]:
            return "Four of a Kind"
        if counts == [3, 2]:
            return "Full House"
        if is_flush:
            return "Flush"
        if is_straight:
            return "Straight"
        if counts == [3, 1, 1]:
            return "Three of a Kind"
        if counts == [2, 2, 1]:
            return "Two Pair"
        if counts == [2, 1, 1, 1]:
            return "Pair"
        return "High Card"
    if n == 4:
        if counts == [4]:
            return "Four of a Kind"
        if counts == [3, 1]:
            return "Three of a Kind"
        if counts == [2, 2]:
            return "Two Pair"
        if counts == [2, 1, 1]:
            return "Pair"
    if n == 3:
        if counts == [3]:
            return "Three of a Kind"
        if counts == [2, 1]:
            return "Pair"
    if n == 2 and counts == [2]:
        return "Pair"
    return "High Card"


def summarize_state(state: Dict[str, Any]) -> Dict[str, Any]:
    round_info = state.get("round") or {}
    jokers = ((state.get("jokers") or {}).get("cards") or [])
    joker_labels: List[str] = []
    for c in jokers[:8]:
        label = c.get("label") or c.get("key") or "?"
        joker_labels.append(str(label))
    return {
        "state": state.get("state"),
        "ante": state.get("ante_num"),
        "round": state.get("round_num"),
        "won": bool(state.get("won")),
        "money": state.get("money"),
        "hands_left": round_info.get("hands_left"),
        "discards_left": round_info.get("discards_left"),
        "chips": round_info.get("chips"),
        "hand_cards": len(((state.get("hand") or {}).get("cards") or [])),
        "shop_cards": len(((state.get("shop") or {}).get("cards") or [])),
        "joker_count": len(jokers),
        "jokers": joker_labels,
    }


def discard_low_cards(state: Dict[str, Any], n: int = 2) -> List[int]:
    hand = ((state.get("hand") or {}).get("cards") or [])
    scored: List[Tuple[int, int]] = []
    for idx, c in enumerate(hand):
        rank = ((c.get("value") or {}).get("rank"))
        scored.append((RANK_VALUE.get(rank, 0), idx))
    scored.sort()
    return [idx for _, idx in scored[: min(n, len(scored))]]


def top_play_options(state: Dict[str, Any], limit: int = 3) -> List[Dict[str, Any]]:
    hand = ((state.get("hand") or {}).get("cards") or [])
    hands = state.get("hands") or {}
    scored: List[Tuple[Tuple[int, int], List[int], str]] = []
    for k in range(1, min(5, len(hand)) + 1):
        for comb in itertools.combinations(range(len(hand)), k):
            cards = list(comb)
            chosen = [hand[i] for i in cards]
            hand_name = classify_hand(chosen)
            h = hands.get(hand_name) or {}
            score = int(h.get("chips", 0) or 0) * int(h.get("mult", 0) or 0)
            scored.append(((score, -k), cards, hand_name))
    scored.sort(key=lambda x: x[0], reverse=True)

    out: List[Dict[str, Any]] = []
    seen = set()
    for key, cards, hand_name in scored:
        t = tuple(cards)
        if t in seen:
            continue
        seen.add(t)
        out.append(
            {
                "action": "play",
                "params": {"cards": cards},
                "why": f"play {hand_name} score={key[0]} cards={cards}",
            }
        )
        if len(out) >= limit:
            break
    return out


def choose_blind_candidates(state: Dict[str, Any]) -> List[Dict[str, Any]]:
    candidates = [{"action": "select", "params": None, "why": "play current blind"}]
    blinds = state.get("blinds") or {}
    current_key = None
    for key in ("small", "big", "boss"):
        b = blinds.get(key) or {}
        if b.get("status") in ("SELECT", "CURRENT", "SELECTED"):
            current_key = key
            break
    if current_key in ("small", "big"):
        candidates.append({"action": "skip", "params": None, "why": f"skip {current_key} blind"})
    return candidates


def choose_hand_candidates(state: Dict[str, Any]) -> List[Dict[str, Any]]:
    candidates: List[Dict[str, Any]] = []
    candidates.extend(top_play_options(state, limit=3))
    round_info = state.get("round") or {}
    if int(round_info.get("discards_left", 0) or 0) > 0 and int(round_info.get("hands_left", 0) or 0) > 1:
        candidates.append({"action": "discard", "params": {"cards": discard_low_cards(state)}, "why": "discard low cards"})
    if not candidates:
        candidates.append({"action": "play", "params": {"cards": [0]}, "why": "safety fallback"})
    return candidates


def choose_pack_candidates(state: Dict[str, Any]) -> List[Dict[str, Any]]:
    pack_cards = ((state.get("pack") or {}).get("cards") or [])
    candidates: List[Dict[str, Any]] = []
    for i in range(min(2, len(pack_cards))):
        candidates.append({"action": "pack", "params": {"card": i}, "why": f"choose pack card {i}"})
    candidates.append({"action": "pack", "params": {"skip": True}, "why": "skip pack"})
    return candidates


def choose_shop_candidates(state: Dict[str, Any]) -> List[Dict[str, Any]]:
    money = int(state.get("money", 0) or 0)
    vouchers = ((state.get("vouchers") or {}).get("cards") or [])
    shop_cards = ((state.get("shop") or {}).get("cards") or [])
    packs = ((state.get("packs") or {}).get("cards") or [])

    candidates: List[Dict[str, Any]] = []

    for i, c in enumerate(vouchers):
        cost = int(((c.get("cost") or {}).get("buy") or 9999))
        if cost <= money:
            candidates.append(
                {
                    "action": "buy",
                    "params": {"voucher": i},
                    "why": f"voucher {c.get('label', '?')}",
                    "priority": 0,
                }
            )

    for i, c in enumerate(shop_cards):
        cost = int(((c.get("cost") or {}).get("buy") or 9999))
        if cost > money:
            continue
        set_name = c.get("set")
        if set_name == "JOKER":
            pr = 1
        elif set_name in ("PLANET", "TAROT", "SPECTRAL"):
            pr = 2
        else:
            pr = 3
        candidates.append(
            {
                "action": "buy",
                "params": {"card": i},
                "why": f"{set_name}:{c.get('label', '?')}",
                "priority": pr,
            }
        )

    for i, c in enumerate(packs):
        cost = int(((c.get("cost") or {}).get("buy") or 9999))
        if cost <= money:
            candidates.append(
                {
                    "action": "buy",
                    "params": {"pack": i},
                    "why": f"pack {c.get('label', '?')}",
                    "priority": 4,
                }
            )

    candidates.append({"action": "next_round", "params": None, "why": "advance", "priority": 9})
    candidates.sort(key=lambda x: x["priority"])
    return candidates
