# Balatro White Stake Reference — Compact Agent Version

Goal: clear White Stake Ante 8 consistently. Prefer survival, stable scoring, and economy over speculative endless-mode setups.

Scoring is driven by **Chips × Mult × XMult**. Late-game clears usually need a balanced engine: one Chips source, one or more +Mult sources, and an XMult path.

## Core Scoring Rules for Play Decisions

1. **Only scoring cards add card chips and card effects.**
   - If you play 5 cards as **High Card**, usually only the High Card itself scores; the other played cards are ignored for card chips/effects.
   - If you play 5 cards as **Pair**, usually only the two paired cards score; the other three played cards do not add chips or trigger "when scored" effects.
   - If you play **Two Pair**, the four pair cards score; the fifth kicker usually does not score.
   - If you play **Three of a Kind**, the three matching cards score; extra unrelated cards do not score.
   - If you play **Full House, Flush, Straight, Four of a Kind, Straight Flush**, the cards that form that hand score.
   - Exceptions: special effects such as **Splash** or **Stone Cards** can make otherwise unscored cards score. Boss-debuffed cards still score zero chips/effects.

2. **Do not play extra filler cards unless they help.**
   - Extra cards can be useful only if they change the hand type, trigger a Joker, trigger a seal/enhancement, or are allowed to score by a special effect.
   - Otherwise, extra filler cards are just discarded and may make the agent overestimate score.

3. **Joker text using "contains" is broader than the final scored hand name.**
   - A hand that **contains Pair** can include Pair, Two Pair, Three of a Kind, Full House, Four of a Kind, and Five of a Kind.
   - A **Full House contains both Three of a Kind and Pair** for Joker trigger purposes.
   - A **Two Pair contains Pair**.
   - A **Four of a Kind contains Pair**, but it does **not** count as Two Pair because Two Pair requires two distinct ranks.
   - Use the actual hand information / game state when available.

4. **Prefer the highest useful poker hand unless Joker value clearly says otherwise.**
   - If the hand has Two Pair, do not play only one Pair unless a Joker strongly rewards Pair or playing fewer cards.
   - If the hand has Full House, do not downgrade to Three of a Kind or Pair unless the Joker benefit clearly exceeds the lost base score.
   - If the hand has Straight/Flush/Full House/Four of a Kind and no Joker requires a lower hand, prefer the stronger scoring hand.
   - Do not force a weak Joker trigger if it makes the total score lower or risks losing the blind.

5. **Estimate score before choosing play/discard.**
   - Compare best available play against the blind target and remaining hands.
   - If current best play can clear or make strong progress, play it.
   - If current best play is far below target and discards remain, discard toward a clear route.

## White Stake Score Targets and Self-Evaluation

Use these targets to judge whether the current build is ahead, barely safe, or behind. On White Stake, Small Blind is usually 1× base, Big Blind 1.5× base, and most Boss Blinds 2× base.

| Ante |  Small |    Big | Normal Boss | Practical check                                              |
| ---: | -----: | -----: | ----------: | ------------------------------------------------------------ |
|    1 |    300 |    450 |         600 | One decent +Mult/+Chips Joker is usually enough.             |
|    2 |    800 |  1,200 |       1,600 | Have stable scoring or a reliable hand route.                |
|    3 |  2,000 |  3,000 |       4,000 | Main hand + Jokers should make several thousand chips.       |
|    4 |  5,000 |  7,500 |      10,000 | Flat weak Jokers start falling off; find stronger scoring.   |
|    5 | 11,000 | 16,500 |      22,000 | Weak Jokers + random Planets is risky. Upgrade Joker quality. |
|    6 | 20,000 | 30,000 |      40,000 | Need real engine: Chips + Mult + XMult or strong scaling.    |
|    7 | 35,000 | 52,500 |      70,000 | Ordinary flat +Chips/+Mult usually not enough.               |
|    8 | 50,000 | 75,000 |     100,000 | Final build should produce large hands or several reliable medium hands. |

Special Boss notes: The Wall is much larger, The Needle allows only one hand, Violet Vessel at Ante 8 is much larger. Always apply the actual boss effect.

Survival estimate:

- **Favored:** best normal hand scores 70%+ of next Boss target, or remaining hands comfortably clear.
- **Barely safe:** best hand scores 40%-70%; buy useful scoring upgrades and avoid speculation.
- **At risk:** best hand scores below 40%, needs rare draws, or Boss counters main route; prioritize Joker upgrades, XMult/scaling, or targeted Planet/Tarot.
- **Critical:** no realistic path to next Boss score; do not buy economy/random Planets/random Tarot/Vouchers. Buy power, replace weak Jokers, or reroll within budget.

## Play and Discard Policy

- Evaluate current Jokers before choosing cards. If a Joker rewards suit, rank, face cards, pairs, two-pairs, exact hand size, last hand, no discards, or held cards, bias toward lines that trigger it **only when the score remains good**.
- Do not downgrade a better natural hand into a weaker hand unless the Joker trigger is clearly worth more.
- Discard only when the current best play is unlikely to clear or when a discard has a clear path toward the active Joker plan or stronger cards.
- Do not spend all discards chasing speculative improvements. Preserve at least 1 discard when possible.
- When discarding, keep duplicated ranks, near-flush suits, enhanced cards, and cards that trigger current Jokers. Discard singleton low cards and boss-debuffed/conflicting cards.
- If multiple hands remain and discards are exhausted, play the strongest available hand each turn. You cannot improve without discards.
- A discard does not consume a hand. Even with only 1 hand left, if discards_left > 0 and the current best play is doomed, discarding can be better than playing.

## Boss Readiness Check in Shop Phase

Before leaving shop, honestly evaluate whether the current Joker lineup can beat the nearest Boss or next dangerous blind. Do not assume the build is safe just because the last blind was cleared.

- If the build is favored, preserve economy and avoid unnecessary rerolls.
- If the build is barely safe, buy clear scoring upgrades but avoid panic rerolls.
- If the build is at risk or critical, spend money to improve Joker quality instead of passively preserving cash.
- If a shop Joker is clearly stronger or better aligned, sell the weakest/off-route Joker and replace it.
- If shop has no useful Joker and failure risk is high, reroll within a reasonable budget for stronger scoring, XMult, scaling, or boss counterplay.
- Do not keep five mediocre Jokers just because slots are full.
- Do not buy extra Planet/Tarot/Packs/Vouchers when the main problem is weak Jokers before a Boss.

## Shop Policy by Stage

### Antes 1-2: immediate survival and useful Joker quantity

- Buy stable scoring Jokers first: +Mult, then +Chips, then simple synergy/economy.
- Early game can often win by stacking several useful Jokers. Quantity and immediate scoring matter more than perfect synergy.
- One ordinary Joker is not an established engine. After buying only one Joker, default to saving money or finding another scoring Joker, not buying random Planets/Tarot.
- Do not chase complex combos, rare scaling, expensive Vouchers, or many Planets early.
- Early rerolls: usually 0-1. If a decent useful Joker appears, buy it instead of rolling past it.
- Save money only after survival is stable. Below $8, default to no reroll unless the next blind is likely fatal.

### Antes 3-5: choose a route and build an engine

- Pick one or two main hand routes supported by Jokers; do not chase every hand type.
- Shop priority: core scoring/synergy Joker or XMult/scaling > important +Mult/+Chips > economy Joker > main-hand Planet > targeted Tarot > unrelated Planet/Pack/Voucher.
- Mid-game rerolls: 1-3 only with a clear target.
- If the current Joker lineup is unlikely to beat the nearest Boss, do not leave shop just to preserve money.

### Antes 6-8: replace weak pieces and find amplification

- Five ordinary Jokers with only small +Chips/+Mult are risky.
- Need at least one strong amplifier: XMult, scaling Mult/XMult, strong synergy, or high-level main hand with deck fixing.
- Do not keep spending most money on Planets unless the Joker engine is already strong.
- Replace mediocre Jokers before Boss fights when a stronger or more suitable Joker appears.
- Economy Jokers that do not convert into score should often be sold/replaced around Ante 6.

## Planet, Tarot, Economy, and Reroll Rules

Planet cards:

- Buy if it upgrades the hand you actually play and helps clear the next blind.
- Buy if Joker engine is already strong and Planet supports base Chips/Mult.
- Do not buy if you still lack stable scoring, if Joker quality is weak, or if it blocks Joker upgrades/rerolls.

Tarot cards:

- Buy/use when it gives concrete value: adds Mult/Bonus cards to likely scoring cards, fixes suits/ranks toward the build, copies/removes useful cards, or solves the next blind.
- Do not let Tarot clog consumable slots. If a targeted Tarot is useful now, use it with current hand indexes.

Economy:

- Economy Jokers are good early/mid only when you can already survive.
- Their purpose is to fund future Joker upgrades/rerolls; sell them when scoring is the problem.
- Do not hoard money while Joker lineup is weak. Convert economy into power before Boss blinds.

Reroll discipline:

- Early: 0-1 rerolls.
- Mid: 1-3 rerolls with a clear target.
- Late: more aggressive only when lacking XMult, scaling, or boss counterplay.
- Below $8: default no reroll.
- If shop repeatedly has no Jokers, do not spend $15+ on empty rerolls.

## One-Line Policy

Early: buy immediate scoring and useful Joker quantity.  
Mid: commit to a route, build economy, find core Jokers, and check Boss readiness.  
Late: find XMult/scaling/strong synergy; replace weak Jokers instead of relying on ordinary Jokers plus Planet cards.  
During play: score only the actual scoring cards, respect "contains" triggers, and prefer the strongest useful hand unless Joker value clearly justifies a downgrade.