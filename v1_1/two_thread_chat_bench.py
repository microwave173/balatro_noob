import argparse
import json
import statistics
import threading
import time
import urllib.request


URL = "http://127.0.0.1:11434/api/chat"
MODEL = "gemma4:e2b-it-q4_K_M"
OPTIONS = {"num_gpu": 999, "num_ctx": 2048, "num_batch": 512, "num_thread": 8}

PROMPT_A = "请只输出A，不要解释。"
PROMPT_B = "请只输出B，不要解释。"


def run_one(prompt):
    payload = {
        "model": MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "options": OPTIONS,
        "think": False,
        "stream": True,
    }
    req = urllib.request.Request(
        URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    t0 = time.perf_counter()
    first_ms = None
    out = []
    with urllib.request.urlopen(req, timeout=300) as resp:
        for raw in resp:
            line = raw.decode("utf-8").strip()
            if not line:
                continue
            ev = json.loads(line)
            c = ev.get("message", {}).get("content", "")
            if c:
                if first_ms is None:
                    first_ms = (time.perf_counter() - t0) * 1000
                out.append(c)
            if ev.get("done"):
                break

    total_ms = (time.perf_counter() - t0) * 1000
    if first_ms is None:
        first_ms = total_ms
    return {"ttft_ms": first_ms, "total_ms": total_ms, "text": "".join(out).strip()}


def run_sequential():
    t0 = time.perf_counter()
    r1 = run_one(PROMPT_A)
    r2 = run_one(PROMPT_B)
    wall_ms = (time.perf_counter() - t0) * 1000
    return {"wall_ms": wall_ms, "r1": r1, "r2": r2}


def run_concurrent():
    start_barrier = threading.Barrier(3)
    results = {}
    lock = threading.Lock()

    def worker(name, prompt):
        start_barrier.wait()
        r = run_one(prompt)
        with lock:
            results[name] = r

    t1 = threading.Thread(target=worker, args=("r1", PROMPT_A))
    t2 = threading.Thread(target=worker, args=("r2", PROMPT_B))
    t1.start()
    t2.start()
    t0 = time.perf_counter()
    start_barrier.wait()
    t1.join()
    t2.join()
    wall_ms = (time.perf_counter() - t0) * 1000
    return {"wall_ms": wall_ms, "r1": results["r1"], "r2": results["r2"]}


def mean(values):
    return statistics.mean(values) if values else 0.0


def summarize(label, runs):
    wall = [x["wall_ms"] for x in runs]
    r1_ttft = [x["r1"]["ttft_ms"] for x in runs]
    r2_ttft = [x["r2"]["ttft_ms"] for x in runs]
    r1_total = [x["r1"]["total_ms"] for x in runs]
    r2_total = [x["r2"]["total_ms"] for x in runs]
    print(
        f"{label}: wall_mean={mean(wall):.1f}ms, "
        f"req1_ttft_mean={mean(r1_ttft):.1f}ms, req2_ttft_mean={mean(r2_ttft):.1f}ms, "
        f"req1_total_mean={mean(r1_total):.1f}ms, req2_total_mean={mean(r2_total):.1f}ms"
    )


def main():
    parser = argparse.ArgumentParser(description="Benchmark sequential vs 2-thread concurrent chat.")
    parser.add_argument("--rounds", type=int, default=5, help="number of rounds")
    parser.add_argument("--warmup", type=int, default=1, help="warmup single calls")
    args = parser.parse_args()

    print(f"model={MODEL}")
    print(f"options={OPTIONS}")
    print(f"rounds={args.rounds}")
    print("warming up...")
    for _ in range(args.warmup):
        _ = run_one("请只输出OK。")

    sequential_runs = []
    concurrent_runs = []

    for i in range(1, args.rounds + 1):
        s = run_sequential()
        c = run_concurrent()
        sequential_runs.append(s)
        concurrent_runs.append(c)
        print(
            f"[round {i}] seq_wall={s['wall_ms']:.1f}ms conc_wall={c['wall_ms']:.1f}ms "
            f"seq_ans=({s['r1']['text']!r},{s['r2']['text']!r}) "
            f"conc_ans=({c['r1']['text']!r},{c['r2']['text']!r})"
        )

    print("-" * 72)
    summarize("sequential", sequential_runs)
    summarize("concurrent", concurrent_runs)
    seq_wall = mean([x["wall_ms"] for x in sequential_runs])
    conc_wall = mean([x["wall_ms"] for x in concurrent_runs])
    print(f"speedup_by_wall= {seq_wall / conc_wall:.2f}x")


if __name__ == "__main__":
    main()
