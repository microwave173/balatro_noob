import argparse
import json
import sys
from pathlib import Path

if __package__ is None or __package__ == "":
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from v1_2.core.deepseek_policy import _decision_user, _strict_schema
from v1_2.core.observation import render_observation_text
from v1_2.core.prompts import (
    COMPACT_FORMAT_GUIDE,
    GAME_PRIMER,
    MASTER_IDENTITY,
    PLAY_DECISION_SCHEMA,
    STRATEGY_TIPS,
)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Dump the exact single-input prompt text for a v1.2 play decision.")
    p.add_argument("--input", default="v1_2/test_inputs/play_decision_ante1_pair.json")
    p.add_argument("--output", default="v1_2/test_inputs/play_decision_ante1_pair_full_prompt.txt")
    p.add_argument("--model", default="deepseek-v4-flash")
    p.add_argument("--max-tokens", type=int, default=360)
    p.add_argument("--temperature", type=float, default=0.0)
    return p.parse_args()


def main() -> None:
    args = parse_args()
    root = Path(__file__).resolve().parents[2]
    in_path = Path(args.input)
    if not in_path.is_absolute():
        in_path = root / in_path
    out_path = Path(args.output)
    if not out_path.is_absolute():
        out_path = root / out_path

    data = json.loads(in_path.read_text(encoding="utf-8-sig"))
    # These fields are for human review only, not for the real model call.
    data.pop("human_hint_not_for_model_later", None)
    observation = render_observation_text(data)

    system_text = MASTER_IDENTITY + "\n\n" + GAME_PRIMER + "\n\n" + STRATEGY_TIPS + "\n\n" + COMPACT_FORMAT_GUIDE
    user_text = _decision_user(
        "PLAY",
        "Choose the best play, discard, or inspect_deck action.",
        observation,
        PLAY_DECISION_SCHEMA,
    )
    request_summary = {
        "model": args.model,
        "temperature": args.temperature,
        "max_tokens": args.max_tokens,
        "response_format": {"type": "json_object"},
        "reasoning": {"enabled": False},
        "enable_thinking": False,
        "api_key": "<not included>",
    }

    body = [
        "# REQUEST PARAMS",
        json.dumps(request_summary, ensure_ascii=False, indent=2),
        "",
        "# SYSTEM MESSAGE",
        system_text,
        "",
        "# USER MESSAGE",
        user_text,
        "",
    ]
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(body), encoding="utf-8")
    print(out_path)


if __name__ == "__main__":
    main()
