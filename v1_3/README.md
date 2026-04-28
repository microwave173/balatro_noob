# Balatro Agent v1.3

v1.3 is an observation-first rewrite. Python no longer generates a small fixed candidate list as the main policy. Instead, it gives DeepSeek a compact but information-rich view of the game and requires structured tool-call decisions that Python validates before acting.

## Run

Start BalatroBot first:

```powershell
uvx balatrobot serve --fast
```

Run one or more games:

```powershell
cd C:\toilet\balatro_bot
$env:DEEPSEEK_API_KEY="your-key"
python -m v1_3.agent --provider deepseek --model deepseek-v4-pro --games 1 --out-dir v1_3/out --reasoning-effort high
```

Run play + reflect loop and write monitor state:

```powershell
python -m v1_3.loop --provider deepseek --model deepseek-v4-pro --iterations 5 --games-per-iter 2 --out-dir v1_3/out --state-file state.json --reasoning-effort high
```

For debugging, add `--llm-log-io`. This prints only the LLM's short human commentary from each tool call without printing the full prompt or full tool arguments.

Start the monitor UI in another terminal:

```powershell
python state_monitor.py --state-file state.json --host 0.0.0.0 --port 8787
```

Reflect only:

```powershell
python -m v1_3.reflect --provider deepseek --model deepseek-v4-pro --out-dir v1_3/out --reasoning-effort high
```

Qwen thinking budget can be set explicitly:

```powershell
python -m v1_3.loop --provider qwen --model qwen3.6-plus --iterations 5 --games-per-iter 2 --out-dir v1_3/out --state-file state.json --think --reasoning-effort high --thinking-budget 8192
```

## Memory Outputs

- `v1_3/out/runs/`: full run records.
- `v1_3/out/memory/play_memory.jsonl`: play observations, decisions, and results.
- `v1_3/out/memory/shop_memory.jsonl`: shop observations, decisions, and results.
- `v1_3/out/rulebook.md`: the only reflected guidance source. Reflect rewrites this rulebook as a full update each time.
- `v1_3/out/latest_last3_llm_io.txt`: latest extracted debug snapshot when requested.
- `state.json`: monitor snapshot written by `v1_3.loop` and live RPC updates from `v1_3.agent`.

## Current Design

- Play stage is observation-first: Python builds a compact state view, DeepSeek returns one tool call, and Python validates its arguments before calling BalatroBot.
- Play/shop thinking mode is enabled by default and can be disabled with `--no-think`. DeepSeek v4 pro and Qwen thinking modes both allow tool calls, but forced `tool_choice` is omitted while thinking is enabled because those APIs reject forced tool choice in thinking mode. For Qwen, `--reasoning-effort low|medium|high` maps to `thinking_budget` 1024, 4096, or 8192 unless `--thinking-budget` is set explicitly.
- Play prompts include deterministic made-hand options from the current non-debuffed hand cards, so the model can see available Flush, Straight, Pair, Two Pair, Full House, and related plays by card index.
- Play decisions can use held Tarot/Spectral consumables with `use(consumableN, cards=[hand indexes])` when the card needs selected playing cards.
- In shop, held Planet consumables are used automatically unless Observatory is active; the model can also choose `use(consumableN)` for visible consumables.
- Shop decisions can sell inventory with `sell(jokerN)` or `sell(consumableN)`, mainly to free Joker slots, replace obsolete Jokers, or raise cash without sacrificing core scoring.
- Pack decisions can pass `targets=[hand indexes]` for Tarot/Spectral pack cards that immediately apply to selected playing cards.
- Each blind first gets a `blind_plan` that stays visible during that blind; later play decisions may update the phase/run plan.
- Shop decisions include current Jokers, current boss, next boss, shop cards, packs, vouchers, reroll cost, and slots.
- Reflect uses thinking by default, samples best/worst memories by Joker signature, and rewrites `rulebook.md` as the sole long-term guidance source.
- Structured skill JSON files are not used in v1.3; prompts only reference the rulebook.
- `v1_3/data/reference_guide.md` is loaded into the system prompt as permanent White Stake guidance before reflected rulebook context.
- Card effects are filled from BalatroBot API state and local `openrpc.json`.
- The monitor state is split into loop-level progress (`loop`, `counts`, `current`, `best`, `rules`) and live progress (`live`), including the latest LLM `commentary` shown by the monitor UI.
