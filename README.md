# Balatro Noob

AI agent experiments for playing Balatro through `balatrobot`.

The current working version is `v1_4`. It uses the BalatroBot RPC API for game actions, asks an LLM for structured decisions, writes monitor state to `state.json`, and reflects long-term guidance into `v1_4/out/rulebook.md`.

## Start v1.4

Run these in separate PowerShell terminals.

### 1. Start BalatroBot

```powershell
uvx balatrobot serve --fast
```

If `--fast` fails, try:

```powershell
uvx balatrobot serve
```

### 2. Run the play + reflect loop

DeepSeek v4 pro, thinking enabled by default:

```powershell
cd C:\toilet\balatro_bot
$env:DEEPSEEK_API_KEY="your-deepseek-key"
python -m v1_4.loop `
  --provider deepseek `
  --model deepseek-v4-pro `
  --iterations 20 `
  --games-per-iter 2 `
  --out-dir v1_4/out `
  --state-file state.json `
  --llm-log-io `
  --reasoning-effort high
```

Qwen 3.6 Plus:

```powershell
cd C:\toilet\balatro_bot
$env:QWEN_API_KEY="your-qwen-key"
python -m v1_4.loop `
  --provider qwen `
  --model qwen3.6-plus `
  --iterations 40 `
  --games-per-iter 2 `
  --out-dir v1_4/out `
  --state-file state.json `
  --llm-log-io `
  --think `
  --reasoning-effort low
```

### 3. Start the web monitor

```powershell
cd C:\toilet\balatro_bot
python state_monitor.py --state-file state.json --host 0.0.0.0 --port 8787
```

Open:

```text
http://127.0.0.1:8787
```

### Optional: commentary overlay

This shows the latest LLM commentary on top of the screen and can translate it with Qwen.

```powershell
cd C:\toilet\balatro_bot
$env:QWEN_API_KEY="your-qwen-key"
python commentary_overlay.py --state-file state.json --qwen-model qwen3.5-flash
```

## Useful Commands

Run one debug game:

```powershell
python -m v1_4.agent --provider deepseek --model deepseek-v4-pro --games 1 --max-steps 20 --out-dir v1_4/out --state-file state.json --llm-log-io
```

Reflect only:

```powershell
python -m v1_4.reflect --provider deepseek --model deepseek-v4-pro --out-dir v1_4/out --reasoning-effort high
```

Disable thinking:

```powershell
python -m v1_4.loop --provider deepseek --model deepseek-v4-pro --no-think --iterations 5 --games-per-iter 1 --out-dir v1_4/out
```

Force decision format:

```powershell
python -m v1_4.loop --provider deepseek --model deepseek-v4-pro --decision-format json --iterations 5 --games-per-iter 1 --out-dir v1_4/out
python -m v1_4.loop --provider qwen --model qwen3.6-plus --decision-format tool --iterations 5 --games-per-iter 1 --out-dir v1_4/out
```

## Output Files

- `state.json`: live monitor state.
- `v1_4/out/runs/`: full game run records.
- `v1_4/out/memory/play_memory.jsonl`: play decisions and outcomes.
- `v1_4/out/memory/shop_memory.jsonl`: shop decisions and outcomes.
- `v1_4/out/rulebook.md`: reflected long-term rulebook.
- `v1_4/data/reference_guide.md`: fixed guidance injected into prompts.

Runtime outputs and local API keys are ignored by git. Keep real keys in environment variables, not in committed files.
