import argparse
import itertools
import json
import os
import random
import time
import urllib.error
import urllib.request
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


class JsonRpcClient:
    def __init__(self, host: str, port: int, timeout: float) -> None:
        self.url = f"http://{host}:{port}"
        self.timeout = timeout

    def call(self, method: str, params: Optional[Dict[str, Any]] = None, retries: int = 1) -> Dict[str, Any]:
        payload: Dict[str, Any] = {"jsonrpc": "2.0", "method": method, "id": 1}
        if params is not None:
            payload["params"] = params
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            self.url,
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        last_err: Optional[Exception] = None
        for _ in range(retries + 1):
            try:
                with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                    out = json.loads(resp.read().decode("utf-8"))
                if "error" in out:
                    err = out["error"]
                    name = err.get("data", {}).get("name", "RPC_ERROR")
                    raise RuntimeError(f"{name}: {err.get('message', 'unknown error')}")
                return out["result"]
            except Exception as e:
                last_err = e
                time.sleep(0.08)
        raise last_err if last_err else RuntimeError("unknown rpc error")


class OllamaPolicy:
    def __init__(self, enabled: bool, model: str, url: str, timeout: float, log_io: bool) -> None:
        self.enabled = enabled
        self.model = model
        self.url = url
        self.timeout = timeout
        self.log_io = log_io
        self.system_prompt = (
            "You are a Balatro agent policy helper.\n"
            "Goal: survive and maximize win probability.\n"
            "Basic strategy:\n"
            "1) Prefer stable hands over greedy high variance lines.\n"
            "2) In shop, prioritize value Jokers, then Planet/Tarot/Spectral, avoid random reroll spam.\n"
            "3) Keep economy healthy; avoid buying weak cards if money is low.\n"
            "4) If a blind is already beatable, do not overcomplicate.\n"
            "5) Output STRICT JSON only.\n"
        )

    def choose(
        self,
        stage: str,
        summary: Dict[str, Any],
        candidates: List[Dict[str, Any]],
    ) -> Optional[Tuple[Dict[str, Any], str]]:
        if not self.enabled:
            return None
        user_obj = {
            "task": "choose one action candidate index to execute",
            "stage": stage,
            "state_summary": summary,
            "candidates": candidates,
            "output_schema": {"candidate_index": "int", "reason": "string"},
        }
        payload = {
            "model": self.model,
            "stream": False,
            "format": "json",
            "messages": [
                {"role": "system", "content": self.system_prompt},
                {
                    "role": "user",
                    "content": json.dumps(user_obj, ensure_ascii=False),
                },
            ],
            "options": {
                "num_ctx": 2048,
                "num_thread": 8,
                "num_gpu": 999,
            },
        }
        if self.log_io:
            print("[llm-input]", json.dumps({"stage": stage, "request": user_obj}, ensure_ascii=False))
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            self.url,
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                out = json.loads(resp.read().decode("utf-8"))
            text = (out.get("message") or {}).get("content", "").strip()
            if self.log_io:
                print("[llm-output]", json.dumps({"stage": stage, "raw": text}, ensure_ascii=False))
            if not text:
                return None
            parsed = json.loads(text)
            idx = int(parsed.get("candidate_index", -1))
            if idx < 0 or idx >= len(candidates):
                return None
            reason = str(parsed.get("reason", "")).strip()
            return candidates[idx], reason
        except Exception as e:
            if self.log_io:
                print("[llm-output]", json.dumps({"stage": stage, "error": str(e)}, ensure_ascii=False))
            return None


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


def best_play_cards(state: Dict[str, Any]) -> List[int]:
    hand = ((state.get("hand") or {}).get("cards") or [])
    hands = state.get("hands") or {}
    if not hand:
        return [0]

    best: Optional[Tuple[Tuple[int, int], List[int]]] = None
    for k in range(1, min(5, len(hand)) + 1):
        for comb in itertools.combinations(range(len(hand)), k):
            chosen = [hand[i] for i in comb]
            hand_name = classify_hand(chosen)
            h = hands.get(hand_name) or {}
            score = int(h.get("chips", 0) or 0) * int(h.get("mult", 0) or 0)
            key = (score, -k)
            if best is None or key > best[0]:
                best = (key, list(comb))
    return best[1] if best else list(range(min(5, len(hand))))


def estimate_play_score(state: Dict[str, Any], cards: List[int]) -> int:
    hand = ((state.get("hand") or {}).get("cards") or [])
    hands = state.get("hands") or {}
    chosen = [hand[i] for i in cards if 0 <= i < len(hand)]
    if not chosen:
        return 0
    hand_name = classify_hand(chosen)
    h = hands.get(hand_name) or {}
    chips = int(h.get("chips", 0) or 0)
    mult = int(h.get("mult", 0) or 0)
    return chips * mult


def current_target_score(state: Dict[str, Any]) -> int:
    blinds = state.get("blinds") or {}
    for key in ("small", "big", "boss"):
        b = blinds.get(key) or {}
        if b.get("status") in ("CURRENT", "SELECTED"):
            return int(b.get("score", 0) or 0)
    return 0


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


def summarize_state(state: Dict[str, Any]) -> Dict[str, Any]:
    round_info = state.get("round") or {}
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
    }


def wait_for_state(
    rpc: JsonRpcClient,
    target_states: List[str],
    timeout_sec: float = 6.0,
    poll_sec: float = 0.08,
) -> Optional[Dict[str, Any]]:
    deadline = time.time() + timeout_sec
    while time.time() < deadline:
        try:
            s = rpc.call("gamestate", retries=0)
            if s.get("state") in target_states:
                return s
        except Exception:
            pass
        time.sleep(poll_sec)
    return None


def decide_with_policy(
    policy: OllamaPolicy,
    stage: str,
    state: Dict[str, Any],
    candidates: List[Dict[str, Any]],
) -> Tuple[Dict[str, Any], str]:
    choice = policy.choose(stage, summarize_state(state), candidates) if policy.enabled else None
    if choice:
        selected, reason = choice
        return selected, reason
    return candidates[0], ""


def run_single_game(
    rpc: JsonRpcClient,
    policy: OllamaPolicy,
    max_steps: int,
    verbose: bool,
) -> Dict[str, Any]:
    try:
        rpc.call("menu", retries=1)
    except Exception:
        pass
    state = wait_for_state(rpc, ["MENU"], timeout_sec=8.0) or {}
    if state.get("state") != "MENU":
        # One more hard attempt before giving up.
        rpc.call("menu", retries=1)
        state = wait_for_state(rpc, ["MENU"], timeout_sec=8.0) or {}
        if state.get("state") != "MENU":
            raise RuntimeError("failed to reach MENU before start")

    state = rpc.call("start", {"deck": "RED", "stake": "WHITE"}, retries=2)

    steps = 0
    buys: List[str] = []
    stalls = 0
    last_state = None
    stable_failures = 0

    while steps < max_steps:
        steps += 1
        st = state.get("state")
        won = bool(state.get("won"))

        if verbose and steps % 20 == 0:
            print(f"[step {steps}] state={st} money={state.get('money')} ante={state.get('ante_num')}")

        if won and st in ("ROUND_EVAL", "GAME_OVER"):
            break
        if st == "GAME_OVER":
            break

        if st == last_state:
            stalls += 1
        else:
            stalls = 0
            last_state = st

        try:
            if st == "BLIND_SELECT":
                candidates = choose_blind_candidates(state)
                selected, llm_reason = decide_with_policy(policy, "BLIND_SELECT", state, candidates)
                if llm_reason:
                    print(f"[llm-reason] stage=BLIND_SELECT choose={selected.get('why')} reason={llm_reason}")
                state = rpc.call(selected["action"], selected.get("params"), retries=2)
                continue

            if st == "SELECTING_HAND":
                hand = ((state.get("hand") or {}).get("cards") or [])
                if not hand:
                    state = rpc.call("gamestate", retries=1)
                    continue

                candidates = choose_hand_candidates(state)
                selected, llm_reason = decide_with_policy(policy, "SELECTING_HAND", state, candidates)
                if llm_reason:
                    print(f"[llm-reason] stage=SELECTING_HAND choose={selected.get('why')} reason={llm_reason}")
                state = rpc.call(selected["action"], selected.get("params"), retries=1)
                continue

            if st == "ROUND_EVAL":
                if bool(state.get("won")):
                    break
                candidates = [{"action": "cash_out", "params": None, "why": "collect rewards and go shop"}]
                selected, llm_reason = decide_with_policy(policy, "ROUND_EVAL", state, candidates)
                if llm_reason:
                    print(f"[llm-reason] stage=ROUND_EVAL choose={selected.get('why')} reason={llm_reason}")
                state = rpc.call(selected["action"], selected.get("params"), retries=1)
                continue

            if st == "SHOP":
                candidates = choose_shop_candidates(state)
                selected, llm_reason = decide_with_policy(policy, "SHOP", state, candidates)
                if llm_reason:
                    print(f"[llm-reason] stage=SHOP choose={selected.get('why', selected.get('action'))} reason={llm_reason}")
                action = selected["action"]
                params = selected.get("params")

                if action == "buy":
                    try:
                        state = rpc.call("buy", params, retries=0)
                        buys.append(selected.get("why", "buy"))
                    except Exception:
                        # If buy fails, do not loop on same item.
                        state = rpc.call("next_round", retries=1)
                else:
                    state = rpc.call("next_round", retries=1)
                continue

            if st == "SMODS_BOOSTER_OPENED":
                candidates = choose_pack_candidates(state)
                selected, llm_reason = decide_with_policy(policy, "SMODS_BOOSTER_OPENED", state, candidates)
                if llm_reason:
                    print(f"[llm-reason] stage=SMODS_BOOSTER_OPENED choose={selected.get('why')} reason={llm_reason}")
                state = rpc.call(selected["action"], selected.get("params"), retries=0)
                continue

            # Transient animation states
            if stalls > 80:
                # hard recovery
                state = rpc.call("gamestate", retries=1)
                stable_failures += 1
                if stable_failures > 5:
                    break
            else:
                time.sleep(0.06)
                state = rpc.call("gamestate", retries=1)
        except Exception:
            time.sleep(0.10)
            try:
                state = rpc.call("gamestate", retries=1)
            except Exception:
                stable_failures += 1
                if stable_failures > 5:
                    break

    try:
        final_state = rpc.call("gamestate", retries=1)
    except Exception:
        final_state = state

    return {
        "won": bool(final_state.get("won")),
        "state": final_state.get("state"),
        "ante": final_state.get("ante_num"),
        "round": final_state.get("round_num"),
        "money": final_state.get("money"),
        "steps": steps,
        "buy_count": len(buys),
        "buy_examples": buys[:8],
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Balatro Gemma agent (state machine + LLM policy + heuristic fallback)")
    parser.add_argument("--host", default=os.getenv("BALATROBOT_HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.getenv("BALATROBOT_PORT", "12346")))
    parser.add_argument("--rpc-timeout", type=float, default=20.0)
    parser.add_argument("--games", type=int, default=1)
    parser.add_argument("--max-steps", type=int, default=900)
    parser.add_argument("--seed", type=int, default=42)

    parser.add_argument("--use-llm", action="store_true", default=True)
    parser.add_argument("--no-llm", action="store_true")
    parser.add_argument("--ollama-url", default=os.getenv("OLLAMA_URL", "http://127.0.0.1:11434/api/chat"))
    parser.add_argument("--ollama-model", default=os.getenv("OLLAMA_MODEL", "gemma4:e2b-it-q4_K_M"))
    parser.add_argument("--ollama-timeout", type=float, default=30.0)
    parser.add_argument("--llm-log-io", dest="llm_log_io", action="store_true", default=True)
    parser.add_argument("--no-llm-log-io", dest="llm_log_io", action="store_false")
    parser.add_argument("--verbose", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    random.seed(args.seed)

    use_llm = args.use_llm and not args.no_llm
    rpc = JsonRpcClient(args.host, args.port, args.rpc_timeout)
    policy = OllamaPolicy(use_llm, args.ollama_model, args.ollama_url, args.ollama_timeout, args.llm_log_io)

    try:
        health = rpc.call("health", retries=1)
    except Exception as e:
        print(f"[fatal] balatrobot health check failed: {e}")
        return

    print(f"health={health.get('status')} llm={use_llm} model={args.ollama_model}")
    all_results: List[Dict[str, Any]] = []

    for i in range(1, args.games + 1):
        t0 = time.time()
        result = run_single_game(rpc, policy, args.max_steps, args.verbose)
        dt = time.time() - t0
        all_results.append(result)
        print(
            f"GAME {i}: won={result['won']} state={result['state']} ante={result['ante']} "
            f"round={result['round']} money={result['money']} buys={result['buy_count']} "
            f"steps={result['steps']} time={dt:.1f}s"
        )
        if result["buy_examples"]:
            print("  buy_examples:", "; ".join(result["buy_examples"]))

    print("RESULTS_JSON")
    print(json.dumps(all_results, ensure_ascii=False))


if __name__ == "__main__":
    main()
