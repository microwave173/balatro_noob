import json
import os
import subprocess
import sys
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path

from PIL import ImageGrab


OLLAMA_URL = os.getenv("OLLAMA_URL", "http://127.0.0.1:11434/api/chat")
MODEL = os.getenv("OLLAMA_MODEL", "gemma4:e2b-it-q4_K_M")
THINK = os.getenv("OLLAMA_THINK", "false").lower() == "true"

OPTIONS = {
    "num_gpu": int(os.getenv("OLLAMA_NUM_GPU", "999")),
    "num_ctx": int(os.getenv("OLLAMA_NUM_CTX", "2048")),
    "num_batch": int(os.getenv("OLLAMA_NUM_BATCH", "512")),
    "num_thread": int(os.getenv("OLLAMA_NUM_THREAD", "8")),
}

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
                        "description": "Optional file name, e.g. shot1.png",
                    }
                },
                "required": [],
            },
        },
    },
]

ALLOWED_COMMANDS = {
    "Get-Date -Format o",
    "Get-Location",
    "whoami",
    "Get-ChildItem",
}

SCREENSHOT_DIR = Path("screenshots")
MAX_TOOL_TURNS = 8


def call_model(messages):
    payload = {
        "model": MODEL,
        "messages": messages,
        "tools": TOOLS,
        "options": OPTIONS,
        "think": THINK,
        "stream": False,
    }
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        OLLAMA_URL,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=300) as resp:
        return json.loads(resp.read().decode("utf-8"))


def run_cli(command):
    if command not in ALLOWED_COMMANDS:
        return (
            f"[blocked] command not allowed: {command!r}. "
            f"Allowed: {sorted(ALLOWED_COMMANDS)}"
        )

    proc = subprocess.run(
        ["powershell", "-NoProfile", "-Command", command],
        capture_output=True,
        text=True,
        timeout=30,
    )
    output = (proc.stdout + proc.stderr).strip()
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
        return str(out_path)
    except Exception as e:
        return f"[error] failed to capture screenshot: {e}"


def handle_tool_call(tc):
    fn = tc["function"]["name"]
    args = tc["function"].get("arguments", {})

    if fn == "run_cli":
        return fn, run_cli(args.get("command", ""))
    if fn == "take_screenshot":
        return fn, take_screenshot(args.get("filename", ""))
    return fn, f"[error] unknown tool: {fn}"


def agent_reply(messages):
    """
    Execute one assistant turn including any required tool loops.
    Returns final assistant text.
    """
    for _ in range(MAX_TOOL_TURNS):
        result = call_model(messages)
        assistant_msg = result["message"]
        messages.append(assistant_msg)

        tool_calls = assistant_msg.get("tool_calls") or []
        if not tool_calls:
            return assistant_msg.get("content", "").strip()

        for tc in tool_calls:
            fn, tool_output = handle_tool_call(tc)
            print(f"[tool] {fn} -> {tool_output}")
            messages.append(
                {
                    "role": "tool",
                    "tool_name": fn,
                    "tool_call_id": tc.get("id"),
                    "content": tool_output,
                }
            )

    return "[error] exceeded max tool loop turns."


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    print(f"Model: {MODEL}")
    print(f"URL: {OLLAMA_URL}")
    print(f"Think: {THINK}")
    print(f"Options: {OPTIONS}")
    print("Agent ready. Type message, /clear to reset, /exit to quit.")

    messages = [
        {
            "role": "system",
            "content": (
                "You are a local assistant with tool access. "
                "If the user asks to run a command or take a screenshot, you must call the appropriate tool. "
                "After receiving tool results, always return a non-empty final answer that summarizes the result. "
                "Be concise and factual."
            ),
        }
    ]

    while True:
        user_input = input("You: ").strip()
        if not user_input:
            continue
        if user_input.lower() in {"/exit", "exit", "quit"}:
            print("Bye.")
            break
        if user_input.lower() == "/clear":
            messages = [messages[0]]
            print("History cleared.")
            continue

        messages.append({"role": "user", "content": user_input})
        try:
            answer = agent_reply(messages)
            print(f"AI: {answer}\n")
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", errors="replace")
            print(f"[HTTP Error] {e.code}: {detail}")
        except urllib.error.URLError as e:
            print(f"[Network Error] {e}")
        except Exception as e:
            print(f"[Error] {e}")


if __name__ == "__main__":
    main()
