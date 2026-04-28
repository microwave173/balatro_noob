import argparse
import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Run Balatro play+reflect closed loop")
    p.add_argument("--iterations", type=int, default=5, help="Number of play+reflect cycles")
    p.add_argument("--games-per-iter", type=int, default=3, help="Games to run in each cycle")
    p.add_argument("--reflect-max-runs", type=int, default=50, help="Recent run logs used by reflection")
    p.add_argument("--reflect-max-rules", type=int, default=24, help="Max rules kept in adaptive rulebook")
    p.add_argument("--provider", choices=["deepseek", "ollama"], default=os.getenv("LLM_PROVIDER", "deepseek"))
    p.add_argument("--model", default=os.getenv("LLM_MODEL", os.getenv("DEEPSEEK_MODEL", "deepseek-v4-flash")))
    p.add_argument("--deepseek-api-key", default=os.getenv("DEEPSEEK_API_KEY", ""))
    p.add_argument("--runs-dir", default=os.getenv("AGENT_RUNS_DIR", "runs"))
    p.add_argument("--reference-file", default=os.getenv("AGENT_REFERENCE_FILE", "agent_core/reference_guide.md"))
    p.add_argument("--skill-file", default=os.getenv("AGENT_SKILL_FILE", "agent_core/rulebook.md"))
    p.add_argument("--state-file", default="state.json", help="State JSON path for monitor")
    p.add_argument("--llm-log-io", action="store_true", default=True)
    p.add_argument("--no-llm-log-io", dest="llm_log_io", action="store_false")
    p.add_argument("--think", action="store_true", default=False)
    p.add_argument("--verbose", action="store_true")
    p.add_argument("--stop-on-error", action="store_true", default=True)
    p.add_argument("--keep-going-on-error", dest="stop_on_error", action="store_false")
    return p.parse_args()


def _run(cmd: List[str], env: dict) -> int:
    print(f"[cmd] {' '.join(cmd)}")
    proc = subprocess.run(cmd, env=env)
    return proc.returncode


def _now_str() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _write_json(path: Path, obj: Dict[str, Any]) -> None:
    # Preserve live per-API updates written by balatro_agent during PLAY stage.
    if path.exists():
        try:
            old = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(old, dict) and "live" in old and "live" not in obj:
                obj["live"] = old["live"]
        except Exception:
            pass
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")
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


def _summarize_runs(runs_dir: str) -> Dict[str, Any]:
    p = Path(runs_dir)
    if not p.exists():
        return {"total_runs": 0, "latest": None, "best": None}

    files = sorted([f for f in p.glob("*.json") if f.is_file()], key=lambda x: x.stat().st_mtime, reverse=True)
    results = [r for r in (_load_run_result(f) for f in files) if r is not None]
    if not results:
        return {"total_runs": len(files), "latest": None, "best": None}

    latest = results[0]
    best = max(results, key=lambda x: (x["ante"], x["round"], x["money"]))
    return {"total_runs": len(files), "latest": latest, "best": best}


def _load_rules(skill_file: str) -> Dict[str, Any]:
    p = Path(skill_file)
    if not p.exists() or not p.is_file():
        return {"source": None, "items": [], "path": str(p.resolve())}

    try:
        lines = p.read_text(encoding="utf-8").splitlines()
    except Exception:
        return {"source": None, "items": [], "path": str(p.resolve())}

    source = None
    items: List[str] = []
    in_rules = False
    for line in lines:
        if line.startswith("Source:"):
            source = line.split(":", 1)[1].strip()
        if line.strip() == "## Rules":
            in_rules = True
            continue
        if in_rules and line.startswith("- "):
            items.append(line[2:].strip())
    return {"source": source, "items": items, "path": str(p.resolve())}


def _update_state_snapshot(state: Dict[str, Any], runs_dir: str, skill_file: str) -> None:
    summary = _summarize_runs(runs_dir)
    state["counts"]["run_files_total"] = int(summary.get("total_runs", 0) or 0)
    state["current"] = summary.get("latest")
    state["best"] = summary.get("best")
    state["rules"] = _load_rules(skill_file)
    state["updated_at"] = _now_str()


def main() -> None:
    args = parse_args()
    here = Path(__file__).resolve().parent
    state_path = (here / args.state_file).resolve() if not Path(args.state_file).is_absolute() else Path(args.state_file)

    env = os.environ.copy()
    env["LLM_PROVIDER"] = args.provider
    env["LLM_MODEL"] = args.model
    env["AGENT_RUNS_DIR"] = args.runs_dir
    env["AGENT_REFERENCE_FILE"] = args.reference_file
    env["AGENT_SKILL_FILE"] = args.skill_file
    env["AGENT_STATE_FILE"] = str(state_path)
    if args.provider == "deepseek" and args.deepseek_api_key:
        env["DEEPSEEK_API_KEY"] = args.deepseek_api_key

    print(
        f"[loop] start={datetime.now().strftime('%Y-%m-%d %H:%M:%S')} "
        f"iterations={args.iterations} games_per_iter={args.games_per_iter} "
        f"provider={args.provider} model={args.model}"
    )
    print(f"[loop] reference_file={args.reference_file} skill_file={args.skill_file} runs_dir={args.runs_dir}")

    if args.provider == "deepseek" and not env.get("DEEPSEEK_API_KEY"):
        print("[fatal] deepseek provider selected but DEEPSEEK_API_KEY is empty")
        sys.exit(2)

    state: Dict[str, Any] = {
        "status": "running",
        "updated_at": _now_str(),
        "started_at": _now_str(),
        "finished_at": None,
        "last_error": None,
        "provider": args.provider,
        "model": args.model,
        "think": args.think,
        "paths": {
            "runs_dir": str((here / args.runs_dir).resolve() if not Path(args.runs_dir).is_absolute() else Path(args.runs_dir)),
            "reference_file": str((here / args.reference_file).resolve() if not Path(args.reference_file).is_absolute() else Path(args.reference_file)),
            "skill_file": str((here / args.skill_file).resolve() if not Path(args.skill_file).is_absolute() else Path(args.skill_file)),
            "state_file": str(state_path),
        },
        "loop": {
            "iterations_total": args.iterations,
            "games_per_iteration": args.games_per_iter,
            "reflect_max_runs": args.reflect_max_runs,
            "reflect_max_rules": args.reflect_max_rules,
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
        "rules": {"source": None, "items": []},
    }
    _update_state_snapshot(state, args.runs_dir, args.skill_file)
    _write_json(state_path, state)

    try:
        for i in range(1, args.iterations + 1):
            state["loop"]["current_iteration"] = i
            state["loop"]["stage"] = "PLAY"
            state["updated_at"] = _now_str()
            _write_json(state_path, state)

            before_runs = int(_summarize_runs(args.runs_dir).get("total_runs", 0) or 0)

            print(f"\n===== CYCLE {i}/{args.iterations}: PLAY =====")
            play_cmd = [
                sys.executable,
                "balatro_agent.py",
                "--games",
                str(args.games_per_iter),
                "--provider",
                args.provider,
                "--model",
                args.model,
                "--reference-file",
                args.reference_file,
                "--skill-file",
                args.skill_file,
                "--runs-dir",
                args.runs_dir,
                "--state-file",
                str(state_path),
            ]
            if args.llm_log_io:
                play_cmd.append("--llm-log-io")
            else:
                play_cmd.append("--no-llm-log-io")
            if args.think:
                play_cmd.append("--think")
            if args.provider == "deepseek":
                play_cmd.extend(["--deepseek-api-key", env.get("DEEPSEEK_API_KEY", "")])
            if args.verbose:
                play_cmd.append("--verbose")

            rc = _run(play_cmd, env=env)
            after_runs = int(_summarize_runs(args.runs_dir).get("total_runs", 0) or 0)
            if rc == 0:
                state["counts"]["games_completed"] += max(0, after_runs - before_runs)
            else:
                state["last_error"] = f"play stage failed in cycle {i}, exit={rc}"
                print(f"[error] {state['last_error']}")
                state["status"] = "error"
                _update_state_snapshot(state, args.runs_dir, args.skill_file)
                _write_json(state_path, state)
                if args.stop_on_error:
                    sys.exit(rc)

            _update_state_snapshot(state, args.runs_dir, args.skill_file)
            _write_json(state_path, state)

            state["loop"]["stage"] = "REFLECT"
            state["updated_at"] = _now_str()
            _write_json(state_path, state)

            print(f"\n===== CYCLE {i}/{args.iterations}: REFLECT =====")
            reflect_cmd = [
                sys.executable,
                "self_reflect.py",
                "--use-llm",
                "--provider",
                args.provider,
                "--model",
                args.model,
                "--max-runs",
                str(args.reflect_max_runs),
                "--max-rules",
                str(args.reflect_max_rules),
                "--runs-dir",
                args.runs_dir,
                "--output-skill-file",
                args.skill_file,
            ]
            if args.provider == "deepseek":
                reflect_cmd.extend(["--deepseek-api-key", env.get("DEEPSEEK_API_KEY", "")])
            if args.verbose:
                reflect_cmd.append("--verbose")

            rc = _run(reflect_cmd, env=env)
            if rc == 0:
                state["counts"]["reflect_completed"] += 1
            else:
                state["last_error"] = f"reflect stage failed in cycle {i}, exit={rc}"
                print(f"[error] {state['last_error']}")
                state["status"] = "error"
                _update_state_snapshot(state, args.runs_dir, args.skill_file)
                _write_json(state_path, state)
                if args.stop_on_error:
                    sys.exit(rc)

            _update_state_snapshot(state, args.runs_dir, args.skill_file)
            _write_json(state_path, state)
    except KeyboardInterrupt:
        state["status"] = "stopped"
        state["last_error"] = "interrupted by user"
        state["finished_at"] = _now_str()
        _update_state_snapshot(state, args.runs_dir, args.skill_file)
        _write_json(state_path, state)
        raise

    print(f"\n[loop] done at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"[loop] latest rules updated at: {here / args.skill_file}")
    state["status"] = "done"
    state["loop"]["stage"] = "DONE"
    state["finished_at"] = _now_str()
    _update_state_snapshot(state, args.runs_dir, args.skill_file)
    _write_json(state_path, state)


if __name__ == "__main__":
    main()
