import argparse
import json
import os
import statistics
import time
import urllib.error
import urllib.request


OLLAMA_URL = os.getenv("OLLAMA_URL", "http://127.0.0.1:11434/api/chat")
MODEL = os.getenv("OLLAMA_MODEL", "gemma4:e2b-it-q4_K_M")

# Keep runtime settings aligned with your current high-GPU setup.
OPTIONS = {
    "num_gpu": int(os.getenv("OLLAMA_NUM_GPU", "999")),
    "num_ctx": int(os.getenv("OLLAMA_NUM_CTX", "2048")),
    "num_batch": int(os.getenv("OLLAMA_NUM_BATCH", "512")),
    "num_thread": int(os.getenv("OLLAMA_NUM_THREAD", "8")),
}

# Fixed preload history used as baseline context.
BASE_HISTORY = [
    {"role": "user", "content": "One sentence: who are you?"},
    {
        "role": "assistant",
        "content": "I am a large language model developed by Google DeepMind.",
    },
    {"role": "user", "content": "One sentence: what is 234*57?"},
    {"role": "assistant", "content": "234 times 57 equals 13338."},
    {
        "role": "user",
        "content": "One sentence: in transformers with MoE, which subnetwork changes most?",
    },
    {
        "role": "assistant",
        "content": "MoE mainly changes the feed-forward network (FFN) block.",
    },
    {
        "role": "user",
        "content": "Continue with one sentence and give only the core conclusion.",
    },
    {"role": "assistant", "content": "Understood, I will keep it to one concise sentence."},
]

# Similar-length prompts, different cognitive difficulty.
EASY_PROMPT = "Only output the number: 23+48=? No explanation."
HARD_PROMPT = "Only output the number: 9th prime=? No explanation."


def build_history(repeat_times):
    if repeat_times <= 1:
        return list(BASE_HISTORY)
    return BASE_HISTORY * repeat_times


def stream_measure(messages):
    payload = {
        "model": MODEL,
        "messages": messages,
        "options": OPTIONS,
        "stream": True,
    }
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        OLLAMA_URL,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    t0 = time.perf_counter()
    first_token_ms = None
    chunks = []

    with urllib.request.urlopen(req, timeout=300) as resp:
        for raw_line in resp:
            line = raw_line.decode("utf-8").strip()
            if not line:
                continue

            event = json.loads(line)
            delta = event.get("message", {}).get("content", "")
            if delta:
                now = time.perf_counter()
                if first_token_ms is None:
                    first_token_ms = (now - t0) * 1000
                chunks.append(delta)

            if event.get("done"):
                break

    total_ms = (time.perf_counter() - t0) * 1000
    if first_token_ms is None:
        first_token_ms = total_ms

    return first_token_ms, total_ms, "".join(chunks)


def summarize(name, values):
    mean = statistics.mean(values)
    p50 = statistics.median(values)
    p90 = statistics.quantiles(values, n=10)[8] if len(values) >= 10 else max(values)
    print(
        f"{name}: mean={mean:.1f}ms, p50={p50:.1f}ms, p90={p90:.1f}ms, "
        f"min={min(values):.1f}ms, max={max(values):.1f}ms"
    )


def run_case(round_index, case_name, history_repeat, question):
    history = build_history(history_repeat)
    messages = history + [{"role": "user", "content": question}]

    ttft_ms, total_ms, answer = stream_measure(messages)
    print(
        f"[round {round_index} {case_name}] repeat={history_repeat} "
        f"ttft={ttft_ms:.1f}ms total={total_ms:.1f}ms answer={answer.strip()!r}"
    )
    return ttft_ms, total_ms, answer.strip()


def warmup(times):
    if times <= 0:
        return

    print(f"Warmup calls: {times}")
    for i in range(1, times + 1):
        messages = build_history(1) + [{"role": "user", "content": "Only output OK."}]
        ttft_ms, total_ms, answer = stream_measure(messages)
        print(
            f"[warmup #{i}] ttft={ttft_ms:.1f}ms total={total_ms:.1f}ms "
            f"answer={answer.strip()!r}"
        )
    print("-" * 72)


def main():
    parser = argparse.ArgumentParser(
        description="Compare first-token latency with same history and long-prefill variant."
    )
    parser.add_argument(
        "--rounds",
        type=int,
        default=6,
        help="Rounds (each round runs easy, hard, and long-prefill)",
    )
    parser.add_argument("--warmup", type=int, default=1, help="Warmup calls before measuring")
    parser.add_argument(
        "--long-repeat",
        type=int,
        default=4,
        help="How many times to repeat the preload history for long-prefill case",
    )
    args = parser.parse_args()

    cases = [
        ("easy", 1, EASY_PROMPT),
        ("hard", 1, HARD_PROMPT),
        ("easy_longprefill", args.long_repeat, EASY_PROMPT),
    ]

    print(f"Model: {MODEL}")
    print(f"URL:   {OLLAMA_URL}")
    print(f"Options: {OPTIONS}")
    print(f"Base history turns: {len(BASE_HISTORY)}")
    print(f"Easy prompt len(chars): {len(EASY_PROMPT)}")
    print(f"Hard prompt len(chars): {len(HARD_PROMPT)}")
    print(f"Long prefill repeat: {args.long_repeat}")

    warmup(args.warmup)

    stats = {
        "easy": {"ttft": [], "total": [], "answers": []},
        "hard": {"ttft": [], "total": [], "answers": []},
        "easy_longprefill": {"ttft": [], "total": [], "answers": []},
    }

    # Interleave all cases each round to reduce drift bias.
    for r in range(1, args.rounds + 1):
        for case_name, repeat_count, question in cases:
            ttft_ms, total_ms, answer = run_case(r, case_name, repeat_count, question)
            stats[case_name]["ttft"].append(ttft_ms)
            stats[case_name]["total"].append(total_ms)
            stats[case_name]["answers"].append(answer)

    print("-" * 72)

    summarize("TTFT easy", stats["easy"]["ttft"])
    summarize("TTFT hard", stats["hard"]["ttft"])
    summarize("TTFT easy_longprefill", stats["easy_longprefill"]["ttft"])
    summarize("TOTAL easy", stats["easy"]["total"])
    summarize("TOTAL hard", stats["hard"]["total"])
    summarize("TOTAL easy_longprefill", stats["easy_longprefill"]["total"])

    d_hard_easy = statistics.mean(stats["hard"]["ttft"]) - statistics.mean(stats["easy"]["ttft"])
    d_long_easy = (
        statistics.mean(stats["easy_longprefill"]["ttft"])
        - statistics.mean(stats["easy"]["ttft"])
    )

    print(f"Delta TTFT (hard - easy): {d_hard_easy:.1f}ms")
    print(f"Delta TTFT (easy_longprefill - easy): {d_long_easy:.1f}ms")

    print("Sample answers:")
    print(f"easy -> {stats['easy']['answers'][0]!r}")
    print(f"hard -> {stats['hard']['answers'][0]!r}")
    print(f"easy_longprefill -> {stats['easy_longprefill']['answers'][0]!r}")


if __name__ == "__main__":
    try:
        main()
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", errors="replace")
        print(f"[HTTP Error] {e.code}: {detail}")
        raise
    except urllib.error.URLError as e:
        print(f"[Network Error] {e}")
        raise
