# Balatro Noob

AI agent experiments for playing Balatro through `balatrobot`.

The current working version is `v1_4`. It uses the BalatroBot RPC API for game actions, asks an LLM for structured decisions, writes monitor state to `state.json`, and reflects long-term guidance into `v1_4/out/rulebook.md`.

## Prerequisites

- Balatro installed from Steam.
- Python 3.10+.
- Git.
- `uv` for running BalatroBot and installing Python tools.

Install `uv`:

```powershell
# Windows PowerShell
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

```bash
# macOS
curl -LsSf https://astral.sh/uv/install.sh | sh
```

## Install BalatroBot

BalatroBot has two parts:

- A Balatro mod installed under the Balatro `Mods` folder.
- A Python CLI that starts Balatro with the mod loaded and exposes the JSON-RPC API on `127.0.0.1:12346`.

Official docs:

- BalatroBot: <https://coder.github.io/balatrobot/installation/>
- Lovely Injector: <https://github.com/ethangreen-dev/lovely-injector>
- Steamodded: <https://github.com/Steamodded/smods>

### Windows

1. Download Lovely Injector for Windows from the latest Lovely release:
   <https://github.com/ethangreen-dev/lovely-injector/releases>

2. Extract `version.dll` into the Balatro Steam install folder, usually:

   ```text
   C:\Program Files (x86)\Steam\steamapps\common\Balatro
   ```

   `version.dll` should sit next to `Balatro.exe`.

3. Install the Balatro mods:

   ```powershell
   mkdir "$env:APPDATA\Balatro\Mods" -Force
   cd "$env:APPDATA\Balatro\Mods"

   git clone https://github.com/Steamodded/smods.git smods
   git clone https://github.com/WilsontheWolf/DebugPlus.git DebugPlus
   git clone https://github.com/coder/balatrobot.git balatrobot
   ```

4. Start BalatroBot:

   ```powershell
   uvx --from "$env:APPDATA\Balatro\Mods\balatrobot" balatrobot serve --fast
   ```

   If `--fast` causes trouble, run:

   ```powershell
   uvx --from "$env:APPDATA\Balatro\Mods\balatrobot" balatrobot serve
   ```

5. Verify the API:

   ```powershell
   uvx --from "$env:APPDATA\Balatro\Mods\balatrobot" balatrobot api health
   ```

   Expected output:

   ```json
   {
     "status": "ok"
   }
   ```

### macOS

1. Download Lovely Injector for your Mac from the latest Lovely release:
   <https://github.com/ethangreen-dev/lovely-injector/releases>

   Use `lovely-aarch64-apple-darwin.tar.gz` for Apple Silicon, or `lovely-x86_64-apple-darwin.tar.gz` for Intel.

2. Extract the archive and copy `liblovely.dylib` and `run_lovely_macos.sh` into the Balatro Steam install folder:

   ```bash
   cd ~/Downloads
   tar -xzf lovely-aarch64-apple-darwin.tar.gz

   cp liblovely.dylib run_lovely_macos.sh "$HOME/Library/Application Support/Steam/steamapps/common/Balatro/"
   chmod +x "$HOME/Library/Application Support/Steam/steamapps/common/Balatro/run_lovely_macos.sh"
   ```

   For Intel Macs, replace the archive name with `lovely-x86_64-apple-darwin.tar.gz`.

3. Install the Balatro mods:

   ```bash
   mkdir -p "$HOME/Library/Application Support/Balatro/Mods"
   cd "$HOME/Library/Application Support/Balatro/Mods"

   git clone https://github.com/Steamodded/smods.git smods
   git clone https://github.com/WilsontheWolf/DebugPlus.git DebugPlus
   git clone https://github.com/coder/balatrobot.git balatrobot
   ```

4. Start BalatroBot:

   ```bash
   uvx --from "$HOME/Library/Application Support/Balatro/Mods/balatrobot" balatrobot serve \
     --platform darwin \
     --love-path "$HOME/Library/Application Support/Steam/steamapps/common/Balatro/run_lovely_macos.sh" \
     --lovely-path "$HOME/Library/Application Support/Steam/steamapps/common/Balatro/liblovely.dylib" \
     --fast
   ```

   If `--fast` causes trouble, remove `--fast`.

   On macOS, start Balatro through this command instead of pressing Play in Steam. The command launches the Steam copy with Lovely injected.

5. Verify the API:

   ```bash
   uvx --from "$HOME/Library/Application Support/Balatro/Mods/balatrobot" balatrobot api health
   ```

   Expected output:

   ```json
   {
     "status": "ok"
   }
   ```

## Install This Project

Clone this repo and install the Python packages used by the agent:

```bash
git clone https://github.com/microwave173/balatro_noob.git
cd balatro_noob
python -m pip install openai flask pillow
```

On Windows, run the same commands in PowerShell. If `python` points to the wrong interpreter, try `py -m pip install openai flask pillow`.

## Start v1.4

Run these in separate terminals.

### 1. Start BalatroBot

Use the Windows or macOS BalatroBot command above and keep that terminal open.

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

macOS/Linux shell version:

```bash
export DEEPSEEK_API_KEY="your-deepseek-key"
python -m v1_4.loop \
  --provider deepseek \
  --model deepseek-v4-pro \
  --iterations 20 \
  --games-per-iter 2 \
  --out-dir v1_4/out \
  --state-file state.json \
  --llm-log-io \
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

macOS/Linux shell version:

```bash
export QWEN_API_KEY="your-qwen-key"
python -m v1_4.loop \
  --provider qwen \
  --model qwen3.6-plus \
  --iterations 40 \
  --games-per-iter 2 \
  --out-dir v1_4/out \
  --state-file state.json \
  --llm-log-io \
  --think \
  --reasoning-effort low
```

### 3. Start the web monitor

```powershell
python state_monitor.py --state-file state.json --host 0.0.0.0 --port 8787
```

Open:

```text
http://127.0.0.1:8787
```

### Optional: commentary overlay

This shows the latest LLM commentary on top of the screen and can translate it with Qwen.

```powershell
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

## Troubleshooting

- `balatrobot api health` fails: make sure the BalatroBot terminal is still running and the game window opened.
- `Connection refused`: BalatroBot is not listening on `127.0.0.1:12346`, or another program is using that port.
- Mods do not appear in-game: check that Lovely is in the Steam Balatro folder and `smods`, `DebugPlus`, and `balatrobot` are folders under the Balatro `Mods` directory.
- macOS starts but health never returns `ok`: use `run_lovely_macos.sh` as `--love-path`, as shown above.
- Windows path errors: confirm Balatro is installed under Steam's `steamapps\common\Balatro`, and `version.dll` is next to `Balatro.exe`.

## Output Files

- `state.json`: live monitor state.
- `v1_4/out/runs/`: full game run records.
- `v1_4/out/memory/play_memory.jsonl`: play decisions and outcomes.
- `v1_4/out/memory/shop_memory.jsonl`: shop decisions and outcomes.
- `v1_4/out/rulebook.md`: reflected long-term rulebook.
- `v1_4/data/reference_guide.md`: fixed guidance injected into prompts.

Runtime outputs and local API keys are ignored by git. Keep real keys in environment variables, not in committed files.
