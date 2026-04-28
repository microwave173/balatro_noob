import argparse
import json
from pathlib import Path
from typing import Any, Dict

from flask import Flask, jsonify


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Simple monitor UI for loop state.json")
    p.add_argument("--state-file", default="state.json")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8787)
    p.add_argument("--refresh-ms", type=int, default=2000)
    return p.parse_args()


def _load_state(state_path: Path) -> Dict[str, Any]:
    if not state_path.exists():
        return {
            "status": "missing",
            "message": f"state file not found: {state_path}",
        }
    try:
        return json.loads(state_path.read_text(encoding="utf-8-sig"))
    except Exception as e:
        return {
            "status": "error",
            "message": f"failed to parse state file: {e}",
        }


def create_app(state_path: Path, refresh_ms: int) -> Flask:
    app = Flask(__name__)

    @app.get("/api/state")
    def api_state() -> Any:
        return jsonify(_load_state(state_path))

    @app.get("/")
    def index() -> str:
        return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Balatro Loop Monitor</title>
  <style>
    :root {{
      --bg: #f6f7fb;
      --panel: #ffffff;
      --ink: #1f2937;
      --muted: #6b7280;
      --accent: #0f766e;
      --bad: #b91c1c;
      --ok: #15803d;
      --border: #e5e7eb;
    }}
    body {{
      margin: 0;
      padding: 24px;
      background: radial-gradient(circle at top left, #e0f2fe, #f6f7fb 35%);
      color: var(--ink);
      font-family: "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif;
    }}
    .wrap {{ max-width: 980px; margin: 0 auto; }}
    .title {{ font-size: 28px; font-weight: 700; margin-bottom: 12px; }}
    .meta {{ color: var(--muted); margin-bottom: 16px; }}
    .grid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
      gap: 12px;
      margin-bottom: 14px;
    }}
    .card {{
      background: var(--panel);
      border: 1px solid var(--border);
      border-radius: 12px;
      padding: 12px;
      box-shadow: 0 2px 10px rgba(0,0,0,0.04);
    }}
    .k {{ font-size: 12px; color: var(--muted); margin-bottom: 6px; }}
    .v {{ font-size: 20px; font-weight: 700; }}
    .ok {{ color: var(--ok); }}
    .bad {{ color: var(--bad); }}
    .panel {{
      background: var(--panel);
      border: 1px solid var(--border);
      border-radius: 12px;
      padding: 14px;
      margin-top: 12px;
      box-shadow: 0 2px 10px rgba(0,0,0,0.04);
    }}
    pre {{
      margin: 0;
      white-space: pre-wrap;
      word-break: break-word;
      font-size: 12px;
      background: #f9fafb;
      border: 1px solid var(--border);
      border-radius: 8px;
      padding: 10px;
    }}
    ul {{ margin: 8px 0 0 20px; padding: 0; }}
    li {{ margin: 4px 0; }}
    .commentary {{
      font-size: 16px;
      line-height: 1.5;
      white-space: pre-wrap;
    }}
    .commentaryMeta {{
      color: var(--muted);
      font-size: 12px;
      margin-bottom: 8px;
    }}
  </style>
</head>
<body>
  <div class="wrap">
    <div class="title">Balatro Loop Monitor</div>
    <div class="meta">Auto refresh: {refresh_ms} ms | state file: {state_path}</div>

    <div class="grid">
      <div class="card"><div class="k">Status</div><div id="status" class="v">-</div></div>
      <div class="card"><div class="k">Cycle</div><div id="cycle" class="v">-</div></div>
      <div class="card"><div class="k">Stage</div><div id="stage" class="v">-</div></div>
      <div class="card"><div class="k">Games Completed</div><div id="games" class="v">-</div></div>
      <div class="card"><div class="k">Reflect Completed</div><div id="reflects" class="v">-</div></div>
      <div class="card"><div class="k">Provider / Model</div><div id="model" class="v" style="font-size:14px">-</div></div>
      <div class="card"><div class="k">Live (Ante / Round)</div><div id="current" class="v">-</div></div>
      <div class="card"><div class="k">Live Method</div><div id="liveMethod" class="v" style="font-size:14px">-</div></div>
      <div class="card"><div class="k">Best (Ante / Round)</div><div id="best" class="v">-</div></div>
    </div>

    <div class="panel">
      <div class="k">Current Commentary</div>
      <div id="commentaryMeta" class="commentaryMeta">-</div>
      <div id="commentary" class="commentary">-</div>
    </div>

    <div class="panel">
      <div class="k">Current Rules</div>
      <ul id="rules"></ul>
    </div>

    <div class="panel">
      <div class="k">Last Error</div>
      <div id="lastError">-</div>
    </div>

    <div class="panel">
      <div class="k">Raw JSON</div>
      <pre id="raw"></pre>
    </div>
  </div>

  <script>
    const refreshMs = {refresh_ms};
    function txt(v) {{ return (v === null || v === undefined || v === "") ? "-" : String(v); }}

    function render(data) {{
      const statusEl = document.getElementById("status");
      statusEl.textContent = txt(data.status);
      statusEl.className = "v " + ((data.status === "done" || data.status === "running") ? "ok" : (data.status === "error" ? "bad" : ""));

      const loop = data.loop || {{}};
      const counts = data.counts || {{}};
      document.getElementById("cycle").textContent = `${{txt(loop.current_iteration)}} / ${{txt(loop.iterations_total)}}`;
      document.getElementById("stage").textContent = txt(loop.stage);
      document.getElementById("games").textContent = txt(counts.games_completed);
      document.getElementById("reflects").textContent = txt(counts.reflect_completed);
      document.getElementById("model").textContent = `${{txt(data.provider)}} / ${{txt(data.model)}}`;

      const cur = data.current || {{}};
      const live = data.live || {{}};
      const best = data.best || {{}};
      const liveAnte = (live.ante !== undefined && live.ante !== null) ? live.ante : cur.ante;
      const liveRound = (live.round !== undefined && live.round !== null) ? live.round : cur.round;
      document.getElementById("current").textContent = `${{txt(liveAnte)}} / ${{txt(liveRound)}}`;
      document.getElementById("liveMethod").textContent = txt(live.last_method);
      document.getElementById("best").textContent = `${{txt(best.ante)}} / ${{txt(best.round)}}`;
      document.getElementById("commentaryMeta").textContent = `${{txt(live.commentary_label)}} | ${{txt(live.commentary_updated_at)}}`;
      document.getElementById("commentary").textContent = txt(live.commentary);

      const rulesEl = document.getElementById("rules");
      rulesEl.innerHTML = "";
      const rules = ((data.rules || {{}}).items || []);
      if (rules.length === 0) {{
        const li = document.createElement("li");
        li.textContent = "-";
        rulesEl.appendChild(li);
      }} else {{
        for (const r of rules) {{
          const li = document.createElement("li");
          li.textContent = r;
          rulesEl.appendChild(li);
        }}
      }}

      document.getElementById("lastError").textContent = txt(data.last_error);
      document.getElementById("raw").textContent = JSON.stringify(data, null, 2);
    }}

    async function refresh() {{
      try {{
        const res = await fetch("/api/state?t=" + Date.now(), {{ cache: "no-store" }});
        const data = await res.json();
        render(data);
      }} catch (e) {{
        document.getElementById("status").textContent = "fetch error";
        document.getElementById("status").className = "v bad";
      }}
    }}

    refresh();
    setInterval(refresh, refreshMs);
  </script>
</body>
</html>"""

    return app


def main() -> None:
    args = parse_args()
    here = Path(__file__).resolve().parent
    state_path = (here / args.state_file).resolve() if not Path(args.state_file).is_absolute() else Path(args.state_file)
    app = create_app(state_path, args.refresh_ms)
    print(f"[monitor] reading state from: {state_path}")
    print(f"[monitor] open: http://{args.host}:{args.port}")
    app.run(host=args.host, port=args.port, debug=False)


if __name__ == "__main__":
    main()
