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

## Update — goal/assist term added

The `k` field on each match records which events occurred. The codes were
decoded by cross-checking counts against Understat's totals for the 2025/26
Bundesliga: **19 of 19 players agreed exactly** (Guirassy 17 goals, El Mala 13,
Uzun 8 goals / 4 assists, Ryerson 0 goals / 15 assists). So `k` code 1 = goal,
code 3 = assist, with certainty.

Goals and assists are now removed from the residual and predicted separately
from the player's own goal rate, scaled by the attacking strength the odds
imply for his team that day.

| Method (blind) | MAE |
|---|---|
| Blend: 30% model + 70% career average | 51.1 |
| Blend: 50/50 | 51.1 |
| Player's career average (ØPts) | 51.3 |
| **Model with goal/assist term** | **51.8** |
| Player's last 10 matches | 52.1 |
| Model without goal/assist term | 52.6 |
| Position baseline | 53.9 |

The goal term is worth **0.8 MAE** — the largest single modelling gain so far.
The model still trails a plain career average by 0.5 in blind conditions, but
the blind test forces every fixture to be average, which is exactly the signal
the goal term exists to use. In production the attack factor comes from real
odds and moves the goal component substantially (Guirassy: 70 goal points in a
strong attacking fixture versus 25 in a weak one). Whether that closes the gap
can only be settled forward, so both the model and a 50/50 blend with the
career average are archived each run and scored against real results.

## What this changes

1. **Do not read a single prediction as precise.** Show the range, not just the
   number. Being off by 40–50 points on one match is normal.
2. **Predictions are for ranking, not forecasting.** Comparing two players or
   two lineups is where small, repeated edges pay off over 34 matchdays.
3. **Keep shrinkage at 600** — confirmed near-optimal.
4. **Do not switch to recent-form averages** — measurably worse.
5. **The odds component is the open question.** Predictions are archived from
   now on so it can be scored against real results after each matchday.
