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

## Matchday 1, 2026/27 — the first real forward test

The walk-forward backtest could never measure the odds-driven half of the model,
because the API only carries bookmaker odds for upcoming matches. Matchday 1,
scored complete, is the first settlement against real results — using the last
forecast made before the Friday deadline.

| | MAE | scored on |
|---|---|---|
| **Model** | **40.7** | 34 |
| ØPts baseline | 49.6 | 34 |
| 50/50 blend | 43.2 | 34 |

The model beats a career average by 9 points of MAE, 18%. That reverses what
the historical backtest found, and the reason is instructive.

### The scoring method decided the answer

An earlier pass over this same matchday had the model *losing* at 50.4 against
the baseline's 46.1. Two flaws produced that:

**Players who never appeared were dropped.** Nine of the 44 were not in their
club's squad at all. In the data that is indistinguishable from "not played
yet" — no entry for the matchday — so the scorer skipped them. But the matchday
was over: their real outcome was zero, and a forecast that said otherwise was
wrong. Excluding them scores only the players who happened to appear, which
systematically flatters any model that over-predicts non-players.

That is precisely where the model earns its advantage. On those nine, the model
averaged 12.2 points of error; the ØPts baseline averaged **75.2**, because a
career average has no idea whether a player is in the squad. Restricted to
players who did appear, the three methods are within two points of each other
(model 44.5, baseline 46.1, blend 43.2). **The model's entire edge is knowing
who will not play.**

**The baselines were scored on different players.** A player with no season
history has no ØPts number, so the model was being averaged over 44 players and
the baseline over 34. Every comparison now runs on the same set.

### Where the remaining error comes from

Splitting by whether the selection call was right:

| Call | n | MAE |
|---|---|---|
| Selection right | 23 | 42.6 |
| Selection wrong | 9 | 66.9 |
| — of which "said start, benched" | 3 | 94.4 |

Selection is both the model's strength and its largest remaining weakness.

### Substitutes are a lottery, not an underestimate

Twelve players came off the bench. The mean signed error says the model
under-predicts them; the median says the opposite, and the median is right:

- Ten of twelve scored **less** than predicted — median error +30 (over-predicted)
- The other two returned **180** (35 min) and **238** (30 min, two goals)

Usually a small disappointment, occasionally an enormous return. Raising bench
forecasts would make the typical case worse; the answer is an honestly shaped
range, not a higher point estimate.

### The range was the real defect

Ranges bracketed the true score **16%** of the time, against the ~60% a
20th-to-80th percentile band should manage. Two holes caused it:

- A player with no Bundesliga record got **no range at all**, displayed as 0–0 —
  maximum apparent confidence exactly where the model knew least.
- Bench players were excluded by a `p_start > 0.5` gate, precisely the group
  with the fat tail.

The range is now two explicit scenarios rather than a band around the estimate,
because for most players the uncertainty is not "how well does he play" but
"does he play at all": the floor is a substitute never coming on, the ceiling is
starting and producing at his 80th percentile. Players with no record borrow the
positional spread instead of showing none.

**Coverage on the same matchday: 16% → 57%**, against a theoretical 60. The
overconfidence is gone. MAE was unchanged (42.6 → 42.4) — this fixed the
model's honesty, not its accuracy.

### Market value carries information the record cannot

Within each position, log market value correlates with per-90 action output:

| Position | correlation | n |
|---|---|---|
| MID | +0.73 | 34 |
| FWD | +0.47 | 24 |
| GK | +0.42 | 13 |
| DEF | +0.39 | 31 |

Top-quartile midfielders produce roughly twice the per-90 output of
bottom-quartile ones. A price encodes reputation, fee and expectation that an
appearance record cannot yet show — which matters most for the player the model
is blindest to: a big signing with no minutes. A thin record is now shrunk
toward what a player *at that price* produces, rather than toward the same
number for a 30M international and a 500k reserve. The effect on points is
small; it is a value signal more than a points one.

### League projection

Scored complete, against what the nine managers actually banked:

| | |
|---|---|
| MAE | 118 points on an 857 average (**14%**) |
| Pairwise ranking correct | 26/36 (**72%**) |
| Mean signed error | **+103** — the projection under-shoots |

The top call was right: AlexG projected first, finished first. The systematic
under-projection is a direct consequence of shrinkage — every individual
forecast is pulled toward the positional mean, and summing eleven conservative
forecasts compounds into a conservative team total. It does not distort the
ranking, which is what the projection is actually used for, so it is left alone
rather than fitted away on one matchday of evidence.
