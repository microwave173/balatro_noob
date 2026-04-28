# Balatro Agent Rulebook

Version: 2026-04-26 07:27:54
Source: heuristic+merge

## Performance Snapshot
- Games analyzed: 10
- Win rate: 0.00%
- Avg ante: 1.20
- Avg round: 2.20
- Early death rate (ante<=1): 80.00%
- Missed best play rate: 0.00%
- Avg play gap when missed: 0.00
- Discard-with-play-available rate: 100.00%
- Rules count: 10

## Rules
- During early antes, avoid skipping Small/Big blind unless economy is very strong.
- If current hand estimated score is weak and discards remain, prioritize one discard before play.
- Reduce early pack purchases when money is below 8; prefer reliable Joker value.
- Before Ante 3, prioritize at least one immediate scoring Joker over niche setup pieces.
- When shop has no clear value buy, choose next_round instead of forcing spend.
- Discard only when current best playable line is unlikely to clear the blind and discards_left > 0.
- If a playable line is already strong, preserve discard resources for later draws.
- When a blind is already mathematically beatable, avoid unnecessary discard risk.
- Target a balanced scaling profile by mid game: chips source + mult source + at least one xmult path.
- Preserve emergency economy buffer unless the current buy is a clear power spike.
