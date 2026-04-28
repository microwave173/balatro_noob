# Balatro White Stake Reference

Goal: clear White Stake Ante 8 consistently. Prefer survival, stable scoring, and economy over speculative endless-mode setups.

Scoring is driven by Chips x Mult x xMult. Late-game clears usually need a balanced engine: one chips source, one or more mult sources, and an xMult path.


## White Stake Score Targets and Self-Evaluation

Use these targets to judge whether the current build is ahead, barely safe, or behind. On White Stake, each Ante has a base chip requirement. Small Blind is usually 1x base, Big Blind is 1.5x base, and most Boss Blinds are 2x base. Special Bosses can change this: The Wall is 4x base, The Needle is 1x base but only one hand, and Violet Vessel is 6x base at Ante 8.

| Ante | Small Blind | Big Blind | Normal Boss | Dangerous Boss Notes | Practical Build Check |
|---:|---:|---:|---:|---|---|
| 1 | 300 | 450 | 600 | Boss effect matters more than score. | One decent +Mult or +Chips Joker is usually enough. Do not over-reroll. |
| 2 | 800 | 1,200 | 1,600 | The Wall would be 3,200; The Needle would be 800 in one hand. | Have at least one stable scoring Joker or a very reliable hand route. |
| 3 | 2,000 | 3,000 | 4,000 | The Wall would be 8,000; The Needle would be 2,000 in one hand. | Current main hand plus Jokers should produce several thousand chips reliably. |
| 4 | 5,000 | 7,500 | 10,000 | The Wall would be 20,000; The Needle would be 5,000 in one hand. | Flat low-value Jokers start falling off. Look for scaling, stronger +Mult/+Chips, or XMult. |
| 5 | 11,000 | 16,500 | 22,000 | The Wall would be 44,000; The Needle would be 11,000 in one hand. | A weak Joker lineup plus Planet cards is risky. Upgrade Joker quality before the Boss. |
| 6 | 20,000 | 30,000 | 40,000 | The Wall would be 80,000; The Needle would be 20,000 in one hand. | You usually need a real engine: Chips + Mult + XMult or strong scaling. |
| 7 | 35,000 | 52,500 | 70,000 | The Wall would be 140,000; The Needle would be 35,000 in one hand. | Ordinary flat +Chips/+Mult is usually not enough. Search for XMult, scaling, or strong synergy. |
| 8 | 50,000 | 75,000 | 100,000 | Violet Vessel is 300,000; other finishers are usually 100,000. | Final build should reliably produce large hands or multiple medium hands under Boss effects. |

### How to Estimate Survival Chance

Before leaving a shop or choosing a risky line, compare your recent actual scoring to the next required score:

- Favored: your best normal hand can score at least 70% of the next Boss target, or your total expected score across remaining hands comfortably exceeds the target even under the Boss effect. Preserve economy unless a clear upgrade appears.
- Barely safe: your best hand scores around 40%-70% of the next Boss target, or you need two to three good hands to clear. Buy useful scoring upgrades and avoid speculative purchases.
- At risk: your best hand scores below 40% of the next Boss target, your build depends on rare draws, or the Boss counters your main route. Prioritize Joker upgrades, XMult/scaling, or a targeted Planet/Tarot that immediately fixes the scoring problem.
- Critical: you cannot explain a realistic path to the next Boss score. Do not buy economy, random Planets, random Tarot cards, or Vouchers. Spend money on immediate power, replace weak Jokers, or reroll within budget.

### Use Recent Performance, Not Hope

When evaluating win chance, use evidence from the last blind:

- If the last blind was cleared only after using most hands and all discards, treat the build as weaker than it looks.
- If the last blind was cleared in one strong hand with spare hands/discards, the build is probably safe for the next small increase.
- If a Joker only works for one hand type, evaluate the score of that hand type specifically, not the best theoretical hand in the deck.
- If the upcoming Boss debuffs the cards or hand type you relied on, reduce the estimated score sharply.
- If your score depends on a rare draw, do not count it as reliable Boss readiness.

### Shop Action Based on Score Target

- If the next target is small relative to your recent scores, save money and avoid unnecessary rerolls.
- If the next Boss target is close to your recent maximum score, buy direct scoring power before leaving the shop.
- If the upcoming target is much higher than anything you have recently scored, do not spend on non-essential Planet/Tarot/Voucher purchases. Improve the Joker engine first.
- If you are missing only one component, search specifically for that component: Chips, +Mult, XMult, scaling, or Boss counterplay.
- Do not mistake passing Small Blind for Boss readiness. Boss score is usually about twice the Ante base and may have a harmful effect.

evaluate current Jokers before choosing a hand. If a Joker rewards suit, rank, face cards, pairs, two-pairs, exact hand size, last hand, no discards, or held cards, bias toward lines that trigger it. Discard only when the current best play is unlikely to clear or when a discard has a clear path toward the active Joker plan or a set of stronger cards.

On White Stake, prioritize strong Jokers over Tarot cards, but if you buy or pick a Tarot card, remember to use it when it gives concrete value instead of letting it clog the consumable slot. For targeted Tarot cards, use current hand indexes; for example, if The Empress is held as consumable0 and hand cards 0 and 3 are cards you are likely to play, use {"action":"use","target":"consumable0","cards":[0,3]} to turn them into Mult Cards. Planet cards should mainly support a specific hand type that the current Jokers reward or that the build reliably plays.


Boss Readiness Check in Shop Phase (important):
Before leaving any shop, honestly evaluate whether the current Joker lineup can beat the nearest Boss Blind or the next dangerous blind. Do not assume the build is safe just because the last blind was cleared. Estimate whether the current scoring engine can reliably produce enough Chips x Mult x xMult under the upcoming boss effect.

- Boss readiness is a check, not a panic trigger. In Antes 1-2, do not repeatedly reroll just because the future boss looks scary; first build Joker quantity with affordable useful Jokers, then improve quality later.
- If the current Joker lineup has a low chance to beat the upcoming Boss, spend money to improve Joker quality instead of passively preserving cash.
- If a shop Joker is clearly stronger or better aligned with the current build, sell the weakest or least relevant Joker and replace it.
- If the shop has no useful Joker and the build is likely to fail soon, reroll within a reasonable budget to search for stronger scoring, XMult, scaling, or boss-countering Jokers.
- Do not keep five mediocre Jokers just because all Joker slots are full. Full slots are not the same as a strong build.
- Do not buy extra Planet cards, Tarot cards, Packs, or Vouchers when the main problem is weak Jokers before an upcoming Boss. Fix the Joker engine first.
- If money is limited, prioritize the purchase that most directly improves the chance to beat the next Boss, even if it reduces interest. Survival beats economy when the build is at risk.
- If the build is already favored to beat the Boss, then preserve economy and avoid unnecessary rerolls.


About Joker Cards (important):
1. Early game, Antes 1-2: buy immediate survival Jokers first
- The first priority is a stable scoring Joker, especially +Mult, then +Chips.
- Early game can often win by stacking several merely useful Jokers. Quantity and immediate scoring matter more than perfect synergy.
- Do not chase complex combos, rare scaling cards, expensive Vouchers, or many Planet cards too early.
- If you do not have a stable scoring Joker, shop money should go toward immediate scoring rather than greedy saving.
- Do not reroll repeatedly for a perfect Joker; early shops usually allow only 0-1 rerolls.
- If an early shop offers a decent useful Joker, buy it instead of rolling past it in search of a perfect future build.

2. Early economy: save money only after survival is stable
- In the first few blinds, survival matters more than max interest.
- Once you have a scoring Joker that can clear the next blinds, start preserving cash.
- Try to move toward $15-$25 over time, because money becomes shop choice and reroll power.
- If money is below $8, do not reroll unless the next blind is likely fatal.

3. Mid game, Antes 3-5: choose a main route and build a scoring engine
- Do not chase Flush, Straight, Full House, Pair, and other routes all at once.
- Pick one or two main hands supported by your current Jokers.
- Shop priority should be:
  core scoring Joker / synergy Joker / XMult or scaling Joker
  > important +Mult or +Chips
  > economy Joker
  > Planet for the main hand
  > Tarot for deck fixing
  > unrelated Planet / random Pack / random Voucher
- Planet cards should upgrade the hand you actually play. Do not buy them just because they appear.

4. Mid-game economy: money is option value, not something to burn
- If your scoring is stable, try to keep at least around $15.
- If you are close to $25, avoid dropping far below it for small gains.
- Mid-game rerolls are fine, but set a cap, usually around 1-3 rerolls.
- If the shop already has a clearly useful item for your build, buy it and leave instead of gambling more.
- However, if the current Joker lineup is unlikely to beat the nearest Boss, do not leave the shop just to preserve money; upgrade or replace weak Jokers when possible.

5. Late game, Antes 6-8: ordinary Jokers must become a real late-game structure
- After Ante 5, five ordinary Jokers with only small +Chips / +Mult effects are risky.
- Late game usually needs at least one strong amplifier:
  XMult Joker
  scaling Mult / XMult Joker
  strong Joker synergy
  high-level main hand plus strong deck fixing
- Do not keep spending most money on Planet cards unless the Joker engine is already strong.
- If you lack XMult or a core synergy, preserve money for rerolls and higher-quality Jokers.
- Before Boss Blinds, actively compare the weakest current Joker against shop options. Replace mediocre Jokers when a stronger or more suitable Joker appears.

6. When to buy Planet cards
- Buy if it upgrades your actual main hand and helps clear the next blind.
- Buy if your Joker engine is already strong and the Planet is supporting base Chips/Mult.
- Do not buy if you still lack a stable scoring Joker.
- Do not buy if it is Ante 5+ and your Joker lineup is weak.
- Do not buy if it prevents rerolls or drops money below a safe economy threshold.

7. When to buy economy Jokers
- Economy Jokers are good in early and mid game, especially when you can already survive.
- Their job is to fund rerolls and key Joker purchases later.
- Around Ante 6, if an economy Joker does not convert into score, consider selling or replacing it.
- Do not fill too many Joker slots with cards that do not help scoring now.

8. When to reroll
- Early game: reroll rarely, usually 0-1 times, unless survival is threatened.
- Mid game: once your route is clear, use 1-3 rerolls to find key pieces.
- Late game: reroll more aggressively if you lack XMult, core synergy, or boss counterplay.
- Below $8, default to no reroll.
- If the shop already offers a clearly useful item, buy it instead of rerolling blindly.
- If the upcoming Boss is likely to beat the current build and the shop offers no good upgrade, reroll to search for a stronger or more suitable Joker, as long as the reroll does not destroy survival money completely.

9. Hard rules for an agent: prevent Planet overbuying
- If Ante >= 5 and Joker quality is weak, do not buy non-essential Planet cards.
- If no XMult, scaling Joker, or build-defining Joker exists by Ante 5, prioritize Joker improvement over Planet cards.
- Planet cards are support, not the main engine, unless the hand level is already central to the build.
- Keep enough money for rerolls when the Joker lineup is weak.

10. One-line policy
- Early: buy immediate scoring and useful Joker quantity, do not get greedy or panic-reroll.
- Mid: commit to a route, build economy, find core Jokers, and honestly check Boss readiness before leaving shop.
- Late: find XMult, scaling, or strong synergy; replace weak Jokers before Boss fights instead of relying on ordinary Jokers plus Planet cards alone.

