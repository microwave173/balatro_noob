import json
import os
import sys
import urllib.error
import urllib.request


OLLAMA_URL = os.getenv("OLLAMA_URL", "http://127.0.0.1:11434/api/chat")
MODEL = os.getenv("OLLAMA_MODEL", "gemma4:e2b-it-q4_K_M")
THINK = os.getenv("OLLAMA_THINK", "false").lower() == "true"

# GPU-first settings for local speed tuning.
# num_gpu=999 means "offload as many layers as possible".
OPTIONS = {
    "num_gpu": int(os.getenv("OLLAMA_NUM_GPU", "999")),
    "num_ctx": int(os.getenv("OLLAMA_NUM_CTX", "2048")),
    "num_batch": int(os.getenv("OLLAMA_NUM_BATCH", "512")),
    "num_thread": int(os.getenv("OLLAMA_NUM_THREAD", "8")),
}


def stream_chat(messages):
    payload = {
        "model": MODEL,
        "messages": messages,
        "options": OPTIONS,
        "stream": True,
        "think": THINK,
    }
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        OLLAMA_URL,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    full_text = []
    with urllib.request.urlopen(req, timeout=300) as resp:
        for raw_line in resp:
            line = raw_line.decode("utf-8").strip()
            if not line:
                continue

            event = json.loads(line)
            delta = event.get("message", {}).get("content", "")
            if delta:
                print(delta, end="", flush=True)
                full_text.append(delta)

            if event.get("done"):
                break

    print()
    sys.stdout.flush()
    return "".join(full_text)


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    print(f"Model: {MODEL}")
    print(f"Options: {OPTIONS}")
    print(f"Think: {THINK}")
    print("Type to chat. /exit to quit, /clear to reset history.")

    messages = []
    while True:
        user_input = input("You: ").strip()
        if not user_input:
            continue
        if user_input.lower() in {"/exit", "exit", "quit"}:
            print("Bye.")
            break
        if user_input.lower() == "/clear":
            messages = []
            print("History cleared.")
            continue

        messages.append({"role": "user", "content": user_input})
        try:
            print("AI: ", end="", flush=True)
            assistant_reply = stream_chat(messages)
        except urllib.error.URLError as e:
            print(f"[Network Error] {e}")
            continue
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", errors="replace")
            print(f"[HTTP Error] {e.code}: {detail}")
            continue
        except (KeyError, json.JSONDecodeError) as e:
            print(f"[Parse Error] {e}")
            continue

        print()
        messages.append({"role": "assistant", "content": assistant_reply})


if __name__ == "__main__":
    main()
