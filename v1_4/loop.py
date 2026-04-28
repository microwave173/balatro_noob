import argparse
import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Run v1.4 play + reflect loop")
    p.add_argument("--iterations", type=int, default=5)
    p.add_argument("--games-per-iter", type=int, default=2)
    p.add_argument("--out-dir", default="v1_4/out")
    p.add_argument("--provider", default=os.getenv("LLM_PROVIDER", "deepseek"), choices=["deepseek", "qwen"])
    p.add_argument("--model", default=os.getenv("DEEPSEEK_MODEL", "deepseek-v4-pro"))
    p.add_argument("--deepseek-api-key", default=os.getenv("DEEPSEEK_API_KEY", ""))
    p.add_argument("--qwen-api-key", default=os.getenv("QWEN_API_KEY", os.getenv("DASHSCOPE_API_KEY", "")))
    p.add_argument("--state-file", default="state.json", help="State JSON path for monitor")
    p.add_argument("--llm-log-io", action="store_true", help="Print LLM outputs only; prompts are not printed")
    p.add_argument("--think", dest="think", action="store_true", default=True, help="Enable model thinking mode for play/shop decisions when the provider supports it")
    p.add_argument("--no-think", dest="think", action="store_false", help="Disable model thinking mode")
    p.add_argument("--reasoning-effort", default="high", choices=["low", "medium", "high", "max"], help="Thinking strength when --think is enabled; DeepSeek uses high|max")
    p.add_argument("--thinking-budget", type=int, default=0, help="Qwen thinking token budget when --think is enabled; 0 maps reasoning effort to a default budget")
    p.add_argument("--decision-format", default="auto", choices=["auto", "json", "tool"], help="Structured decision transport: auto uses JSON output for DeepSeek and tool calls for Qwen")
    p.add_argument("--keep-going-on-error", action="store_true")
    return p.parse_args()


def _now_str() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _write_json(path: Path, obj: Dict[str, Any]) -> None:
    out = dict(obj)
    if path.exists():
        try:
            old = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(old, dict) and "live" in old:
                out["live"] = old["live"]
        except Exception:
            pass
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def _load_run_result(path: Path) -> Optional[Dict[str, Any]]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    result = data.get("result") or {}
    return {
        "file": str(path.resolve()),
        "ante": int(result.get("ante", 0) or 0),
        "round": int(result.get("round", 0) or 0),
        "won": bool(result.get("won", False)),
        "money": int(result.get("money", 0) or 0),
        "state": str(result.get("state", "")),
    }


def _score_result(item: Dict[str, Any] | None) -> tuple[int, int, int, int]:
    if not item:
        return (0, 0, 0, 0)
    return (
        int(bool(item.get("won", False))),
        int(item.get("ante", 0) or 0),
        int(item.get("round", 0) or 0),
        int(item.get("money", 0) or 0),
    )


def _summarize_runs(out_dir: str | Path) -> Dict[str, Any]:
    runs_dir = Path(out_dir) / "runs"
    if not runs_dir.exists():
        return {"total_runs": 0, "latest": None, "best": None}

    files = sorted([f for f in runs_dir.glob("*.json") if f.is_file()], key=lambda x: x.stat().st_mtime, reverse=True)
    results = [r for r in (_load_run_result(f) for f in files) if r is not None]
    if not results:
        return {"total_runs": len(files), "latest": None, "best": None}

    latest = results[0]
    best = max(results, key=_score_result)
    return {"total_runs": len(files), "latest": latest, "best": best}


def _load_rules(out_dir: str | Path) -> Dict[str, Any]:
    path = Path(out_dir) / "rulebook.md"
    if not path.exists() or not path.is_file():
        return {"source": None, "items": [], "path": str(path.resolve())}

    items: List[str] = []
    in_summary = False
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except Exception:
        return {"source": None, "items": [], "path": str(path.resolve())}

    for raw in lines:
        line = raw.strip()
        if line.startswith("## "):
            in_summary = line == "## Summary Rules"
            continue
        if in_summary and line.startswith("- "):
            text = line[2:].strip()
            if text and not text.startswith("No reflected"):
                items.append(text)
    return {"source": str(path.resolve()), "items": items, "path": str(path.resolve())}


def _update_state_snapshot(state: Dict[str, Any], out_dir: str | Path) -> None:
    summary = _summarize_runs(out_dir)
    live = state.get("live") if isinstance(state.get("live"), dict) else {}
    file_best = summary.get("best")
    live_best = state.get("live_best") if isinstance(state.get("live_best"), dict) else None
    if live and live.get("ante") is not None:
        live_candidate = {
            "file": None,
            "ante": int(live.get("ante", 0) or 0),
            "round": int(live.get("round", 0) or 0),
            "won": bool(live.get("won", False)),
            "money": int(live.get("money", 0) or 0),
            "state": str(live.get("state", "")),
            "source": "live",
        }
        if _score_result(live_candidate) > _score_result(live_best):
            live_best = live_candidate
    best = max([x for x in (file_best, live_best) if x], key=_score_result, default=None)
    state["counts"]["run_files_total"] = int(summary.get("total_runs", 0) or 0)
    state["current"] = summary.get("latest")
    state["best"] = best
    state["best_file"] = file_best
    if live_best:
        state["live_best"] = live_best
    state["rules"] = _load_rules(out_dir)
    state["updated_at"] = _now_str()


def main() -> None:
    args = parse_args()
    if args.provider == "qwen" and args.model == "deepseek-v4-flash":
        args.model = "qwen3.6-plus"
    root = Path(__file__).resolve().parents[1]
    state_path = (root / args.state_file).resolve() if not Path(args.state_file).is_absolute() else Path(args.state_file)

    api_key = args.qwen_api_key if args.provider == "qwen" else args.deepseek_api_key
    if not api_key:
        env_name = "QWEN_API_KEY or DASHSCOPE_API_KEY" if args.provider == "qwen" else "DEEPSEEK_API_KEY"
        print(f"[fatal] {env_name} is empty")
        state = _initial_state(args, root, state_path)
        state["status"] = "error"
        state["last_error"] = f"{env_name} is empty"
        state["finished_at"] = _now_str()
        _update_state_snapshot(state, args.out_dir)
        _write_json(state_path, state)
        return

    env = os.environ.copy()
    if args.provider == "qwen":
        env["QWEN_API_KEY"] = api_key
        env["DASHSCOPE_API_KEY"] = api_key
    else:
        env["DEEPSEEK_API_KEY"] = api_key
    env["DEEPSEEK_MODEL"] = args.model
    env["V14_STATE_FILE"] = str(state_path)
    env["V13_STATE_FILE"] = str(state_path)

    state = _initial_state(args, root, state_path)
    _update_state_snapshot(state, args.out_dir)
    _write_json(state_path, state)

    try:
        for i in range(1, args.iterations + 1):
            state["loop"]["current_iteration"] = i
            state["loop"]["stage"] = "PLAY"
            _update_state_snapshot(state, args.out_dir)
            _write_json(state_path, state)

            before_runs = int(_summarize_runs(args.out_dir).get("total_runs", 0) or 0)

            print(f"\n===== v1.4 CYCLE {i}/{args.iterations}: PLAY =====")
            play_cmd = [
                sys.executable,
                "-m",
                "v1_4.agent",
                "--games",
                str(args.games_per_iter),
                "--model",
                args.model,
                "--provider",
                args.provider,
                "--out-dir",
                args.out_dir,
                "--state-file",
                str(state_path),
                "--decision-format",
                args.decision_format,
            ]
            if args.think:
                play_cmd.extend(["--think", "--reasoning-effort", args.reasoning_effort])
                if args.thinking_budget > 0:
                    play_cmd.extend(["--thinking-budget", str(args.thinking_budget)])
            else:
                play_cmd.append("--no-think")
            if args.llm_log_io:
                play_cmd.append("--llm-log-io")
            rc = subprocess.run(play_cmd, cwd=root, env=env).returncode
            after_runs = int(_summarize_runs(args.out_dir).get("total_runs", 0) or 0)
            if rc == 0:
                state["counts"]["games_completed"] += max(0, after_runs - before_runs)
            else:
                state["status"] = "error"
                state["last_error"] = f"play stage failed in cycle {i}, exit={rc}"
                _update_state_snapshot(state, args.out_dir)
                _write_json(state_path, state)
                if not args.keep_going_on_error:
                    sys.exit(rc)

            _update_state_snapshot(state, args.out_dir)
            _write_json(state_path, state)

            state["loop"]["stage"] = "REFLECT"
            _update_state_snapshot(state, args.out_dir)
            _write_json(state_path, state)

            print(f"\n===== v1.4 CYCLE {i}/{args.iterations}: REFLECT =====")
            reflect_cmd = [
                sys.executable,
                "-m",
                "v1_4.reflect",
                "--model",
                args.model,
                "--provider",
                args.provider,
                "--out-dir",
                args.out_dir,
                "--reasoning-effort",
                args.reasoning_effort,
                "--decision-format",
                args.decision_format,
            ]
            if args.thinking_budget > 0:
                reflect_cmd.extend(["--thinking-budget", str(args.thinking_budget)])
            if args.llm_log_io:
                reflect_cmd.append("--llm-log-io")
            rc = subprocess.run(reflect_cmd, cwd=root, env=env).returncode
            if rc == 0:
                state["counts"]["reflect_completed"] += 1
            else:
                state["status"] = "error"
                state["last_error"] = f"reflect stage failed in cycle {i}, exit={rc}"
                _update_state_snapshot(state, args.out_dir)
                _write_json(state_path, state)
                if not args.keep_going_on_error:
                    sys.exit(rc)

            _update_state_snapshot(state, args.out_dir)
            _write_json(state_path, state)
    except KeyboardInterrupt:
        state["status"] = "stopped"
        state["last_error"] = "interrupted by user"
        state["finished_at"] = _now_str()
        _update_state_snapshot(state, args.out_dir)
        _write_json(state_path, state)
        raise

    state["status"] = "done"
    state["loop"]["stage"] = "DONE"
    state["finished_at"] = _now_str()
    _update_state_snapshot(state, args.out_dir)
    _write_json(state_path, state)


def _initial_state(args: argparse.Namespace, root: Path, state_path: Path) -> Dict[str, Any]:
    out_dir = (root / args.out_dir).resolve() if not Path(args.out_dir).is_absolute() else Path(args.out_dir)
    return {
        "version": "v1_4",
        "status": "running",
        "updated_at": _now_str(),
        "started_at": _now_str(),
        "finished_at": None,
        "last_error": None,
        "provider": args.provider,
        "model": args.model,
        "think": args.think,
        "reasoning_effort": args.reasoning_effort if args.think else None,
        "thinking_budget": _effective_thinking_budget(args.provider, args.think, args.reasoning_effort, args.thinking_budget),
        "decision_format": args.decision_format,
        "paths": {
            "out_dir": str(out_dir),
            "runs_dir": str(out_dir / "runs"),
            "rulebook": str(out_dir / "rulebook.md"),
            "state_file": str(state_path),
        },
        "loop": {
            "iterations_total": args.iterations,
            "games_per_iteration": args.games_per_iter,
            "current_iteration": 0,
            "stage": "INIT",
        },
        "counts": {
            "games_completed": 0,
            "reflect_completed": 0,
            "run_files_total": 0,
        },
        "current": None,
        "best": None,
        "live": {
            "commentary": None,
            "commentary_label": None,
            "commentary_updated_at": None,
        },
        "rules": {"source": None, "items": []},
    }


def _effective_thinking_budget(provider: str, think: bool, reasoning_effort: str, thinking_budget: int) -> Optional[int]:
    if not think or str(provider or "").lower() != "qwen":
        return None
    if thinking_budget and thinking_budget > 0:
        return thinking_budget
    return {
        "low": 1024,
        "medium": 4096,
        "high": 8192,
    }.get(str(reasoning_effort or "high").lower(), 8192)


if __name__ == "__main__":
    main()

