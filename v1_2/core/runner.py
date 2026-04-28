import json
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

from .deepseek_policy import DeepSeekPolicy
from .effect_catalog import EffectCatalog
from .memory import SkillMemory, append_jsonl
from .observation import build_observation, current_blind_key
from .rpc import JsonRpcClient, wait_for_state
from .validator import (
    validate_blind_action,
    validate_pack_action,
    validate_play_action,
    validate_shop_action,
)


class V12Runner:
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
        blind_plan = ""
        shop_plan = ""
        blind_plan_key = ""
        shop_plan_key = ""
        events: List[Dict[str, Any]] = []
        buys: List[str] = []

        for step in range(1, self.max_steps + 1):
            st = state.get("state")
            if self.verbose:
                print(f"[v1_2 step {step}] state={st} ante={state.get('ante_num')} round={state.get('round_num')} money={state.get('money')}")

            if bool(state.get("won")) and st in ("ROUND_EVAL", "GAME_OVER"):
                break
            if st == "GAME_OVER":
                break

            try:
                if st == "BLIND_SELECT":
                    obs = self._obs(state, "BLIND_SELECT", run_plan, "")
                    decision = self.policy.blind_select(obs["compact"])
                    action, params = validate_blind_action(decision, obs["state"])
                    before = _state_brief(obs["state"])
                    state = self.rpc.call(action, params, retries=2)
                    blind_plan = ""
                    shop_plan = ""
                    events.append(_event(step, "BLIND_SELECT", obs, decision, action, params, before, _state_brief(state)))
                    continue

                if st == "SELECTING_HAND":
                    if not (((state.get("hand") or {}).get("cards")) or []):
                        state = self.rpc.call("gamestate", retries=1)
                        continue

                    cur_key = f"{state.get('ante_num')}-{state.get('round_num')}-{current_blind_key(state)}"
                    skills = self.memory.retrieve("PLAY", state)
                    if cur_key != blind_plan_key:
                        plan_obs = self._obs(state, "PLAY", run_plan, "", skills)
                        plan = self.policy.blind_plan(plan_obs["compact"])
                        blind_plan = str(plan.get("blind_plan") or plan.get("phase_plan") or "").strip()
                        if blind_plan:
                            run_plan = _merge_plan(run_plan, blind_plan)
                        blind_plan_key = cur_key

                    obs = self._obs(state, "PLAY", run_plan, blind_plan, skills)
                    decision = self.policy.play_decision(obs["compact"])
                    inspected_deck = False
                    if str(decision.get("action") or "").lower() == "inspect_deck":
                        inspected_deck = True
                        inspect_obs = self._obs(
                            state,
                            "PLAY",
                            run_plan,
                            _merge_plan(blind_plan, "Deck detail was inspected; now commit to play or discard."),
                            skills,
                            include_deck_detail=True,
                        )
                        decision = self.policy.play_decision(inspect_obs["compact"])
                        obs = inspect_obs
                    if decision.get("phase_plan"):
                        blind_plan = _merge_plan(blind_plan, str(decision.get("phase_plan") or ""))
                        run_plan = _merge_plan(run_plan, str(decision.get("phase_plan") or ""))
                    action, params = validate_play_action(decision, obs["state"])
                    before = _state_brief(obs["state"])
                    if action == "use":
                        state = self.rpc.call("use", params, retries=1)
                    else:
                        state = self.rpc.call(action, params, retries=1)
                    after = _state_brief(state)
                    event = _event(step, "PLAY", obs, decision, action, params, before, after)
                    event["inspected_deck"] = inspected_deck
                    event["used_skills"] = decision.get("used_skills") or []
                    events.append(event)
                    self._write_play_memory(event)
                    continue

                if st == "ROUND_EVAL":
                    if bool(state.get("won")):
                        break
                    before = _state_brief(state)
                    state = self.rpc.call("cash_out", retries=1)
                    events.append({"step": step, "stage": "ROUND_EVAL", "action": "cash_out", "before": before, "after": _state_brief(state)})
                    continue

                if st == "SHOP":
                    auto_use = _auto_use_consumable_params(state)
                    if auto_use:
                        before = _state_brief(state)
                        state = self.rpc.call("use", auto_use, retries=1)
                        events.append({"step": step, "stage": "SHOP", "action": "use", "params": auto_use, "before": before, "after": _state_brief(state), "auto": True})
                        continue

                    shop_key = f"{state.get('ante_num')}-{state.get('round_num')}"
                    if shop_key != shop_plan_key:
                        shop_plan = ""
                        shop_plan_key = shop_key
                    skills = self.memory.retrieve("SHOP", state)
                    obs = self._obs(state, "SHOP", run_plan, shop_plan, skills)
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
                        except Exception:
                            state = self.rpc.call("next_round", retries=1)
                            action, params = "next_round", None
                    elif action == "use":
                        state = self.rpc.call("use", params, retries=1)
                    elif action == "sell":
                        state = self.rpc.call("sell", params, retries=1)
                    elif action == "reroll":
                        state = self.rpc.call("reroll", retries=1)
                    else:
                        state = self.rpc.call("next_round", retries=1)
                    after = _state_brief(state)
                    event = _event(step, "SHOP", obs, decision, action, params, before, after)
                    event["used_skills"] = decision.get("used_skills") or []
                    events.append(event)
                    self._write_shop_memory(event)
                    continue

                if st == "SMODS_BOOSTER_OPENED":
                    obs = self._obs(state, "PACK", run_plan, shop_plan)
                    decision = self.policy.pack_decision(obs["compact"])
                    action, params = validate_pack_action(decision, obs["state"])
                    before = _state_brief(obs["state"])
                    state = self.rpc.call(action, params, retries=0)
                    events.append(_event(step, "PACK", obs, decision, action, params, before, _state_brief(state)))
                    continue

                time.sleep(0.08)
                state = self.rpc.call("gamestate", retries=1)
            except Exception as e:
                events.append({"step": step, "stage": st, "error": str(e), "state": _state_brief(state)})
                time.sleep(0.15)
                try:
                    state = self.rpc.call("gamestate", retries=1)
                except Exception:
                    break

        try:
            final_state = self.rpc.call("gamestate", retries=1)
        except Exception:
            final_state = state

        return {
            "version": "v1_2",
            "won": bool(final_state.get("won")),
            "state": final_state.get("state"),
            "ante": final_state.get("ante_num"),
            "round": final_state.get("round_num"),
            "money": final_state.get("money"),
            "buy_count": len(buys),
            "buy_examples": buys[:10],
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
        relevant_skills: List[Dict[str, Any]] | None = None,
        include_deck_detail: bool = False,
    ) -> Dict[str, Any]:
        return build_observation(
            state,
            self.catalog,
            phase=phase,
            run_plan=run_plan,
            phase_plan=phase_plan,
            relevant_skills=relevant_skills or [],
            long_term_context=self.memory.long_term_context(),
            include_deck_detail=include_deck_detail,
        )

    def _write_play_memory(self, event: Dict[str, Any]) -> None:
        append_jsonl(self.mem_dir / "play_memory.jsonl", _memory_item("play", event))

    def _write_shop_memory(self, event: Dict[str, Any]) -> None:
        append_jsonl(self.mem_dir / "shop_memory.jsonl", _memory_item("shop", event))


def save_run_record(out_dir: str | Path, record: Dict[str, Any]) -> Path:
    p = Path(out_dir) / "runs"
    p.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out = p / f"{ts}_v1_2.json"
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
    return {
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
        "used_skills": event.get("used_skills") or [],
    }


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
