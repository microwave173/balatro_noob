import json
import os
import sys
from pathlib import Path

from openai import OpenAI

if __package__ is None or __package__ == "":
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from v1_3.core.deepseek_policy import _extract_json, _load_reference_guide
from v1_3.core.prompts import GAME_PRIMER, MASTER_IDENTITY, PLAY_DECISION_SCHEMA, STRATEGY_TIPS


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    api_key = os.getenv("DEEPSEEK_API_KEY", "")
    if not api_key:
        print("[fatal] DEEPSEEK_API_KEY is empty")
        return
    runs = sorted(Path("v1_3/out_probe2/runs").glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not runs:
        print("[fatal] no v1_3/out_probe2 run found")
        return
    data = json.loads(runs[0].read_text(encoding="utf-8"))
    obs = ""
    for event in data.get("result", {}).get("events", []):
        if event.get("stage") == "PLAY":
            obs = ((event.get("observation") or {}).get("compact")) or ""
            if obs:
                break
    if not obs:
        print("[fatal] no PLAY observation found")
        return

    system = "\n\n".join(
        [
            MASTER_IDENTITY.replace("Use the required tool call for decisions.", "Use JSON output for this probe."),
            GAME_PRIMER,
            STRATEGY_TIPS,
            _load_reference_guide(),
            "Return exactly one JSON object and no prose outside JSON. Required keys: action, target, cards, phase_plan, reason, commentary.",
        ]
    )
    user = (
        "Current stage: PLAY\n\n"
        "Task: choose the best play, discard, use, or inspect_deck action.\n\n"
        "Information you can see:\n"
        f"{obs}\n\n"
        "Return exactly one JSON object. Do not use markdown. Do not add prose before or after the JSON.\n\n"
        f"{PLAY_DECISION_SCHEMA.replace('Tool arguments:', 'JSON arguments:')}"
    )
    client = OpenAI(api_key=api_key, base_url="https://api.deepseek.com", timeout=90)
    for max_tokens in (700, 1800):
        ok = 0
        print(f"CASE max_tokens={max_tokens}")
        for i in range(1, 6):
            response = client.chat.completions.create(
                model="deepseek-v4-pro",
                messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
                max_tokens=max_tokens,
                extra_body={"thinking": {"type": "enabled"}},
            )
            message = response.choices[0].message
            raw = (message.content or "").strip()
            parsed = _extract_json(raw)
            valid = (
                isinstance(parsed, dict)
                and parsed.get("action") in {"play", "discard", "use", "inspect_deck"}
                and isinstance(parsed.get("cards"), list)
            )
            ok += int(valid)
            print(
                json.dumps(
                    {
                        "trial": i,
                        "finish_reason": response.choices[0].finish_reason,
                        "reasoning_len": len(getattr(message, "reasoning_content", "") or ""),
                        "valid": valid,
                        "action": parsed.get("action") if isinstance(parsed, dict) else None,
                        "raw_prefix": raw[:100],
                    },
                    ensure_ascii=False,
                )
            )
        print(f"OK {ok}/5")


if __name__ == "__main__":
    main()
