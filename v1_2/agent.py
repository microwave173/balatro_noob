import argparse
import json
import os
import random
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

if __package__ is None or __package__ == "":
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from v1_2.core.deepseek_policy import DeepSeekPolicy
from v1_2.core.effect_catalog import EffectCatalog
from v1_2.core.memory import SkillMemory
from v1_2.core.rpc import JsonRpcClient
from v1_2.core.runner import V12Runner, save_run_record


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Balatro agent v1.2: observation-first DeepSeek player")
    p.add_argument("--host", default=os.getenv("BALATROBOT_HOST", "127.0.0.1"))
    p.add_argument("--port", type=int, default=int(os.getenv("BALATROBOT_PORT", "12346")))
    p.add_argument("--rpc-timeout", type=float, default=20.0)
    p.add_argument("--games", type=int, default=1)
    p.add_argument("--max-steps", type=int, default=900)
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--deck", default="RED")
    p.add_argument("--stake", default="WHITE")
    p.add_argument("--model", default=os.getenv("DEEPSEEK_MODEL", "deepseek-v4-flash"))
    p.add_argument("--deepseek-url", default=os.getenv("DEEPSEEK_BASE_URL", os.getenv("DEEPSEEK_URL", "https://api.deepseek.com")))
    p.add_argument("--deepseek-api-key", default=os.getenv("DEEPSEEK_API_KEY", ""))
    p.add_argument("--llm-timeout", type=float, default=45.0)
    p.add_argument("--llm-log-io", action="store_true")
    p.add_argument("--think", action="store_true", help="Enable DeepSeek thinking mode for play/shop decisions")
    p.add_argument("--reasoning-effort", default="high", choices=["low", "medium", "high"], help="DeepSeek thinking strength when --think is enabled")
    p.add_argument("--play-candidate-count", type=int, default=0, help=argparse.SUPPRESS)
    p.add_argument("--out-dir", default="v1_2/out")
    p.add_argument("--state-file", default=os.getenv("V12_STATE_FILE", ""))
    p.add_argument("--openrpc-path", default="")
    p.add_argument("--verbose", action="store_true")
    return p.parse_args()


def main() -> None:
    args = parse_args()
    random.seed(args.seed)
    if not args.deepseek_api_key:
        print("[fatal] DEEPSEEK_API_KEY is empty")
        return

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    rpc_state_updater = _make_rpc_state_updater(args.state_file, args.model, args.think, args.reasoning_effort)
    rpc = JsonRpcClient(args.host, args.port, args.rpc_timeout, on_result=rpc_state_updater)
    policy = DeepSeekPolicy(
        api_key=args.deepseek_api_key,
        model=args.model,
        url=args.deepseek_url,
        timeout=args.llm_timeout,
        log_io=args.llm_log_io,
        think=args.think,
        reasoning_effort=args.reasoning_effort,
    )
    catalog = EffectCatalog(args.openrpc_path or None)
    memory = SkillMemory(out_dir / "memory")
    runner = V12Runner(
        rpc,
        policy,
        catalog,
        memory,
        out_dir=out_dir,
        max_steps=args.max_steps,
        verbose=args.verbose,
    )

    try:
        health = rpc.call("health", retries=1)
    except Exception as e:
        print(f"[fatal] balatrobot health check failed: {e}")
        return

    print(f"health={health.get('status')} version=v1_2 model={args.model} games={args.games}")
    if args.state_file:
        print(f"live_state_file={Path(args.state_file).resolve()}")
    results: List[Dict[str, Any]] = []

    for i in range(1, args.games + 1):
        t0 = time.time()
        result = runner.run_game(deck=args.deck, stake=args.stake)
        dt = time.time() - t0
        record = {
            "meta": {
                "version": "v1_2",
                "model": args.model,
                "think": args.think,
                "reasoning_effort": args.reasoning_effort if args.think else None,
                "deck": args.deck,
                "stake": args.stake,
                "game_index": i,
                "duration_sec": dt,
            },
            "result": result,
        }
        path = save_run_record(out_dir, record)
        summary = {k: v for k, v in result.items() if k != "events"}
        results.append(summary)
        print(
            f"GAME {i}: won={summary['won']} state={summary['state']} ante={summary['ante']} "
            f"round={summary['round']} money={summary['money']} buys={summary['buy_count']} "
            f"time={dt:.1f}s log={path}"
        )

    print("RESULTS_JSON")
    print(json.dumps(results, ensure_ascii=False))


def _safe_load_json(path: Path) -> Dict[str, Any]:
    if not path.exists() or not path.is_file():
        return {}
    try:
        obj = json.loads(path.read_text(encoding="utf-8"))
        return obj if isinstance(obj, dict) else {}
    except Exception:
        return {}


def _write_json_atomic(path: Path, obj: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def _score_result(item: Dict[str, Any] | None) -> tuple[int, int, int, int]:
    if not item:
        return (0, 0, 0, 0)
    return (
        int(bool(item.get("won", False))),
        int(item.get("ante", 0) or 0),
        int(item.get("round", 0) or 0),
        int(item.get("money", 0) or 0),
    )


def _make_rpc_state_updater(
    state_file: str,
    model: str,
    think: bool,
    reasoning_effort: str,
) -> Optional[Callable[[str, Dict[str, Any]], None]]:
    if not state_file:
        return None
    state_path = Path(state_file)
    if not state_path.is_absolute():
        state_path = (Path.cwd() / state_path).resolve()

    counters = {"api_calls_total": 0, "api_calls_with_ante_round": 0}

    def _on_result(method: str, result: Dict[str, Any]) -> None:
        counters["api_calls_total"] += 1
        if "ante_num" not in result and "round_num" not in result:
            return
        counters["api_calls_with_ante_round"] += 1

        state = _safe_load_json(state_path)
        live = state.get("live") if isinstance(state.get("live"), dict) else {}
        live.update(
            {
                "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "source": "v1_2.agent.rpc",
                "last_method": method,
                "state": result.get("state"),
                "ante": result.get("ante_num"),
                "round": result.get("round_num"),
                "money": result.get("money"),
                "won": result.get("won"),
                "provider": "deepseek",
                "model": model,
                "think": think,
                "reasoning_effort": reasoning_effort if think else None,
                "api_calls_total": counters["api_calls_total"],
                "api_calls_with_ante_round": counters["api_calls_with_ante_round"],
            }
        )
        state["live"] = live
        live_candidate = {
            "file": None,
            "ante": int(result.get("ante_num", 0) or 0),
            "round": int(result.get("round_num", 0) or 0),
            "won": bool(result.get("won", False)),
            "money": int(result.get("money", 0) or 0),
            "state": str(result.get("state", "")),
            "source": "live",
        }
        live_best = state.get("live_best") if isinstance(state.get("live_best"), dict) else None
        if _score_result(live_candidate) > _score_result(live_best):
            state["live_best"] = live_candidate

        best = state.get("best") if isinstance(state.get("best"), dict) else None
        if _score_result(state.get("live_best")) > _score_result(best):
            state["best"] = state["live_best"]
        try:
            _write_json_atomic(state_path, state)
        except Exception:
            pass

    return _on_result


if __name__ == "__main__":
    main()
