import argparse
import json
import os
import platform
import shlex
import subprocess
import sys
import time
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from v1_4.core.env import load_dotenv

load_dotenv()


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Run v1.4 play + reflect loop")
    p.add_argument("--iterations", type=int, default=5)
    p.add_argument("--games-per-iter", type=int, default=2)
    p.add_argument("--out-dir", default="v1_4/out")
    p.add_argument("--provider", default=os.getenv("LLM_PROVIDER", "deepseek"), choices=["deepseek", "qwen", "visioncoder"])
    p.add_argument("--model", default=os.getenv("DEEPSEEK_MODEL", "deepseek-v4-pro"))
    p.add_argument("--deepseek-api-key", default=os.getenv("DEEPSEEK_API_KEY", ""))
    p.add_argument("--qwen-api-key", default=os.getenv("QWEN_API_KEY", os.getenv("DASHSCOPE_API_KEY", "")))
    p.add_argument("--visioncoder-api-key", default=os.getenv("VISIONCODER_API_KEY", ""))
    p.add_argument("--state-file", default="state.json", help="State JSON path for monitor")
    p.add_argument("--llm-log-io", action="store_true", help="Print LLM outputs only; prompts are not printed")
    p.add_argument("--think", dest="think", action="store_true", default=True, help="Enable model thinking mode for play/shop decisions when the provider supports it")
    p.add_argument("--no-think", dest="think", action="store_false", help="Disable model thinking mode")
    p.add_argument("--reasoning-effort", default="high", choices=["low", "medium", "high", "max"], help="Thinking strength when --think is enabled; DeepSeek uses high|max")
    p.add_argument("--thinking-budget", type=int, default=0, help="Qwen thinking token budget when --think is enabled; 0 maps reasoning effort to a default budget")
    p.add_argument("--decision-format", default="auto", choices=["auto", "json", "tool"], help="Structured decision transport: auto uses JSON output for DeepSeek and tool calls for Qwen")
    p.add_argument("--keep-going-on-error", action="store_true")
    p.add_argument("--balatrobot-host", default=os.getenv("BALATROBOT_HOST", "127.0.0.1"))
    p.add_argument("--balatrobot-port", type=int, default=int(os.getenv("BALATROBOT_PORT", "12346")))
    p.add_argument("--balatrobot-health-timeout", type=float, default=35.0)
    p.add_argument("--balatrobot-serve-command", default=os.getenv("BALATROBOT_SERVE_COMMAND", ""), help="Override the command used to restart BalatroBot and Balatro")
    p.add_argument("--no-auto-restart-game", dest="auto_restart_game", action="store_false", default=True)
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
    if args.provider == "visioncoder" and args.model == "deepseek-v4-pro":
        args.model = os.getenv("VISIONCODER_MODEL", "gpt-5.6-sol")
    root = Path(__file__).resolve().parents[1]
    state_path = (root / args.state_file).resolve() if not Path(args.state_file).is_absolute() else Path(args.state_file)

    api_key = _provider_api_key(args)
    if not api_key:
        env_name = _provider_key_name(args.provider)
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
    elif args.provider == "visioncoder":
        env["VISIONCODER_API_KEY"] = api_key
        env["VISIONCODER_BASE_URL"] = os.getenv("VISIONCODER_BASE_URL", "https://coder.api.visioncoder.cn/v1")
        env["VISIONCODER_MODEL"] = args.model
    else:
        env["DEEPSEEK_API_KEY"] = api_key
    env["DEEPSEEK_MODEL"] = args.model
    env["V14_STATE_FILE"] = str(state_path)
    env["V13_STATE_FILE"] = str(state_path)

    state = _initial_state(args, root, state_path)
    _update_state_snapshot(state, args.out_dir)
    _write_json(state_path, state)
    serve_process: Optional[subprocess.Popen[Any]] = None

    try:
        for i in range(1, args.iterations + 1):
            state["loop"]["current_iteration"] = i
            state["loop"]["stage"] = "PLAY"
            _update_state_snapshot(state, args.out_dir)
            _write_json(state_path, state)

            print(f"\n===== v1.4 CYCLE {i}/{args.iterations}: PLAY =====")
            completed, play_error, serve_process = _run_games_individually(
                args, root, state_path, env, serve_process
            )
            state["counts"]["games_completed"] += completed
            if play_error:
                state["status"] = "error"
                state["last_error"] = f"play stage failed in cycle {i}: {play_error}"
                _update_state_snapshot(state, args.out_dir)
                _write_json(state_path, state)
                if not args.keep_going_on_error:
                    sys.exit(1)

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
    finally:
        _stop_managed_serve(serve_process)

    state["status"] = "done"
    state["loop"]["stage"] = "DONE"
    state["finished_at"] = _now_str()
    _update_state_snapshot(state, args.out_dir)
    _write_json(state_path, state)


def _run_games_individually(
    args: argparse.Namespace,
    root: Path,
    state_path: Path,
    env: Dict[str, str],
    serve_process: Optional[subprocess.Popen[Any]] = None,
) -> tuple[int, str, Optional[subprocess.Popen[Any]]]:
    completed = 0
    last_won = False
    for game_index in range(1, args.games_per_iter + 1):
        if last_won:
            # Winning can crash Balatro shortly after the final RPC response.
            time.sleep(1.0)
        if not _balatrobot_healthy(args.balatrobot_host, args.balatrobot_port):
            if not args.auto_restart_game:
                return completed, f"BalatroBot unavailable before game {game_index} and auto restart is disabled", serve_process
            serve_process, error = _restart_balatrobot(args, root, env, serve_process)
            if error:
                return completed, error, serve_process

        print(f"\n--- GAME {game_index}/{args.games_per_iter} ---")
        before_files = _run_files(args.out_dir)
        rc = subprocess.run(_agent_command(args, state_path), cwd=root, env=env).returncode
        new_files = _run_files(args.out_dir) - before_files
        if rc != 0 or not new_files:
            if args.auto_restart_game:
                serve_process, restart_error = _restart_balatrobot(args, root, env, serve_process)
                if not restart_error:
                    before_files = _run_files(args.out_dir)
                    rc = subprocess.run(_agent_command(args, state_path), cwd=root, env=env).returncode
                    new_files = _run_files(args.out_dir) - before_files
            if rc != 0 or not new_files:
                return completed, f"game {game_index} produced no run record (exit={rc})", serve_process
        latest = max(new_files, key=lambda p: p.stat().st_mtime)
        last_won = bool(_read_run_json(latest).get("won"))
        completed += 1
    return completed, "", serve_process


def _agent_command(args: argparse.Namespace, state_path: Path) -> List[str]:
    cmd = [
        sys.executable, "-m", "v1_4.agent", "--games", "1",
        "--model", args.model, "--provider", args.provider,
        "--out-dir", args.out_dir, "--state-file", str(state_path),
        "--decision-format", args.decision_format,
        "--host", args.balatrobot_host, "--port", str(args.balatrobot_port),
    ]
    if args.think:
        cmd.extend(["--think", "--reasoning-effort", args.reasoning_effort])
        if args.thinking_budget > 0:
            cmd.extend(["--thinking-budget", str(args.thinking_budget)])
    else:
        cmd.append("--no-think")
    if args.llm_log_io:
        cmd.append("--llm-log-io")
    return cmd


def _balatrobot_healthy(host: str, port: int, timeout: float = 2.0) -> bool:
    payload = json.dumps({"jsonrpc": "2.0", "method": "health", "params": {}, "id": 1}).encode("utf-8")
    request = urllib.request.Request(
        f"http://{host}:{port}", data=payload, headers={"Content-Type": "application/json"}, method="POST"
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            data = json.loads(response.read().decode("utf-8"))
        return (data.get("result") or {}).get("status") == "ok"
    except Exception:
        return False


def _restart_balatrobot(
    args: argparse.Namespace,
    root: Path,
    env: Dict[str, str],
    previous: Optional[subprocess.Popen[Any]],
) -> tuple[Optional[subprocess.Popen[Any]], str]:
    if previous and previous.poll() is None:
        previous.terminate()
        try:
            previous.wait(timeout=5)
        except subprocess.TimeoutExpired:
            previous.kill()
    command = _balatrobot_serve_command(args)
    if not command:
        return None, "no BalatroBot restart command is available for this platform"
    log_dir = Path(args.out_dir) / "balatrobot_logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / f"restart_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
    log_file = log_path.open("a", encoding="utf-8")
    try:
        process = subprocess.Popen(command, cwd=root, env=env, stdout=log_file, stderr=subprocess.STDOUT)
    except Exception as e:
        log_file.close()
        return None, f"failed to start BalatroBot: {e}"
    finally:
        if not log_file.closed:
            log_file.close()
    deadline = time.time() + args.balatrobot_health_timeout
    while time.time() < deadline:
        if _balatrobot_healthy(args.balatrobot_host, args.balatrobot_port):
            print(f"BalatroBot restarted; log={log_path}")
            return process, ""
        if process.poll() is not None:
            return process, f"BalatroBot restart exited early; see {log_path}"
        time.sleep(0.5)
    return process, f"BalatroBot health timeout after restart; see {log_path}"


def _stop_managed_serve(process: Optional[subprocess.Popen[Any]]) -> None:
    if not process or process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()


def _balatrobot_serve_command(args: argparse.Namespace) -> List[str]:
    if args.balatrobot_serve_command:
        return shlex.split(args.balatrobot_serve_command)
    system = platform.system()
    if system == "Darwin":
        home = Path.home()
        mod = home / "Library/Application Support/Balatro/Mods/balatrobot"
        game = home / "Library/Application Support/Steam/steamapps/common/Balatro"
        return [
            "uvx", "--from", str(mod), "balatrobot", "serve",
            "--host", args.balatrobot_host, "--port", str(args.balatrobot_port),
            "--platform", "darwin", "--love-path", str(game / "run_lovely_macos.sh"),
            "--lovely-path", str(game / "liblovely.dylib"), "--fast",
        ]
    if system == "Windows":
        appdata = os.getenv("APPDATA", "")
        if appdata:
            return ["uvx", "--from", str(Path(appdata) / "Balatro/Mods/balatrobot"), "balatrobot", "serve", "--fast"]
    return []


def _run_files(out_dir: str | Path) -> set[Path]:
    return set((Path(out_dir) / "runs").glob("*.json"))


def _read_run_json(path: Path) -> Dict[str, Any]:
    try:
        return (json.loads(path.read_text(encoding="utf-8-sig")).get("result") or {})
    except Exception:
        return {}


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


def _provider_api_key(args: argparse.Namespace) -> str:
    if args.provider == "qwen":
        return args.qwen_api_key
    if args.provider == "visioncoder":
        return args.visioncoder_api_key
    return args.deepseek_api_key


def _provider_key_name(provider: str) -> str:
    if provider == "qwen":
        return "QWEN_API_KEY or DASHSCOPE_API_KEY"
    if provider == "visioncoder":
        return "VISIONCODER_API_KEY"
    return "DEEPSEEK_API_KEY"


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
