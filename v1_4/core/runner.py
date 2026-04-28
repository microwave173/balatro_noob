import json
import time
from concurrent.futures import Future, ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

from .deepseek_policy import DeepSeekPolicy
from .effect_catalog import EffectCatalog
from .memory import SkillMemory, append_jsonl
from .observation import build_observation
from .rpc import JsonRpcClient, wait_for_state
from .validator import (
    validate_blind_action,
    validate_pack_action,
    validate_play_action,
    validate_shop_action,
)


HISTORY_KEEP_RECENT = 8
HISTORY_COMPRESS_TRIGGER_RECORDS = 12
HISTORY_MAX_CHARS = 7200


class V14Runner:
    def __init__(
        self,
        rpc: JsonRpcClient,
        policy: DeepSeekPolicy,
        catalog: EffectCatalog,
        memory: SkillMemory,
        *,
        out_dir: str | Path,
        max_steps: int = 900,
        verbose: bool = False,
    ) -> None:
        self.rpc = rpc
        self.policy = policy
        self.catalog = catalog
        self.memory = memory
        self.out_dir = Path(out_dir)
        self.max_steps = max_steps
        self.verbose = verbose
        self.mem_dir = self.out_dir / "memory"
        self.mem_dir.mkdir(parents=True, exist_ok=True)

    def run_game(self, deck: str = "RED", stake: str = "WHITE") -> Dict[str, Any]:
        state = self._start_game(deck, stake)
        run_plan = "Survive with stable scoring; adapt build around current Jokers, shop offers, and boss effects."
        shop_plan = ""
        shop_plan_key = ""
        action_feedback = ""
        history_summary = ""
        recent_history: List[Dict[str, Any]] = []
        history_compactor = _AsyncHistoryCompactor(self.policy)
        recent_play_results: List[Dict[str, Any]] = []
        events: List[Dict[str, Any]] = []
        buys: List[str] = []

        def remember(event: Dict[str, Any]) -> None:
            nonlocal history_summary, recent_history
            history_summary, recent_history = history_compactor.record(
                history_summary,
                recent_history,
                event,
            )

        for step in range(1, self.max_steps + 1):
            st = state.get("state")
            if self.verbose:
                print(f"[v1_4 step {step}] state={st} ante={state.get('ante_num')} round={state.get('round_num')} money={state.get('money')}")

            if bool(state.get("won")) and st in ("ROUND_EVAL", "GAME_OVER"):
                break
            if st == "GAME_OVER":
                break

            try:
                if st == "BLIND_SELECT":
                    obs = self._obs(state, "BLIND_SELECT", run_plan, "", history_summary=history_summary, recent_history=recent_history)
                    decision = self.policy.blind_select(obs["compact"])
                    action, params = validate_blind_action(decision, obs["state"])
                    before = _state_brief(obs["state"])
                    state = self.rpc.call(action, params, retries=2)
                    shop_plan = ""
                    action_feedback = ""
                    event = _event(step, "BLIND_SELECT", obs, decision, action, params, before, _state_brief(state))
                    events.append(event)
                    remember(event)
                    continue

                if st == "SELECTING_HAND":
                    if not (((state.get("hand") or {}).get("cards")) or []):
                        state = self.rpc.call("gamestate", retries=1)
                        continue

                    obs = self._obs(
                        state,
                        "PLAY",
                        run_plan,
                        action_feedback,
                        history_summary=history_summary,
                        recent_history=recent_history,
                    )
                    decision = self.policy.play_decision(obs["compact"])
                    inspected_deck = False
                    if str(decision.get("action") or "").lower() == "inspect_deck":
                        inspected_deck = True
                        inspect_obs = self._obs(
                            state,
                            "PLAY",
                            run_plan,
                            _merge_plan(action_feedback, "Deck detail was inspected; now commit to play or discard."),
                            include_deck_detail=True,
                            history_summary=history_summary,
                            recent_history=recent_history,
                        )
                        decision = self.policy.play_decision(inspect_obs["compact"])
                        obs = inspect_obs
                    if decision.get("phase_plan"):
                        run_plan = _merge_plan(run_plan, str(decision.get("phase_plan") or ""))
                    action, params = validate_play_action(decision, obs["state"])
                    before = _state_brief(obs["state"])
                    if action == "use":
                        try:
                            state = self.rpc.call("use", params, retries=1)
                            action_feedback = ""
                        except Exception as e:
                            msg = str(e)
                            if "NOT_ALLOWED" in msg:
                                action_feedback = _merge_plan(
                                    action_feedback,
                                    f"Previous attempted use {params} failed: {msg}. In this stage, do not try that consumable again; choose play, discard, inspect_deck, or another legal action.",
                                )
                                event = _event(step, "PLAY", obs, decision, action, params, before, before)
                                event["action_error"] = msg
                                events.append(event)
                                remember(event)
                                continue
                            raise
                    else:
                        state = self.rpc.call(action, params, retries=1)
                        action_feedback = ""
                    after = _state_brief(state)
                    event = _event(step, "PLAY", obs, decision, action, params, before, after)
                    event["inspected_deck"] = inspected_deck
                    events.append(event)
                    remember(event)
                    if action == "play":
                        recent_play_results.append(_play_result_summary(event))
                        recent_play_results = recent_play_results[-3:]
                    self._write_play_memory(event)
                    continue

                if st == "ROUND_EVAL":
                    if bool(state.get("won")):
                        break
                    before = _state_brief(state)
                    state = self.rpc.call("cash_out", retries=1)
                    event = {"step": step, "stage": "ROUND_EVAL", "action": "cash_out", "before": before, "after": _state_brief(state)}
                    events.append(event)
                    remember(event)
                    continue

                if st == "SHOP":
                    auto_use = _auto_use_consumable_params(state)
                    if auto_use:
                        before = _state_brief(state)
                        state = self.rpc.call("use", auto_use, retries=1)
                        event = {"step": step, "stage": "SHOP", "action": "use", "params": auto_use, "before": before, "after": _state_brief(state), "auto": True}
                        events.append(event)
                        remember(event)
                        continue

                    shop_key = f"{state.get('ante_num')}-{state.get('round_num')}"
                    if shop_key != shop_plan_key:
                        shop_plan = ""
                        action_feedback = ""
                        shop_plan_key = shop_key
                    obs = self._obs(
                        state,
                        "SHOP",
                        run_plan,
                        _merge_plan(shop_plan, action_feedback),
                        recent_play_results=recent_play_results,
                        history_summary=history_summary,
                        recent_history=recent_history,
                    )
                    decision = self.policy.shop_decision(obs["compact"])
                    if decision.get("shop_plan"):
                        shop_plan = str(decision.get("shop_plan") or "").strip()
                        run_plan = _merge_plan(run_plan, shop_plan)
                    action, params = validate_shop_action(decision, obs["state"])
                    before = _state_brief(obs["state"])
                    if action == "buy":
                        try:
                            state = self.rpc.call("buy", params, retries=0)
                            buys.append(str(decision.get("target") or params))
                            action_feedback = ""
                        except Exception:
                            state = self.rpc.call("next_round", retries=1)
                            action, params = "next_round", None
                            action_feedback = ""
                    elif action == "use":
                        try:
                            state = self.rpc.call("use", params, retries=1)
                            action_feedback = ""
                        except Exception as e:
                            msg = str(e)
                            if "NOT_ALLOWED" in msg:
                                action_feedback = _merge_plan(
                                    action_feedback,
                                    f"Previous attempted shop use {params} failed: {msg}. Do not try that consumable again in this stage; choose buy, sell, reroll, or next_round.",
                                )
                                event = _event(step, "SHOP", obs, decision, action, params, before, before)
                                event["action_error"] = msg
                                events.append(event)
                                remember(event)
                                self._write_shop_memory(event)
                                continue
                            raise
                    elif action == "sell":
                        state = self.rpc.call("sell", params, retries=1)
                        action_feedback = ""
                    elif action == "reroll":
                        state = self.rpc.call("reroll", retries=1)
                        action_feedback = ""
                    else:
                        state = self.rpc.call("next_round", retries=1)
                        action_feedback = ""
                    after = _state_brief(state)
                    event = _event(step, "SHOP", obs, decision, action, params, before, after)
                    events.append(event)
                    remember(event)
                    self._write_shop_memory(event)
                    continue

                if st == "SMODS_BOOSTER_OPENED":
                    obs = self._obs(state, "PACK", run_plan, shop_plan, history_summary=history_summary, recent_history=recent_history)
                    decision = self.policy.pack_decision(obs["compact"])
                    action, params = validate_pack_action(decision, obs["state"])
                    before = _state_brief(obs["state"])
                    state = self.rpc.call(action, params, retries=0)
                    event = _event(step, "PACK", obs, decision, action, params, before, _state_brief(state))
                    events.append(event)
                    remember(event)
                    continue

                time.sleep(0.08)
                state = self.rpc.call("gamestate", retries=1)
            except Exception as e:
                event = {"step": step, "stage": st, "error": str(e), "state": _state_brief(state)}
                events.append(event)
                remember(event)
                time.sleep(0.15)
                try:
                    state = self.rpc.call("gamestate", retries=1)
                except Exception:
                    break

        try:
            final_state = self.rpc.call("gamestate", retries=1)
        except Exception:
            final_state = state
        history_summary, recent_history = history_compactor.drain(history_summary, recent_history)
        history_compactor.close(wait=False)

        return {
            "version": "v1_4",
            "won": bool(final_state.get("won")),
            "state": final_state.get("state"),
            "ante": final_state.get("ante_num"),
            "round": final_state.get("round_num"),
            "money": final_state.get("money"),
            "buy_count": len(buys),
            "buy_examples": buys[:10],
            "history_summary": history_summary,
            "events": events,
        }

    def _start_game(self, deck: str, stake: str) -> Dict[str, Any]:
        try:
            self.rpc.call("menu", retries=1)
        except Exception:
            pass
        state = wait_for_state(self.rpc, {"MENU"}, timeout_sec=8.0) or {}
        if state.get("state") != "MENU":
            self.rpc.call("menu", retries=1)
            state = wait_for_state(self.rpc, {"MENU"}, timeout_sec=8.0) or {}
        if state.get("state") != "MENU":
            raise RuntimeError("failed to reach MENU before start")
        return self.rpc.call("start", {"deck": deck, "stake": stake}, retries=2)

    def _obs(
        self,
        state: Dict[str, Any],
        phase: str,
        run_plan: str,
        phase_plan: str,
        include_deck_detail: bool = False,
        recent_play_results: List[Dict[str, Any]] | None = None,
        history_summary: str = "",
        recent_history: List[Dict[str, Any]] | None = None,
    ) -> Dict[str, Any]:
        return build_observation(
            state,
            self.catalog,
            phase=phase,
            run_plan=run_plan,
            phase_plan=phase_plan,
            long_term_context=self.memory.long_term_context(),
            include_deck_detail=include_deck_detail,
            recent_play_results=recent_play_results or [],
            action_history_summary=history_summary,
            recent_actions=_render_recent_history(recent_history or []),
        )

    def _write_play_memory(self, event: Dict[str, Any]) -> None:
        append_jsonl(self.mem_dir / "play_memory.jsonl", _memory_item("play", event))

    def _write_shop_memory(self, event: Dict[str, Any]) -> None:
        append_jsonl(self.mem_dir / "shop_memory.jsonl", _memory_item("shop", event))


def save_run_record(out_dir: str | Path, record: Dict[str, Any]) -> Path:
    p = Path(out_dir) / "runs"
    p.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out = p / f"{ts}_v1_4.json"
    out.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
    return out


def _event(
    step: int,
    stage: str,
    obs: Dict[str, Any],
    decision: Dict[str, Any],
    action: str,
    params: Dict[str, Any] | None,
    before: Dict[str, Any],
    after: Dict[str, Any],
) -> Dict[str, Any]:
    out = {
        "step": step,
        "stage": stage,
        "joker_signature": obs.get("joker_signature") or [],
        "observation": obs,
        "decision": decision,
        "action": action,
        "params": params,
        "before": before,
        "after": after,
    }
    if isinstance(decision, dict) and decision.get("_parse_error"):
        out["decision_parse_error"] = True
    return out


def _memory_item(kind: str, event: Dict[str, Any]) -> Dict[str, Any]:
    before = event.get("before") or {}
    after = event.get("after") or {}
    reward = int(after.get("chips", 0) or 0) - int(before.get("chips", 0) or 0)
    return {
        "kind": kind,
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "joker_signature": event.get("joker_signature") or [],
        "observation": event.get("observation"),
        "inspected_deck": bool(event.get("inspected_deck")),
        "decision": event.get("decision"),
        "action": {"type": event.get("action"), "params": event.get("params")},
        "result": {
            "chips_delta": reward,
            "before": before,
            "after": after,
            "survived_step": after.get("state") != "GAME_OVER",
        },
    }


def _play_result_summary(event: Dict[str, Any]) -> Dict[str, Any]:
    before = event.get("before") or {}
    after = event.get("after") or {}
    decision = event.get("decision") or {}
    obs = event.get("observation") or {}
    state = obs.get("state") or {}
    blind = obs.get("boss") or {}
    chips_delta = int(after.get("chips", 0) or 0) - int(before.get("chips", 0) or 0)
    return {
        "ante": before.get("ante"),
        "round": before.get("round"),
        "jokers": event.get("joker_signature") or [],
        "action": event.get("action"),
        "hand": _played_hand_label(decision),
        "chips_delta": chips_delta,
        "total_chips": after.get("chips"),
        "blind_required": blind.get("score") or _current_blind_required(state),
    }


def _played_hand_label(decision: Dict[str, Any]) -> str:
    action = str(decision.get("action") or "").lower()
    cards = decision.get("cards")
    if action and isinstance(cards, list):
        return f"{action} cards={cards}"
    return action or "unknown"


def _current_blind_required(state: Dict[str, Any]) -> Any:
    blinds = state.get("blinds") or {}
    for key in ("small", "big", "boss"):
        blind = blinds.get(key) or {}
        if blind.get("status") in ("CURRENT", "SELECT", "SELECTED"):
            return blind.get("score")
    return None


def _state_brief(state: Dict[str, Any]) -> Dict[str, Any]:
    rnd = state.get("round") or {}
    return {
        "state": state.get("state"),
        "ante": state.get("ante_num"),
        "round": state.get("round_num"),
        "money": state.get("money"),
        "chips": rnd.get("chips"),
        "hands_left": rnd.get("hands_left"),
        "discards_left": rnd.get("discards_left"),
        "won": bool(state.get("won")),
    }


def _merge_plan(run_plan: str, new_plan: str) -> str:
    new_plan = " ".join(str(new_plan or "").split())
    if not new_plan:
        return run_plan
    base = " ".join(str(run_plan or "").split())
    merged = f"{base} Current plan: {new_plan}" if base else new_plan
    return merged[-900:]


class _AsyncHistoryCompactor:
    def __init__(self, policy: DeepSeekPolicy) -> None:
        self.policy = policy
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="v1_4_history_compactor")
        self.future: Future[str] | None = None
        self.pending_summary = ""
        self.pending_older: List[Dict[str, Any]] = []
        self.in_flight_count = 0

    def record(
        self,
        summary: str,
        recent: List[Dict[str, Any]],
        event: Dict[str, Any],
    ) -> tuple[str, List[Dict[str, Any]]]:
        summary = self._collect(summary)
        recent = list(recent) + [_history_record(event)]
        if len(recent) <= HISTORY_COMPRESS_TRIGGER_RECORDS and _history_chars(summary, recent) <= HISTORY_MAX_CHARS:
            return summary, recent

        keep = recent[-HISTORY_KEEP_RECENT:]
        older = recent[:-HISTORY_KEEP_RECENT]
        if not older:
            return summary[-1600:], keep

        if self.future is None:
            self.pending_summary = summary
            self.pending_older = older
            self.in_flight_count = len(older)
            self.future = self.executor.submit(_summarize_history_safe, self.policy, summary, older)
        else:
            self.pending_older.extend(older)
        return summary[-1600:], keep

    def drain(self, summary: str, recent: List[Dict[str, Any]]) -> tuple[str, List[Dict[str, Any]]]:
        if self.future is None:
            return summary, recent
        if not self.future.done():
            return summary, recent
        try:
            summary = str(self.future.result() or summary)
        except Exception:
            summary = _fallback_history_summary(self.pending_summary or summary, self.pending_older)
        self.future = None
        self.pending_summary = ""
        self.pending_older = []
        self.in_flight_count = 0
        return summary[-1600:], recent

    def close(self, *, wait: bool) -> None:
        self.executor.shutdown(wait=wait, cancel_futures=not wait)

    def _collect(self, summary: str) -> str:
        if self.future is None or not self.future.done():
            return summary
        try:
            out = str(self.future.result() or summary)
        except Exception:
            out = _fallback_history_summary(self.pending_summary or summary, self.pending_older)
        extra_older = self.pending_older[self.in_flight_count :]
        self.future = None
        self.pending_summary = ""
        self.pending_older = []
        self.in_flight_count = 0
        if extra_older:
            self.pending_summary = out
            self.pending_older = extra_older
            self.in_flight_count = len(extra_older)
            self.future = self.executor.submit(_summarize_history_safe, self.policy, out, extra_older)
        return out[-1600:]


def _summarize_history_safe(policy: DeepSeekPolicy, summary: str, older: List[Dict[str, Any]]) -> str:
    try:
        return policy.summarize_history(summary, older)
    except Exception:
        return _fallback_history_summary(summary, older)


def _record_action_history(
    policy: DeepSeekPolicy,
    summary: str,
    recent: List[Dict[str, Any]],
    event: Dict[str, Any],
) -> tuple[str, List[Dict[str, Any]]]:
    recent = list(recent) + [_history_record(event)]
    if len(recent) <= HISTORY_COMPRESS_TRIGGER_RECORDS and _history_chars(summary, recent) <= HISTORY_MAX_CHARS:
        return summary, recent

    keep = recent[-HISTORY_KEEP_RECENT:]
    older = recent[:-HISTORY_KEEP_RECENT]
    if not older:
        return summary[-1600:], keep
    try:
        new_summary = policy.summarize_history(summary, older)
    except Exception:
        new_summary = _fallback_history_summary(summary, older)
    return new_summary[-1600:], keep


def _history_record(event: Dict[str, Any]) -> Dict[str, Any]:
    decision = event.get("decision") if isinstance(event.get("decision"), dict) else {}
    before = event.get("before") or event.get("state") or {}
    after = event.get("after") or {}
    obs = event.get("observation") if isinstance(event.get("observation"), dict) else {}
    state = obs.get("state") if isinstance(obs.get("state"), dict) else {}
    record: Dict[str, Any] = {
        "step": event.get("step"),
        "stage": event.get("stage"),
        "action": event.get("action") or decision.get("action") or "error",
        "target": decision.get("target"),
        "cards": decision.get("cards"),
        "params": event.get("params"),
        "jokers": event.get("joker_signature") or _joker_labels(state),
        "before": _history_state(before),
        "after": _history_state(after),
    }
    if decision.get("reason"):
        record["reason"] = _clip(decision.get("reason"), 240)
    if decision.get("commentary"):
        record["commentary"] = _clip(decision.get("commentary"), 180)
    if event.get("action_error") or event.get("error"):
        record["error"] = _clip(event.get("action_error") or event.get("error"), 220)
    if event.get("inspected_deck"):
        record["inspected_deck"] = True
    if event.get("auto"):
        record["auto"] = True
    if record["action"] == "play":
        record["score_delta"] = _score_delta(before, after)
    return {k: v for k, v in record.items() if v not in (None, "", [], {})}


def _render_recent_history(recent: List[Dict[str, Any]]) -> List[str]:
    out: List[str] = []
    for r in recent[-HISTORY_KEEP_RECENT:]:
        before = r.get("before") or {}
        after = r.get("after") or {}
        parts = [
            f"step{r.get('step')}",
            str(r.get("stage") or "?"),
            str(r.get("action") or "?"),
        ]
        if r.get("target"):
            parts.append(f"target={r.get('target')}")
        if r.get("cards"):
            parts.append(f"cards={r.get('cards')}")
        if r.get("score_delta") is not None:
            parts.append(f"scored={r.get('score_delta')}")
        if before or after:
            parts.append(
                "state "
                f"{before.get('ante')}/{before.get('round')} chips={before.get('chips')} money={before.get('money')} "
                f"-> chips={after.get('chips')} money={after.get('money')} state={after.get('state')}"
            )
        if r.get("jokers"):
            parts.append(f"jokers={r.get('jokers')}")
        if r.get("error"):
            parts.append(f"error={r.get('error')}")
        if r.get("reason"):
            parts.append(f"reason={r.get('reason')}")
        out.append("; ".join(parts))
    return out


def _history_chars(summary: str, recent: List[Dict[str, Any]]) -> int:
    return len(summary or "") + len(json.dumps(recent, ensure_ascii=False, default=str))


def _fallback_history_summary(summary: str, older: List[Dict[str, Any]]) -> str:
    facts = []
    for r in older[-6:]:
        facts.append(
            f"step{r.get('step')} {r.get('stage')} {r.get('action')} "
            f"cards={r.get('cards')} target={r.get('target')} score_delta={r.get('score_delta')} "
            f"error={r.get('error') or ''}"
        )
    merged = " ".join([str(summary or "").strip(), "Older actions:", " | ".join(facts)]).strip()
    return _clip(merged, 1600)


def _history_state(state: Dict[str, Any]) -> Dict[str, Any]:
    return {
        k: state.get(k)
        for k in ("state", "ante", "round", "money", "chips", "hands_left", "discards_left", "won")
        if state.get(k) is not None
    }


def _score_delta(before: Dict[str, Any], after: Dict[str, Any]) -> int | None:
    if not before or not after:
        return None
    try:
        return int(after.get("chips", 0) or 0) - int(before.get("chips", 0) or 0)
    except Exception:
        return None


def _joker_labels(state: Dict[str, Any]) -> List[str]:
    return [str(c.get("label") or c.get("key") or "?") for c in (((state.get("jokers") or {}).get("cards")) or [])]


def _clip(value: Any, limit: int) -> str:
    text = " ".join(str(value or "").split())
    return text if len(text) <= limit else text[: max(0, limit - 3)] + "..."


PLANET_KEYS = {
    "c_mercury",
    "c_venus",
    "c_earth",
    "c_mars",
    "c_jupiter",
    "c_saturn",
    "c_uranus",
    "c_neptune",
    "c_pluto",
    "c_planet_x",
    "c_ceres",
    "c_eris",
}


def _auto_use_consumable_params(state: Dict[str, Any]) -> Dict[str, int] | None:
    if _has_observatory(state):
        return None
    consumables = ((state.get("consumables") or {}).get("cards")) or []
    for i, card in enumerate(consumables):
        if str(card.get("key") or "") in PLANET_KEYS:
            return {"consumable": i}
    return None


def _has_observatory(state: Dict[str, Any]) -> bool:
    used = {str(x) for x in (state.get("used_vouchers") or [])}
    if "v_observatory" in used:
        return True
    vouchers = ((state.get("vouchers") or {}).get("cards")) or []
    return any(str(v.get("key") or "") == "v_observatory" for v in vouchers)
