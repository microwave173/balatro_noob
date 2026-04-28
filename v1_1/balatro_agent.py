import argparse
import json
import os
import random
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from agent_core.llm_policy import LLMPolicy
from agent_core.rpc_client import JsonRpcClient
from agent_core.runner import run_single_game


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Balatro agent with pluggable LLM providers")
    parser.add_argument("--host", default=os.getenv("BALATROBOT_HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.getenv("BALATROBOT_PORT", "12346")))
    parser.add_argument("--rpc-timeout", type=float, default=20.0)
    parser.add_argument("--games", type=int, default=1)
    parser.add_argument("--max-steps", type=int, default=900)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--deck", default="RED")
    parser.add_argument("--stake", default="WHITE")

    parser.add_argument("--provider", choices=["ollama", "deepseek"], default=os.getenv("LLM_PROVIDER", "deepseek"))
    parser.add_argument("--model", default=os.getenv("LLM_MODEL", ""))
    parser.add_argument("--use-llm", action="store_true", default=True)
    parser.add_argument("--no-llm", action="store_true")
    parser.add_argument("--llm-timeout", type=float, default=30.0)
    parser.add_argument("--llm-log-io", dest="llm_log_io", action="store_true", default=True)
    parser.add_argument("--no-llm-log-io", dest="llm_log_io", action="store_false")
    parser.add_argument("--think", action="store_true", default=False)
    parser.add_argument("--reference-file", default=os.getenv("AGENT_REFERENCE_FILE", "agent_core/reference_guide.md"))
    parser.add_argument("--ignore-reference-file", action="store_true")
    parser.add_argument("--skill-file", default=os.getenv("AGENT_SKILL_FILE", "agent_core/rulebook.md"))
    parser.add_argument("--ignore-skill-file", action="store_true")
    parser.add_argument("--runs-dir", default=os.getenv("AGENT_RUNS_DIR", "runs"))
    parser.add_argument("--no-save-runs", action="store_true")
    parser.add_argument("--state-file", default=os.getenv("AGENT_STATE_FILE", ""))

    parser.add_argument("--ollama-url", default=os.getenv("OLLAMA_URL", "http://127.0.0.1:11434/api/chat"))
    parser.add_argument("--deepseek-url", default=os.getenv("DEEPSEEK_URL", "https://api.deepseek.com/chat/completions"))
    parser.add_argument("--deepseek-api-key", default=os.getenv("DEEPSEEK_API_KEY", ""))
    parser.add_argument("--verbose", action="store_true")
    return parser.parse_args()


def _resolve_model(provider: str, model: str) -> str:
    if model:
        return model
    if provider == "ollama":
        return os.getenv("OLLAMA_MODEL", "gemma4:e2b-it-q4_K_M")
    return os.getenv("DEEPSEEK_MODEL", "deepseek-v4-flash")


def _load_skill_text(path: str, ignore: bool) -> str:
    if ignore:
        return ""
    p = Path(path)
    if not p.exists() or not p.is_file():
        return ""
    try:
        return p.read_text(encoding="utf-8")
    except Exception:
        return ""


def _load_text(path: str, ignore: bool) -> str:
    if ignore:
        return ""
    p = Path(path)
    if not p.exists() or not p.is_file():
        return ""
    try:
        return p.read_text(encoding="utf-8")
    except Exception:
        return ""


def _save_run_record(runs_dir: str, provider: str, model: str, game_idx: int, record: Dict[str, Any]) -> None:
    p = Path(runs_dir)
    p.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out = p / f"{ts}_g{game_idx}_{provider}_{model.replace(':', '_').replace('/', '_')}.json"
    out.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")


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


def _make_rpc_state_updater(
    state_file: str,
    provider: str,
    model: str,
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
                "source": "balatro_agent.rpc",
                "last_method": method,
                "state": result.get("state"),
                "ante": result.get("ante_num"),
                "round": result.get("round_num"),
                "money": result.get("money"),
                "won": result.get("won"),
                "provider": provider,
                "model": model,
                "api_calls_total": counters["api_calls_total"],
                "api_calls_with_ante_round": counters["api_calls_with_ante_round"],
            }
        )
        state["live"] = live
        try:
            _write_json_atomic(state_path, state)
        except Exception:
            pass

    return _on_result


def main() -> None:
    args = parse_args()
    random.seed(args.seed)

    use_llm = args.use_llm and not args.no_llm
    model = _resolve_model(args.provider, args.model)
    reference_text = _load_text(args.reference_file, args.ignore_reference_file)
    skill_text = _load_skill_text(args.skill_file, args.ignore_skill_file)

    if args.provider == "deepseek" and use_llm and not args.deepseek_api_key:
        print("[fatal] deepseek provider selected but DEEPSEEK_API_KEY is empty")
        return

    rpc_state_updater = _make_rpc_state_updater(args.state_file, args.provider, model)
    rpc = JsonRpcClient(args.host, args.port, args.rpc_timeout, on_result=rpc_state_updater)
    policy = LLMPolicy(
        enabled=use_llm,
        provider=args.provider,
        model=model,
        timeout=args.llm_timeout,
        log_io=args.llm_log_io,
        ollama_url=args.ollama_url,
        deepseek_url=args.deepseek_url,
        deepseek_api_key=args.deepseek_api_key,
        think=args.think,
        reference_text=reference_text,
        skill_text=skill_text,
    )

    try:
        health = rpc.call("health", retries=1)
    except Exception as e:
        print(f"[fatal] balatrobot health check failed: {e}")
        return

    print(
        f"health={health.get('status')} llm={use_llm} provider={args.provider} "
        f"model={model} think={args.think}"
    )
    print(
        f"reference_file={'(ignored)' if args.ignore_reference_file else args.reference_file} "
        f"rulebook_file={'(ignored)' if args.ignore_skill_file else args.skill_file}"
    )
    if args.state_file:
        print(f"live_state_file={Path(args.state_file).resolve()}")
    all_results: List[Dict[str, Any]] = []

    for i in range(1, args.games + 1):
        t0 = time.time()
        full_result = run_single_game(
            rpc,
            policy,
            args.max_steps,
            args.verbose,
            deck=args.deck,
            stake=args.stake,
        )
        dt = time.time() - t0
        if not args.no_save_runs:
            record = {
                "meta": {
                    "provider": args.provider,
                    "model": model,
                    "llm_enabled": use_llm,
                    "think": args.think,
                    "deck": args.deck,
                    "stake": args.stake,
                    "game_index": i,
                    "duration_sec": dt,
                    "skill_file": None if args.ignore_skill_file else args.skill_file,
                },
                "result": full_result,
            }
            _save_run_record(args.runs_dir, args.provider, model, i, record)

        result = {k: v for k, v in full_result.items() if k != "events"}
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
