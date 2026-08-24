# Backtest results — points prediction model

Run: `uv run scripts/backtest.py [--sweep]`
Date: 2026-08-24 · 127 players · 11,195 recorded matches · 9,199 evaluated predictions

Walk-forward: for every historical match, the player's profile is rebuilt from
his earlier matches only. Nothing from the match itself or later ones leaks in.

## The headline

**Single-match points are intrinsically noisy.** Actual scores have a standard
deviation of 70 points around a mean of 87. The best predictor tested is still
off by ~51 points on an average match. No model fixes that; it is the nature of
one football match.

## Fair test — nothing about the match is known

This is production reality minus the odds signal (historical odds are not
available through the API, so every fixture is treated as average here).

| Method | MAE |
|---|---|
| Blend: 30% model + 70% career average | 51.1 |
| Blend: 50/50 | 51.2 |
| Player's average so far (what ØPts shows) | 51.3 |
| Model, blind | 51.9 |
| Player's average over his last 10 matches | 52.2 |
| Position baseline (ignores who the player is) | 53.0 |

**The model's player-part does not beat a simple career average.** Blending is
0.2 MAE better, which is noise. Recent form (last 10) is *worse* than the career
average — chasing form is a trap.

Knowing which player it is only buys ~1.1 MAE over a generic positional
baseline. For a single match, player identity matters far less than intuition
suggests.

## Ceiling — the real result and minutes handed to the model

| Method | MAE |
|---|---|
| Model + actual result/minutes | 38.9 |
| Same, without shrinkage | 39.4 |
| Position baseline + actual result/minutes | 40.1 |

Perfect fixture knowledge cuts error from ~52 to ~39, a 25% improvement. **That
gap is where all the value lives.** Bookmaker odds give a partial view of it.
How much of those 13 points the odds actually recover cannot be measured
backwards — only forward, from matchday 1 onward.

## Pure learned component — predicting the player's own per-90 output

| Method | MAE |
|---|---|
| Shrunk player rate | 47.1 |
| Raw player rate | 47.6 |
| Position baseline | 48.5 |

Shrinkage helps, modestly and consistently.

## Shrinkage sweep

| Prior weight (minutes) | Blind MAE | Rate MAE |
|---|---|---|
| 0 | 52.02 | 47.64 |
| 150 | 51.93 | 47.33 |
| 300 | 51.89 | 47.21 |
| **600 (current)** | **51.87** | **47.11** |
| 900 | 51.89 | 47.08 |
| 1500 | 51.96 | 47.11 |
| 3000 | 52.14 | 47.31 |

The curve is flat between 300 and 1500. The current 600 sits at the minimum;
the exact value barely matters.

## What this changes

1. **Do not read a single prediction as precise.** Show the range, not just the
   number. Being off by 40–50 points on one match is normal.
2. **Predictions are for ranking, not forecasting.** Comparing two players or
   two lineups is where small, repeated edges pay off over 34 matchdays.
3. **Keep shrinkage at 600** — confirmed near-optimal.
4. **Do not switch to recent-form averages** — measurably worse.
5. **The odds component is the open question.** Predictions are archived from
   now on so it can be scored against real results after each matchday.
