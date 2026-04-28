# Balatro《小丑牌》白注通关入门技巧整理

> 目标：不是追求无尽模式高分，而是**稳定打过白注 Ante 8 Boss Blind**。  
> 适合：刚开始玩、经常在 Ante 3~6 暴毙、想给 AI agent 写规则/策略基线的人。

---

## 0. 白注通关的核心思路

白注并不要求你做很花的 combo。稳定通关通常靠三件事：

1. **前期先活下来**：Ante 1~2 尽快拿到能加分的 Joker。
2. **中期建立经济和构筑方向**：别把钱乱花光，围绕 1~2 种牌型升级。
3. **后期必须有 `Chips + Mult + XMult` 三类得分来源**：只堆一种通常不够。

Balatro 的基础计分逻辑是：

```text
最终得分 ≈ Chips × Mult
```

所以只加 Chips 或只加 Mult 都会遇到瓶颈。后期真正强的是 `XMult`，因为它会乘在已有 Mult 上。

---

## 1. 开局 Ante 1：优先靠 Flush / 稳定牌型过第一关

### 1.1 第一关不要过度复杂化

刚开始没有 Joker，最现实的目标是用比较高基础分的牌型过关。常见选择：

- **Flush 同花**：早期非常稳，容易凑，基础分也不错。
- **Full House 葫芦**：如果起手已经有三条或两对，可以考虑。
- **Straight 顺子**：能成时很强，但不要为了很少的 outs 硬追。

社区讨论里常见建议是：早期默认以 Flush 为主，而不是盲目追 Straight；如果手里已经有 3 of a kind，则 Full House 是好选择。

### 1.2 什么时候重开？

白注没必要过早重开。  
如果 Ante 1 商店很差，仍然可以继续打到 Ante 2~3 看有没有基础 Joker。真正危险的是：

```text
Ante 3 之后仍然没有稳定加分来源
```

此时后面的 blind 数值会明显变高，单靠基础牌型通常开始吃力。

---

## 2. 商店优先级：先拿“能活”的 Joker，再考虑花活

### 2.1 早期最需要的 Joker 类型

早期最关键的是能直接提高分数的 Joker，优先级大致是：

```text
稳定 +Mult Joker
> 稳定 +Chips Joker
> 经济 Joker
> 需要很久成长的 scaling Joker
> 花活型 utility Joker
```

早期如果没有任何加分 Joker，很容易死在 Ante 2~3。  
所以不要为了“完美构筑”错过能让你立刻过关的普通 Joker。

### 2.2 中后期 Joker 结构

比较稳定的白注通关阵容通常包含：

```text
1 个 Chips 来源
1~2 个 +Mult 来源
1 个 XMult 来源
1 个经济 / 工具 / 构筑辅助 Joker
```

不是每局都能完美，但你需要有意识地补齐短板。

### 2.3 XMult 为什么重要？

后期 blind 需求增长很快。  
普通 `+Mult` 到后面会变得不够，`XMult` 可以把已经堆起来的 Mult 再乘一遍，是通关 Ante 8 很关键的爆发来源。

---

## 3. 经济：别把钱每回合都花光

### 3.1 利息机制很重要

Balatro 每回合结束时会根据持有金钱给利息：默认每 $5 给 $1，最多 $5，也就是持有 $25 时吃满默认利息。

实战建议：

```text
前期：该买保命 Joker 就买，不要为了利息死掉
中期：尽量保持 $15~$25
后期：如果构筑成型，可以把钱用于 reroll / 补关键组件
```

### 3.2 不要无脑 reroll

新手常见错误：

```text
商店没看到想要的
→ 连续 reroll
→ 钱没了
→ 下一关又没变强
→ 暴毙
```

比较稳的规则：

```text
money < 8：一般不要 reroll，除非当前必死
money 8~15：最多少量 reroll
money > 25：可以更积极找关键 Joker / Tarot / Planet
```

### 3.3 Voucher 不要见到就买

Voucher 很强，但早期钱很紧。  
如果买 Voucher 会导致你买不起 Joker，或者吃不到利息，就要谨慎。

优先考虑：

- 增加手牌数 / 弃牌数的 Voucher
- 增强经济上限的 Voucher
- 与当前构筑强相关的 Voucher

---

## 4. 牌型路线：白注不要贪太多路线

### 4.1 选 1~2 个主力牌型

不要每种牌型都想玩。白注更稳的做法是尽早确定主力牌型，例如：

```text
Flush 路线
Pair / Two Pair 路线
High Card 路线
Full House 路线
```

然后围绕它：

```text
买对应 Planet
用 Tarot 改牌
用 Standard Pack 找关键牌
选择协同 Joker
```

### 4.2 新手最推荐的路线

#### Flush 路线

优点：

- 前期容易凑。
- 不太需要复杂 deck fixing。
- 适合初学者理解游戏节奏。

缺点：

- 后期如果没有 XMult 或套牌改造，可能不够稳定。
- 遇到某些 Boss Blind 会难受。

#### Pair / Two Pair 路线

优点：

- 容易打出来。
- 很多 scaling Joker 可以稳定成长。
- 比 Flush 更容易每回合稳定触发。

缺点：

- 基础分低，需要 Joker 支撑。
- 需要较好的 Chips / Mult 来源。

#### High Card 路线

优点：

- 最稳定，几乎每手都能出。
- 后期很多强构筑其实可以围绕 High Card。
- 不太依赖抽到特定 5 张牌。

缺点：

- 新手前期可能觉得分数太低。
- 必须依赖 Joker，而不是靠牌型基础分。

---

## 5. Planet / Tarot / Pack 选择

### 5.1 Planet：只升级你真正会打的牌型

不要看到 Planet 就随便买。  
优先买：

```text
当前主力牌型的 Planet
> 未来很可能转型的牌型 Planet
> 其他 Planet
```

如果你主打 Pair，就不要乱买 Straight / Flush 的 Planet，除非你真的准备转型。

### 5.2 Tarot：优先做 deck fixing

Tarot 的价值不只是临时加分，更重要的是改造牌组。常见目标：

- 增加主力花色数量。
- 删除无用牌。
- 复制强牌。
- 给关键牌加 enhancement。
- 把牌改成更适合当前 Joker 的形态。

### 5.3 Standard Pack / Buffoon Pack

早期 Buffoon Pack 很重要，因为它能找 Joker。  
Standard Pack 可以帮助你拿到带 Seal / Edition / Enhancement 的好牌，但不要在没有经济基础时乱开包。

---

## 6. 跳过 Blind：新手不要乱跳

跳过 blind 会给 Tag，但代价是：

```text
少打一关
少拿一轮钱
少进一次商店
少一次成长机会
```

白注新手建议：

```text
大多数时候不跳
```

可以考虑跳的情况：

- Investment Tag：前期经济收益很高。
- Negative / Polychrome / Holographic / Foil 等强 Joker 相关 Tag。
- Buffoon Tag：你急需 Joker。
- 当前构筑很强，不需要这一轮钱和商店。

如果你还不确定一个 Tag 值不值得跳，默认不要跳，正常打完 blind 更稳。

---

## 7. 出牌阶段：别只看“当前最大牌型”

### 7.1 先判断这局靠什么得分

不同构筑下，最优出牌不同：

```text
靠牌型基础分：打高价值 5 张牌型
靠 Joker 触发：打能触发 Joker 的牌型
靠某张增强牌：保证那张牌被计分
靠 scaling Joker：优先触发成长条件
```

例如你有一个“每次打 Pair 增长”的 Joker，那即使 Flush 当前分数更高，也可能应该打 Pair 来养成长。

### 7.2 不要浪费 hand / discard

一般来说：

- 如果当前牌已经能过 blind，可以考虑保留资源。
- 如果需要找关键牌，先 discard 再 play。
- 如果有 scaling Joker，尽量在安全情况下多触发成长。

### 7.3 计算时记住 Joker 触发顺序

Joker 的顺序会影响得分。通常：

```text
+Mult 放在左边
XMult 放在右边
```

因为你希望先把 Mult 加起来，再让 XMult 去乘它。

---

## 8. 白注通关的阶段策略

### Ante 1~2：保命阶段

目标：

```text
拿到第一个稳定加分 Joker
尽量别乱花钱
用 Flush / Full House / Pair 等稳定牌型过关
```

优先做：

- 买便宜且能立刻加分的 Joker。
- 少量开 Buffoon Pack 找 Joker。
- 不要为了后期 combo 牺牲当前生存。

### Ante 3~5：成型阶段

目标：

```text
确定主力牌型
开始升级主力 Planet
建立经济
补齐 Chips / Mult 来源
```

优先做：

- 选择主力路线。
- 买 scaling Joker。
- 控制 reroll 次数。
- 开 Tarot / Standard Pack 改造牌组。

### Ante 6~8：爆发阶段

目标：

```text
找到 XMult
修补构筑短板
针对 Boss Blind 做调整
```

优先做：

- 保留足够钱找关键组件。
- 补 XMult。
- 检查 Boss Blind 是否会克制你的主力牌型。
- 该卖弱 Joker 时要卖。

---

## 9. 常见暴毙原因

### 9.1 只有 Chips，没有 Mult

分数会看起来稳定，但后期增长不够。

### 9.2 只有 +Mult，没有 XMult

中期能过，后期 Ante 7~8 容易卡住。

### 9.3 经济崩盘

每回合钱都花光，导致：

```text
买不起关键 Joker
买不起 Pack
不能 reroll
吃不到利息
```

### 9.4 路线太多

同时想玩 Flush、Straight、Full House、Four of a Kind，结果每种都不够强。

### 9.5 过度追求稀有 Joker

白注通关不需要每局都拿神级 combo。  
很多普通 Joker 组合也能过，只要结构完整。

---

## 10. 给 AI Agent 的可执行规则摘要

如果你想让 AI agent 打白注，可以先写成这些规则。

### 10.1 商店规则

```text
如果 Joker 数量 < 2：
    优先买便宜的 +Mult / +Chips Joker

如果没有 +Mult：
    优先买稳定 +Mult Joker

如果没有 Chips 来源：
    优先买 Chips Joker 或升级主力牌型 Planet

如果 Ante >= 5 且没有 XMult：
    提高 XMult Joker 优先级

如果 money < 8：
    禁止 reroll，除非下一关大概率必死

如果 money >= 25：
    允许 reroll 找关键组件
```

### 10.2 牌型路线规则

```text
如果已有 Flush 协同：
    主打 Flush，优先买对应 Planet 和改花色 Tarot

如果已有 Pair / Two Pair 协同：
    主打 Pair / Two Pair，优先保留对子牌

如果 Joker 主要按“每手触发”成长：
    优先 High Card / Pair 等稳定牌型
```

### 10.3 出牌规则

```text
枚举所有可出牌组合
计算即时得分
如果能过 blind：
    选择资源消耗较低 / 能触发成长的组合
如果不能过 blind：
    选择最高期望得分组合
```

### 10.4 跳盲规则

```text
默认不跳
只有出现高价值 Tag 且当前生存压力低时跳
Investment / Negative / Polychrome / Buffoon 可以提高跳过优先级
```

---

## 11. 一份简单白注通关检查表

每个 Ante 结束后问自己：

```text
我有没有稳定 +Mult？
我有没有 Chips 来源？
我有没有后期 XMult？
我现在主打什么牌型？
我的钱是不是总低于 $5？
我的 Joker 有没有至少 3 个能直接贡献得分？
我是不是为了开包/roll 商店把经济滚没了？
Boss Blind 会不会克制我的主力路线？
```

如果这些问题大多数都有答案，白注通关率会明显提高。

---

## 12. 最短版口诀

```text
前期先买能加分的 Joker
中期别乱花钱，围绕一种牌型升级
后期一定要找 XMult
别乱跳盲，别乱 reroll
Chips、+Mult、XMult 三件套凑齐
白注就会稳定很多
```

---

## 参考资料

1. Balatro Wiki: Poker Hands. https://balatrogame.fandom.com/wiki/Poker_Hands  
2. Balatro Wiki: Jokers. https://balatrogame.fandom.com/wiki/Jokers  
3. Balatro Wiki: Vouchers. https://balatrogame.fandom.com/wiki/Vouchers  
4. Games.gg: Balatro Economy Guide. https://games.gg/balatro/guides/balatro-economy-guide/  
5. Games.gg: Balatro Beginner Guide. https://games.gg/balatro/guides/balatro-beginners-guide/  
6. Steam Community: Balatro Beginner Bguide. https://steamcommunity.com/sharedfiles/filedetails/?id=3197193231  
7. Steam Community discussion: Tips on beating the game on white stake. https://steamcommunity.com/app/2379780/discussions/0/764059330564756729/  
8. Steam Community discussion: White Stake, my absolute bane. https://steamcommunity.com/app/2379780/discussions/0/596264973809835356/  
9. PC Gamer Forum: Balatro tips and strategies. https://forums.pcgamer.com/threads/balatro-tips-and-strategies-add-your-own.148962/  
10. GameFAQs discussion: i need help improving. https://gamefaqs.gamespot.com/boards/407420-balatro/80908908  
