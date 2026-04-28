# Balatro Agent v1.2

v1.2 is an observation-first rewrite. Python no longer generates a small fixed candidate list as the main policy. Instead, it gives DeepSeek a compact but information-rich view of the game and asks it to produce structured plans and validated JSON actions.

## Run

Start BalatroBot first:

```powershell
uvx balatrobot serve --fast
```

Run one or more games:

```powershell
cd C:\toilet\balatro_bot
$env:DEEPSEEK_API_KEY="your-key"
python -m v1_2.agent --games 1 --model deepseek-v4-flash --out-dir v1_2/out --think --reasoning-effort high
```

Run play + reflect loop and write monitor state:

```powershell
python -m v1_2.loop --iterations 5 --games-per-iter 2 --model deepseek-v4-flash --out-dir v1_2/out --state-file state.json --think --reasoning-effort high
```

Start the monitor UI in another terminal:

```powershell
python state_monitor.py --state-file state.json --host 0.0.0.0 --port 8787
```

Reflect only:

```powershell
python -m v1_2.reflect --model deepseek-v4-flash --out-dir v1_2/out
```

## Memory Outputs

- `v1_2/out/runs/`: full run records.
- `v1_2/out/memory/play_memory.jsonl`: play observations, decisions, and results.
- `v1_2/out/memory/shop_memory.jsonl`: shop observations, decisions, and results.
- `v1_2/out/memory/play_skills.json`: reflected structured play skills.
- `v1_2/out/memory/shop_skills.json`: reflected structured shop skills.
- `v1_2/out/memory/mistakes.jsonl`: reflected mistakes.
- `v1_2/out/rulebook.md`: human-readable summary.
- `state.json`: monitor snapshot written by `v1_2.loop` and live RPC updates from `v1_2.agent`.

## Current Design

- Play stage is observation-first: Python builds a compact state view, DeepSeek returns one JSON action, and Python validates it before calling BalatroBot.
- Play/shop thinking mode is optional and enabled with `--think`; when enabled, the default DeepSeek reasoning effort is `high`.
- Play prompts include deterministic made-hand options from the current non-debuffed hand cards, so the model can see available Flush, Straight, Pair, Two Pair, Full House, and related plays by card index.
- Play decisions can use held Tarot/Spectral consumables with `use(consumableN, cards=[hand indexes])` when the card needs selected playing cards.
- In shop, held Planet consumables are used automatically unless Observatory is active; the model can also choose `use(consumableN)` for visible consumables.
- Shop decisions can sell inventory with `sell(jokerN)` or `sell(consumableN)`, mainly to free Joker slots, replace obsolete Jokers, or raise cash without sacrificing core scoring.
- Pack decisions can pass `targets=[hand indexes]` for Tarot/Spectral pack cards that immediately apply to selected playing cards.
- Each blind first gets a `blind_plan` that stays visible during that blind; later play decisions may update the phase/run plan.
- Shop decisions include current Jokers, current boss, next boss, shop cards, packs, vouchers, reroll cost, and slots.
- Reflect uses thinking by default and samples best/worst memories by Joker signature.
- Card effects are filled from BalatroBot API state and local `openrpc.json`.
- The monitor state is split into loop-level progress (`loop`, `counts`, `current`, `best`, `rules`) and live RPC progress (`live`).
