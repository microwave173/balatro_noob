# Balatro Noob 项目说明与运行指南

这份文档给第一次接手项目的人看。目标是快速理解这个项目在做什么、核心代码在哪里、怎么把 BalatroBot 和 LLM agent 跑起来。

## 这个项目做什么

`balatro_noob` 是一个用 LLM 自动玩 Balatro 的实验项目。它不直接读屏或模拟鼠标，而是通过 `balatrobot` 提供的 JSON-RPC API 读取游戏状态并执行动作。

核心流程：

```text
Balatro + BalatroBot RPC
  -> v1_4.agent 读取 gamestate
  -> observation.py 把当前局面整理成 LLM 可读文本
  -> DeepSeek / Qwen 输出结构化决策
  -> validator.py 校验动作是否合法
  -> rpc.py 调用 play / discard / buy / sell / reroll / use
  -> runner.py 记录每局轨迹和记忆
  -> 每层结束评估 effort 1-10 分
  -> reflect.py 对比最难/最易层并增量编辑 rulebook.md
```

当前主版本是 `v1_4`。旧的 `v1_1`、`v1_2`、`v1_3` 主要是历史实验版本。

## 重要目录和文件

```text
README.md                         安装 BalatroBot 和基础运行命令
PROJECT_GUIDE.md                  当前这份接手说明
state_monitor.py                  Web 监控页面
commentary_overlay.py             屏幕右上角 LLM 解说 overlay
state.json                        运行时状态快照

v1_4/agent.py                     单次运行若干局游戏的入口
v1_4/loop.py                      play + reflect 循环入口
v1_4/reflect.py                   从历史局总结 rulebook
v1_4/core/runner.py               主游戏循环和阶段调度
v1_4/core/observation.py          把 BalatroBot state 转成 prompt observation
v1_4/core/prompts.py              系统 prompt 和结构化输出 schema
v1_4/core/deepseek_policy.py      DeepSeek/Qwen 调用与结构化输出解析
v1_4/core/validator.py            LLM 动作合法性校验和 fallback
v1_4/core/rpc.py                  BalatroBot JSON-RPC client
v1_4/core/memory.py               rulebook 记忆读取和 JSONL 写入
v1_4/data/reference_guide.md      固定注入 prompt 的 Balatro 策略参考

v1_4/out/runs/                    每局完整运行记录
v1_4/out/memory/play_memory.jsonl 出牌阶段记忆
v1_4/out/memory/shop_memory.jsonl 商店阶段记忆
v1_4/out/memory/ante_reviews.jsonl 每层完整轨迹与费力程度评价
v1_4/out/rulebook.md              reflect 后的长期规则
```

## 运行前准备

需要：

- Steam 版 Balatro
- Python 3.10+
- `uv`
- BalatroBot mod
- 一个 LLM API key：DeepSeek 或 Qwen

Python 依赖：

```bash
cd /Users/mabokai/Desktop/proj/balatro_noob
python -m pip install openai flask pillow
```

如果是 Windows：

```powershell
py -m pip install openai flask pillow
```

## 启动 BalatroBot

必须先启动 BalatroBot。agent 会连接默认地址：

```text
127.0.0.1:12346
```

macOS 常用命令：

```bash
uvx --from "$HOME/Library/Application Support/Balatro/Mods/balatrobot" balatrobot serve \
  --platform darwin \
  --love-path "$HOME/Library/Application Support/Steam/steamapps/common/Balatro/run_lovely_macos.sh" \
  --lovely-path "$HOME/Library/Application Support/Steam/steamapps/common/Balatro/liblovely.dylib" \
  --fast
```

Windows 常用命令：

```powershell
uvx --from "$env:APPDATA\Balatro\Mods\balatrobot" balatrobot serve --fast
```

验证 RPC 是否可用：

```bash
uvx --from "$HOME/Library/Application Support/Balatro/Mods/balatrobot" balatrobot api health
```

Windows：

```powershell
uvx --from "$env:APPDATA\Balatro\Mods\balatrobot" balatrobot api health
```

期望输出：

```json
{"status": "ok"}
```

如果 agent 报：

```text
[fatal] balatrobot health check failed
```

优先检查 BalatroBot 是否还在运行、端口是否是 `12346`、Balatro 是否是通过 BalatroBot 命令启动的。

## 运行 v1.4 agent

推荐先从 `v1_4.loop` 开始，因为它会自动执行：

```text
PLAY 若干局 -> REFLECT 总结经验 -> 下一轮继续
```

DeepSeek：

```bash
cd /Users/mabokai/Desktop/proj/balatro_noob
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

Qwen：

```bash
cd /Users/mabokai/Desktop/proj/balatro_noob
export QWEN_API_KEY="your-qwen-key"
python -m v1_4.loop \
  --provider qwen \
  --model qwen3.6-plus \
  --iterations 20 \
  --games-per-iter 2 \
  --out-dir v1_4/out \
  --state-file state.json \
  --llm-log-io \
  --think \
  --reasoning-effort high
```

VisionCoder GPT-5.6：

```bash
cd /Users/mabokai/Desktop/proj/balatro_noob
python -m v1_4.loop \
  --provider visioncoder \
  --model gpt-5.6-sol \
  --iterations 20 \
  --games-per-iter 2 \
  --out-dir v1_4/out \
  --state-file state.json \
  --llm-log-io \
  --reasoning-effort high
```

VisionCoder 会自动读取项目根目录的 `.env`：

```text
VISIONCODER_API_KEY=...
VISIONCODER_BASE_URL=https://coder.api.visioncoder.cn/v1
VISIONCODER_MODEL=gpt-5.6-sol
```

只跑一局，不做 reflect：

```bash
python -m v1_4.agent \
  --provider deepseek \
  --model deepseek-v4-pro \
  --games 1 \
  --out-dir v1_4/out \
  --state-file state.json \
  --llm-log-io \
  --reasoning-effort high
```

## 启动监控页面

另开一个终端：

```bash
cd /Users/mabokai/Desktop/proj/balatro_noob
python state_monitor.py --state-file state.json --host 0.0.0.0 --port 8787
```

浏览器打开：

```text
http://127.0.0.1:8787
```

监控页面会读取 `state.json`，展示当前轮次、最好成绩、最新 live state 和 rulebook 摘要。

## 可选：启动 commentary overlay

overlay 会把 LLM 每步的简短 commentary 显示到屏幕右上角。

```bash
export QWEN_API_KEY="your-qwen-key"
python commentary_overlay.py --state-file state.json --qwen-model qwen3.5-flash
```

macOS Tk 不支持 `-transparentcolor` 时，可能需要在 `commentary_overlay.py` 里使用 `-alpha` 或关闭透明色逻辑。之前出现过类似报错：

```text
_tkinter.TclError: bad attribute "-transparentcolor"
```

## v1.4 的决策机制

每一步 agent 会根据游戏阶段选择不同 schema：

- `BLIND_SELECT`: 选择盲注或跳过
- `PLAY`: 出牌、弃牌、使用消耗牌、检查牌堆
- `SHOP`: 买牌、卖牌、reroll、进入下一轮
- `PACK`: 开补充包时选择卡牌或跳过

LLM 输出结构化动作后，`validator.py` 会做安全校验：

- 卡牌 index 必须在当前手牌范围内
- 没钱不能买
- 商店里不能非法使用需要手牌目标的 Tarot
- 非法 sell / use 会 fallback
- 输出解析失败时会尽量 salvage，否则走默认 play

所以 LLM 的输出不会无条件执行。

## reflection 机制

每轮 `v1_4.loop` 会先玩若干局，再调用 `v1_4.reflect`。

每个 Ante（小盲、大盲、Boss）结束后，agent 会根据该层完整轨迹评价费力程度：

- `1-2`: 基本无压力，少量出牌且余量充足
- `3-4`: 较轻松，只有常规弃牌或调整
- `5-6`: 中等，需要多次出牌、针对性弃牌或承受一定资源压力
- `7-8`: 困难，牌型难凑、余量窄、构筑不稳定或较依赖运气
- `9`: 勉强过关，接近最后一手或依赖幸运翻盘
- `10`: 该层失败；失败强制为 10

评价会保留出牌/弃牌次数、剩余手数、得分余量、Boss、Joker 变化、商店动作和关键轨迹，写入：

```text
v1_4/out/memory/ante_reviews.jsonl
```

reflect 默认选取最难 3 层和最易 3 层作对照。3+3 能覆盖失败、勉强过关和顺利成型等差异，同时把 prompt 控制在可管理范围；可通过 `--extreme-count` 调整。

reflect 不再重写整本 rulebook，而是最多执行 6 个有轨迹证据的 `add`、`update` 或 `delete` 操作。首次没有 rulebook 时以 `v1_4/bak/rulebook.md` 为基线。

最后重写：

```text
v1_4/out/rulebook.md
```

下一轮 prompt 会引用更新后的 rulebook 和本局已完成层的紧凑 effort 评价，而不是把全部历史日志塞进上下文。

## 游戏崩溃后的自动重启

`v1_4.loop` 现在每局单独启动一次 agent。每局前检查 BalatroBot health；如果胜利后游戏崩溃或 RPC 失联，loop 会重新启动 BalatroBot/Balatro，再运行下一局。agent 退出但没有生成新的 run 文件也会被视为失败，并在重启后重试一次。

macOS 和 Windows 有默认启动命令。自定义安装方式可覆盖：

```bash
python -m v1_4.loop ... \
  --balatrobot-serve-command 'your balatrobot serve command'
```

如需禁止自动重启，添加 `--no-auto-restart-game`。

## 局内历史压缩

最近操作使用紧凑字段保存，不再重复保存 commentary。默认在记录超过 36 条或实际渲染文本超过 14000 字符时压缩，并保留最近 12 条原始操作；旧逻辑在 13 条时触发且压缩后仅留 8 条，容易约每 5 步再次调用 compact。

## 常见问题

### 1. `balatrobot health check failed`

BalatroBot 没启动、端口不对、Balatro 不是通过 BalatroBot/Lovely 启动，或者 RPC 服务崩了。

处理：

```bash
balatrobot api health
```

如果不通，重启 BalatroBot serve。

### 2. LLM API key empty

DeepSeek：

```bash
export DEEPSEEK_API_KEY="your-key"
```

Qwen：

```bash
export QWEN_API_KEY="your-key"
```

Windows PowerShell：

```powershell
$env:DEEPSEEK_API_KEY="your-key"
$env:QWEN_API_KEY="your-key"
```

### 3. 模型输出不是合法 JSON / tool call

可以尝试：

```bash
--decision-format json
```

或者关闭 thinking：

```bash
--no-think
```

DeepSeek 默认更适合 JSON Output，Qwen 默认更适合 tool call。
VisionCoder 使用 Responses API，并强制走 JSON Output。

### 4. 运行太慢

降低循环规模：

```bash
--iterations 3 --games-per-iter 1
```

或降低推理强度：

```bash
--reasoning-effort low
```

### 5. 想清空历史重新实验

谨慎删除：

```bash
rm -rf v1_4/out
rm -f state.json
```

这会清除历史 run、memory 和 reflected rulebook。

## 接手建议

如果只是想跑起来：

1. 先保证 `balatrobot api health` 返回 ok。
2. 再跑 `python -m v1_4.agent --games 1 ...`。
3. 确认能完整玩一局后，再跑 `v1_4.loop`。
4. 同时开 `state_monitor.py` 观察状态。

如果想改进效果，优先看：

```text
v1_4/core/observation.py
v1_4/core/prompts.py
v1_4/core/validator.py
v1_4/reflect.py
```

这四处分别决定：模型看见什么、模型被要求怎么回答、动作如何被约束、长期经验如何更新。
