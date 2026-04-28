import argparse
import json
import os
from pathlib import Path

from openai import OpenAI


def parse_args():
    p = argparse.ArgumentParser(description="Send one TXT prompt directly to DeepSeek with OpenAI SDK.")
    p.add_argument("--input", default="v1_4/test_inputs/play_decision_ante1_pair_full_prompt.txt")
    p.add_argument("--model", default=os.getenv("DEEPSEEK_MODEL", "deepseek-v4-pro"))
    p.add_argument("--base-url", default=os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com"))
    p.add_argument("--api-key", default=os.getenv("DEEPSEEK_API_KEY", ""))
    p.add_argument("--max-tokens", type=int, default=360)
    p.add_argument("--temperature", type=float, default=0.0)
    p.add_argument("--debug", action="store_true")
    p.add_argument("--disable-thinking", action="store_true")
    return p.parse_args()


def main():
    args = parse_args()
    if not args.api_key:
        raise SystemExit("DEEPSEEK_API_KEY is empty")

    prompt = Path(args.input).read_text(encoding="utf-8-sig")
    client = OpenAI(api_key=args.api_key, base_url=args.base_url)
    kwargs = {}
    if args.disable_thinking:
        kwargs["extra_body"] = {
            "thinking": {"type": "disabled"},
        }
    response = client.chat.completions.create(
        model=args.model,
        messages=[{"role": "user", "content": prompt}],
        temperature=args.temperature,
        max_tokens=args.max_tokens,
        response_format={"type": "json_object"},
        **kwargs,
    )

    message = response.choices[0].message
    content = message.content or ""
    if args.debug:
        print("MESSAGE_DEBUG")
        try:
            print(message.model_dump_json(indent=2))
        except Exception:
            print(message)
        print("CONTENT")
    try:
        print(json.dumps(json.loads(content), ensure_ascii=False, indent=2))
    except Exception:
        print(content)


if __name__ == "__main__":
    main()

