import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, Optional

from openai import OpenAI

if __package__ is None or __package__ == "":
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from v1_3.core.deepseek_policy import _extract_json, _load_reference_guide
from v1_3.core.effect_catalog import EffectCatalog
from v1_3.core.observation import build_observation
from v1_3.core.prompts import GAME_PRIMER, MASTER_IDENTITY, PLAY_DECISION_SCHEMA, STRATEGY_TIPS
from v1_3.core.rpc import JsonRpcClient


JSON_FORMAT_GUIDE = """You will receive current visible Balatro game information.
Return exactly one JSON object and no prose outside JSON.
The JSON object must match this schema:
{
  "action": "play|discard|use|inspect_deck",
  "target": "consumable0|null",
  "cards": [0,1],
  "phase_plan": "optional short plan update",
  "reason": "a few concise sentences",
  "commentary": "1 short sentence for the human operator"
}
Use zero-based hand indexes exactly as shown. If you calculate an exact expected score, make it as accurate as possible; if estimating, keep the estimate close.
"""


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Probe DeepSeek v4 pro thinking JSON output reliability without taking game actions.")
    p.add_argument("--host", default=os.getenv("BALATROBOT_HOST", "127.0.0.1"))
    p.add_argument("--port", type=int, default=int(os.getenv("BALATROBOT_PORT", "12346")))
    p.add_argument("--model", default="deepseek-v4-pro")
    p.add_argument("--api-key", default=os.getenv("DEEPSEEK_API_KEY", ""))
    p.add_argument("--base-url", default=os.getenv("DEEPSEEK_BASE_URL", os.getenv("DEEPSEEK_URL", "https://api.deepseek.com")))
    p.add_argument("--trials", type=int, default=5)
    p.add_argument("--max-tokens", type=int, default=700)
    p.add_argument("--out", default="v1_3/out/deepseek_json_thinking_probe.json")
    p.add_argument("--include-reasoning-effort", choices=["", "low", "medium", "high"], default="", help="Default empty means do not send reasoning_effort.")
    return p.parse_args()


def main() -> None:
    args = parse_args()
    if not args.api_key:
        print("[fatal] DEEPSEEK_API_KEY is empty")
        return

    rpc = JsonRpcClient(args.host, args.port, timeout=20)
    state = rpc.call("gamestate", retries=1)
    catalog = EffectCatalog(None)
    obs = build_observation(
        state,
        catalog,
        phase="PLAY",
        run_plan="Probe only; do not execute actions.",
        phase_plan="Choose the best legal PLAY action as JSON.",
        long_term_context={},
    )

    system_text = "\n\n".join(
        [
            MASTER_IDENTITY.replace("Use the required tool call for decisions.", "Use JSON output for this probe."),
            GAME_PRIMER,
            STRATEGY_TIPS,
            _load_reference_guide(),
            JSON_FORMAT_GUIDE,
        ]
    )
    user_text = (
        "Current stage: PLAY\n\n"
        "Task: choose the best play, discard, use, or inspect_deck action.\n\n"
        "Information you can see:\n"
        f"{obs['compact']}\n\n"
        "Return exactly one JSON object. Do not use markdown. Do not add prose before or after the JSON.\n\n"
        f"{PLAY_DECISION_SCHEMA.replace('Tool arguments:', 'JSON arguments:')}"
    )

    client = OpenAI(api_key=args.api_key, base_url=args.base_url.rstrip("/"), timeout=90)
    results = []
    for i in range(1, args.trials + 1):
        request: Dict[str, Any] = {
            "model": args.model,
            "messages": [
                {"role": "system", "content": system_text},
                {"role": "user", "content": user_text},
            ],
            "max_tokens": args.max_tokens,
            "extra_body": {"thinking": {"type": "enabled"}},
        }
        if args.include_reasoning_effort:
            request["reasoning_effort"] = args.include_reasoning_effort
        result = _run_trial(client, request)
        result["trial"] = i
        results.append(result)
        print(json.dumps(_compact_result(result), ensure_ascii=False))

    summary = {
        "model": args.model,
        "thinking": True,
        "reasoning_effort_sent": args.include_reasoning_effort or None,
        "trials": args.trials,
        "valid_json": sum(1 for r in results if r.get("valid_json")),
        "valid_action_json": sum(1 for r in results if r.get("valid_action_json")),
        "results": results,
        "prompt_snapshot": {
            "system_chars": len(system_text),
            "user_chars": len(user_text),
            "observation": obs["compact"],
        },
    }
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"SUMMARY valid_json={summary['valid_json']}/{args.trials} valid_action_json={summary['valid_action_json']}/{args.trials} out={out_path}")


def _run_trial(client: OpenAI, request: Dict[str, Any]) -> Dict[str, Any]:
    try:
        response = client.chat.completions.create(**request)
        message = response.choices[0].message
        raw = (message.content or "").strip()
        parsed = _extract_json(raw)
        return {
            "ok": True,
            "finish_reason": response.choices[0].finish_reason,
            "raw": raw[:4000],
            "reasoning_content_len": len(getattr(message, "reasoning_content", "") or ""),
            "valid_json": isinstance(parsed, dict),
            "valid_action_json": _is_valid_action_json(parsed),
            "parsed": parsed,
        }
    except Exception as e:
        return {
            "ok": False,
            "error_type": type(e).__name__,
            "error": str(e)[:1000],
            "valid_json": False,
            "valid_action_json": False,
        }


def _is_valid_action_json(obj: Optional[Dict[str, Any]]) -> bool:
    if not isinstance(obj, dict):
        return False
    action = str(obj.get("action") or "")
    if action not in {"play", "discard", "use", "inspect_deck"}:
        return False
    if "cards" not in obj or not isinstance(obj.get("cards"), list):
        return False
    if not isinstance(obj.get("reason"), str) or not obj.get("reason"):
        return False
    if not isinstance(obj.get("commentary"), str) or not obj.get("commentary"):
        return False
    return True


def _compact_result(result: Dict[str, Any]) -> Dict[str, Any]:
    parsed = result.get("parsed") if isinstance(result.get("parsed"), dict) else {}
    return {
        "trial": result.get("trial"),
        "ok": result.get("ok"),
        "finish_reason": result.get("finish_reason"),
        "reasoning_content_len": result.get("reasoning_content_len"),
        "valid_json": result.get("valid_json"),
        "valid_action_json": result.get("valid_action_json"),
        "action": parsed.get("action"),
        "cards": parsed.get("cards"),
        "error": result.get("error"),
        "raw_prefix": str(result.get("raw") or "")[:160],
    }


if __name__ == "__main__":
    main()
