import json
import subprocess
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path

from PIL import ImageGrab


OLLAMA_URL = "http://127.0.0.1:11434/api/chat"
MODEL = "gemma4:e2b-it-q4_K_M"


TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "run_cli",
            "description": "Run a safe PowerShell command and return output",
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {
                        "type": "string",
                        "description": "PowerShell command to run",
                    }
                },
                "required": ["command"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "take_screenshot",
            "description": "Capture a full-screen screenshot and save it to disk",
            "parameters": {
                "type": "object",
                "properties": {
                    "filename": {
                        "type": "string",
                        "description": "Optional filename, e.g. shot1.png",
                    }
                },
                "required": [],
            },
        },
    },
]

# Keep this very strict for safety.
ALLOWED_COMMANDS = {
    "Get-Date -Format o",
    "Get-Location",
    "whoami",
}

SCREENSHOT_DIR = Path("screenshots")


def call_model(messages):
    payload = {
        "model": MODEL,
        "messages": messages,
        "tools": TOOLS,
        "think": False,
        "stream": False,
    }
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        OLLAMA_URL,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=120) as resp:
        return json.loads(resp.read().decode("utf-8"))


def run_cli(command):
    if command not in ALLOWED_COMMANDS:
        return (
            f"[blocked] command not allowed: {command!r}. "
            f"Allowed: {sorted(ALLOWED_COMMANDS)}"
        )

    p = subprocess.run(
        ["powershell", "-NoProfile", "-Command", command],
        capture_output=True,
        text=True,
        timeout=20,
    )
    output = (p.stdout + p.stderr).strip()
    return output or "[empty output]"


def take_screenshot(filename=""):
    SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)

    if filename:
        safe_name = Path(filename).name
        if not safe_name.lower().endswith(".png"):
            safe_name += ".png"
    else:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        safe_name = f"screenshot_{ts}.png"

    out_path = (SCREENSHOT_DIR / safe_name).resolve()
    try:
        image = ImageGrab.grab(all_screens=True)
        image.save(out_path, format="PNG")
    except Exception as e:
        return f"[error] failed to capture screenshot: {e}"

    return str(out_path)


def main():
    # Prompt intentionally encourages tool use.
    messages = [
        {
            "role": "user",
            "content": (
                "请调用三次工具："
                "1) run_cli 执行 `Get-Date -Format o`；"
                "2) run_cli 执行 `Get-Location`；"
                "3) take_screenshot 保存为 `demo_shot.png`。"
                "最后用三行中文总结结果。"
            ),
        }
    ]

    max_turns = 8
    for _ in range(max_turns):
        result = call_model(messages)
        assistant_msg = result["message"]
        messages.append(assistant_msg)

        tool_calls = assistant_msg.get("tool_calls") or []
        if not tool_calls:
            print("Final answer:")
            print(assistant_msg.get("content", "").strip())
            return

        for tc in tool_calls:
            fn = tc["function"]["name"]
            args = tc["function"].get("arguments", {})
            if fn == "run_cli":
                tool_output = run_cli(args.get("command", ""))
            elif fn == "take_screenshot":
                tool_output = take_screenshot(args.get("filename", ""))
            else:
                tool_output = f"[error] unknown tool: {fn}"

            print(f"Tool call -> {fn}({args})")
            print(f"Tool result -> {tool_output}\n")

            messages.append(
                {
                    "role": "tool",
                    "tool_name": fn,
                    "tool_call_id": tc.get("id"),
                    "content": tool_output,
                }
            )

    print("Stopped: exceeded max tool-call turns.")


if __name__ == "__main__":
    try:
        main()
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", errors="replace")
        print(f"[HTTP Error] {e.code}: {detail}")
    except urllib.error.URLError as e:
        print(f"[Network Error] {e}")
