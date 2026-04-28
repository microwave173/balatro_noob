import time
from typing import Any, Dict, List, Tuple

from .llm_policy import LLMPolicy
from .rpc_client import JsonRpcClient, wait_for_state
from .strategy import (
    choose_blind_candidates,
    choose_hand_candidates,
    choose_pack_candidates,
    choose_shop_candidates,
    summarize_state,
)


def _decide_with_policy(
    policy: LLMPolicy,
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
    policy: LLMPolicy,
    max_steps: int,
    verbose: bool,
    *,
    deck: str = "RED",
    stake: str = "WHITE",
) -> Dict[str, Any]:
    try:
        rpc.call("menu", retries=1)
    except Exception:
        pass
    state = wait_for_state(rpc, ["MENU"], timeout_sec=8.0) or {}
    if state.get("state") != "MENU":
        rpc.call("menu", retries=1)
        state = wait_for_state(rpc, ["MENU"], timeout_sec=8.0) or {}
        if state.get("state") != "MENU":
            raise RuntimeError("failed to reach MENU before start")

    state = rpc.call("start", {"deck": deck, "stake": stake}, retries=2)

    steps = 0
    buys: List[str] = []
    events: List[Dict[str, Any]] = []
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
                selected, llm_reason = _decide_with_policy(policy, "BLIND_SELECT", state, candidates)
                if llm_reason:
                    print(f"[llm-reason] stage=BLIND_SELECT choose={selected.get('why')} reason={llm_reason}")
                events.append(
                    {
                        "step": steps,
                        "stage": "BLIND_SELECT",
                        "state": summarize_state(state),
                        "candidates": candidates,
                        "selected": selected,
                        "llm_reason": llm_reason,
                    }
                )
                state = rpc.call(selected["action"], selected.get("params"), retries=2)
                continue

            if st == "SELECTING_HAND":
                hand = ((state.get("hand") or {}).get("cards") or [])
                if not hand:
                    state = rpc.call("gamestate", retries=1)
                    continue

                candidates = choose_hand_candidates(state)
                selected, llm_reason = _decide_with_policy(policy, "SELECTING_HAND", state, candidates)
                if llm_reason:
                    print(f"[llm-reason] stage=SELECTING_HAND choose={selected.get('why')} reason={llm_reason}")
                events.append(
                    {
                        "step": steps,
                        "stage": "SELECTING_HAND",
                        "state": summarize_state(state),
                        "candidates": candidates,
                        "selected": selected,
                        "llm_reason": llm_reason,
                    }
                )
                state = rpc.call(selected["action"], selected.get("params"), retries=1)
                continue

            if st == "ROUND_EVAL":
                if bool(state.get("won")):
                    break
                candidates = [{"action": "cash_out", "params": None, "why": "collect rewards and go shop"}]
                selected, llm_reason = _decide_with_policy(policy, "ROUND_EVAL", state, candidates)
                if llm_reason:
                    print(f"[llm-reason] stage=ROUND_EVAL choose={selected.get('why')} reason={llm_reason}")
                events.append(
                    {
                        "step": steps,
                        "stage": "ROUND_EVAL",
                        "state": summarize_state(state),
                        "candidates": candidates,
                        "selected": selected,
                        "llm_reason": llm_reason,
                    }
                )
                state = rpc.call(selected["action"], selected.get("params"), retries=1)
                continue

            if st == "SHOP":
                candidates = choose_shop_candidates(state)
                selected, llm_reason = _decide_with_policy(policy, "SHOP", state, candidates)
                if llm_reason:
                    print(f"[llm-reason] stage=SHOP choose={selected.get('why', selected.get('action'))} reason={llm_reason}")
                events.append(
                    {
                        "step": steps,
                        "stage": "SHOP",
                        "state": summarize_state(state),
                        "candidates": candidates,
                        "selected": selected,
                        "llm_reason": llm_reason,
                    }
                )
                action = selected["action"]
                params = selected.get("params")

                if action == "buy":
                    try:
                        state = rpc.call("buy", params, retries=0)
                        buys.append(selected.get("why", "buy"))
                    except Exception:
                        state = rpc.call("next_round", retries=1)
                else:
                    state = rpc.call("next_round", retries=1)
                continue

            if st == "SMODS_BOOSTER_OPENED":
                candidates = choose_pack_candidates(state)
                selected, llm_reason = _decide_with_policy(policy, "SMODS_BOOSTER_OPENED", state, candidates)
                if llm_reason:
                    print(f"[llm-reason] stage=SMODS_BOOSTER_OPENED choose={selected.get('why')} reason={llm_reason}")
                events.append(
                    {
                        "step": steps,
                        "stage": "SMODS_BOOSTER_OPENED",
                        "state": summarize_state(state),
                        "candidates": candidates,
                        "selected": selected,
                        "llm_reason": llm_reason,
                    }
                )
                state = rpc.call(selected["action"], selected.get("params"), retries=0)
                continue

            if stalls > 80:
                state = rpc.call("gamestate", retries=1)
                stable_failures += 1
                if stable_failures > 5:
                    break
            else:
                time.sleep(0.06)
                state = rpc.call("gamestate", retries=1)
        except Exception:
            events.append(
                {
                    "step": steps,
                    "stage": st,
                    "state": summarize_state(state),
                    "error": "action_or_poll_failed",
                }
            )
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
        "events": events,
    }
