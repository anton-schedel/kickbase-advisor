"""Predict a player's points for the upcoming matchday.

Idea: a Kickbase score splits into two parts.

  points = fixture part + player part

The fixture part (appearance bonus, minutes, win/loss, clean sheet) is fully
determined by the match and the position, so we can compute it exactly for any
historical match and estimate it for the next one from bookmaker odds.
Everything else — goals, assists, duels, passes, saves, cards — is the player's
own contribution. We recover it per match as a residual, average it per 90
minutes, and project it onto the upcoming fixture.

  predicted = expected fixture part + residual_per_90 * expected minutes / 90

The residual therefore carries the player's actual scoring ability, while the
fixture part carries the matchup. That is what makes a strong player in a
brutal away game rank below a modest player at home to a weak side.
"""

import math
import statistics

from analysis.odds import CLEAN_SHEET_POINTS, WIN_POINTS, LOSS_POINTS

STARTER_STATUS = 5  # "st" in the performance feed; 3/4 mean substituted in

# The "k" list on each match records which notable events happened. Codes were
# decoded by cross-checking counts against Understat's goal and assist totals
# for the 2025/26 Bundesliga — 19 of 19 players agreed exactly.
GOAL_CODE = 1
ASSIST_CODE = 3
GOAL_POINTS = {"GK": 120, "DEF": 100, "MID": 90, "FWD": 80}
ASSIST_POINTS = {"GK": 55, "DEF": 45, "MID": 35, "FWD": 35}
# Goals and assists are the biggest single swings in a score, so they are
# modelled separately and scaled by how much the fixture favours attacking.
LEAGUE_AVG_TEAM_GOALS = 1.5
GOAL_RATE_PRIOR = {"GK": 0.005, "DEF": 0.04, "MID": 0.10, "FWD": 0.25}
ASSIST_RATE_PRIOR = {"GK": 0.01, "DEF": 0.06, "MID": 0.12, "FWD": 0.12}
RATE_SHRINKAGE_MINUTES = 900
STARTING_XI_BONUS = 5
SUB_BONUS = 2
CLEAN_SHEET_RATE = {"GK": 5, "DEF": 3, "MID": 2, "FWD": 1}  # per 10 minutes

# A season in the 2. Bundesliga is a weaker signal for Bundesliga output.
SECOND_DIVISION_FACTOR = 0.85
# Older seasons still inform, but recent evidence counts double.
SEASON_WEIGHTS = [1.0, 0.5]

# How likely a player is to start / to appear at all, given the ligainsider
# lineup signal. Used only when we have no better information.
START_PRIORS = {
    True: (0.90, 0.97),  # in the predicted XI: (p_start, p_play)
    False: (0.12, 0.50),  # published lineup, he is not in it
}
SUB_MINUTES = 18  # typical minutes for someone coming off the bench
FULL_MATCH_MINUTES = 85  # a start, allowing for the usual late substitution

# Kickbase's own starting-eleven likelihood (premium-only "prob" field), a 1-5
# scale where 1 means nailed on. Validated against ligainsider's predicted XIs
# over 57 players: levels 1-2 were 100% in the XI, level 3 was 62%, levels 4-5
# were 0%. Mapped to (p_start, p_play) with the tails kept off 0 and 1, since
# 57 observations cannot justify certainty.
KICKBASE_START_PROB = {
    1: (0.95, 0.97),
    2: (0.87, 0.93),
    3: (0.60, 0.78),
    4: (0.12, 0.40),
    5: (0.04, 0.15),
}

# A per-90 rate from a handful of substitute cameos is noise: someone who
# scored 40 points in a 12-minute appearance is not a 300-point player. We
# shrink every rate toward the positional median, with the prior carrying the
# weight of roughly seven full matches. Players with a real body of minutes are
# barely moved; tiny samples collapse onto the baseline.
SHRINKAGE_MINUTES = 600
MIN_MINUTES_FOR_PRIOR = 900
FALLBACK_PRIORS = {"GK": 60.0, "DEF": 55.0, "MID": 60.0, "FWD": 60.0}


def _minutes(match: dict) -> int:
    raw = (match.get("mp") or "0'").rstrip("'")
    try:
        return int(raw)
    except ValueError:
        return 0


def _blocks(minutes: int) -> int:
    """Completed 10-minute blocks, capped at a regulation 90."""
    return min(9, minutes // 10)


def fixture_points(position: str, minutes: float, started: bool, won: bool, lost: bool, clean_sheet: bool) -> float:
    """The part of a score that follows from the match, not the player."""
    blocks = _blocks(int(minutes))
    full = minutes >= 90
    points = STARTING_XI_BONUS if started else SUB_BONUS
    points += blocks + (1 if full else 0)
    if won:
        points += WIN_POINTS
    elif lost:
        points += LOSS_POINTS
    if clean_sheet:
        rate = CLEAN_SHEET_RATE.get(position, 0)
        points += rate * blocks + (rate if full else 0)
    return points


def _decompose(match: dict, position: str) -> dict | None:
    """Split one historical match into fixture points and player residual."""
    points = match.get("p")
    minutes = _minutes(match)
    if points is None or minutes <= 0:
        return None
    own_team = match.get("pt")
    if own_team == match.get("t1"):
        scored, conceded = match.get("t1g"), match.get("t2g")
    else:
        scored, conceded = match.get("t2g"), match.get("t1g")
    if scored is None or conceded is None:
        return None
    base = fixture_points(
        position,
        minutes,
        started=match.get("st") == STARTER_STATUS,
        won=scored > conceded,
        lost=scored < conceded,
        clean_sheet=conceded == 0,
    )
    codes = match.get("k") or []
    goals = sum(1 for code in codes if code == GOAL_CODE)
    assists = sum(1 for code in codes if code == ASSIST_CODE)
    goal_points = goals * GOAL_POINTS.get(position, 0) + assists * ASSIST_POINTS.get(position, 0)
    return {
        "minutes": minutes,
        "points": points,
        # Residual after removing both the fixture and the goal/assist points,
        # so those are not counted twice when they are predicted separately.
        "residual": points - base - goal_points,
        "goals": goals,
        "assists": assists,
        "started": match.get("st") == STARTER_STATUS,
    }


def match_records(performance: dict) -> list[dict]:
    """Every scored match in chronological order, with its season context."""
    records = []
    for season in performance.get("it", []):
        for match in season.get("ph", []):
            if match.get("p") is None:
                continue
            records.append(
                {
                    "match": match,
                    "season": season.get("ti"),
                    "competition": season.get("n") or "",
                    "date": match.get("md") or "",
                }
            )
    records.sort(key=lambda r: r["date"])
    return records


def profile_from_records(records: list[dict], position: str) -> dict | None:
    """Build a profile from a chronological slice — used live and in backtests.

    Taking a prefix of the records gives exactly what was knowable before a
    given match, which is what walk-forward evaluation requires.
    """
    if not records:
        return None
    seasons_present = list(dict.fromkeys(r["season"] for r in records))
    recent = seasons_present[-len(SEASON_WEIGHTS) :]
    weight_of = {season: SEASON_WEIGHTS[i] for i, season in enumerate(reversed(recent))}

    weighted_residual = weighted_minutes = 0.0
    weighted_goals = weighted_assists = 0.0
    per90_samples: list[float] = []
    starts = appearances = scheduled = 0

    for record in records:
        weight = weight_of.get(record["season"])
        if weight is None:
            continue
        scheduled += 1
        decomposed = _decompose(record["match"], position)
        if not decomposed:
            continue
        level = SECOND_DIVISION_FACTOR if "2." in record["competition"] else 1.0
        appearances += 1
        starts += 1 if decomposed["started"] else 0
        weighted_residual += decomposed["residual"] * weight * level
        weighted_minutes += decomposed["minutes"] * weight
        weighted_goals += decomposed["goals"] * weight * level
        weighted_assists += decomposed["assists"] * weight * level
        if decomposed["minutes"] >= 60:
            per90_samples.append(decomposed["residual"] * level * 90 / decomposed["minutes"])

    if weighted_minutes <= 0:
        return None

    return {
        "residual_per90_raw": weighted_residual / weighted_minutes * 90,
        "goals_per90_raw": weighted_goals / weighted_minutes * 90,
        "assists_per90_raw": weighted_assists / weighted_minutes * 90,
        "goals": weighted_goals,
        "assists": weighted_assists,
        "minutes": weighted_minutes,
        "start_rate": starts / scheduled if scheduled else 0.0,
        "play_rate": appearances / scheduled if scheduled else 0.0,
        "matches": appearances,
        "sources": recent,
        "spread": _spread(per90_samples),
    }


def player_profile(performance: dict, position: str) -> dict | None:
    """Per-90 scoring ability and start rate, from the last seasons played."""
    return profile_from_records(match_records(performance), position)


def position_priors(profiles: list[tuple[str, dict | None]]) -> dict[str, float]:
    """Median per-90 rate per position, from players with enough minutes.

    Self-calibrating: the baseline comes from this league's own player pool
    rather than a hard-coded guess.
    """
    by_position: dict[str, list[float]] = {}
    for position, profile in profiles:
        if profile and profile["minutes"] >= MIN_MINUTES_FOR_PRIOR:
            by_position.setdefault(position, []).append(profile["residual_per90_raw"])
    priors = dict(FALLBACK_PRIORS)
    for position, rates in by_position.items():
        if len(rates) >= 3:
            priors[position] = statistics.median(rates)
    return priors


# A thin record is shrunk toward "what this position normally produces", which
# is the same number for a 30M international and a 500k reserve. The market
# disagrees, and it is right to: value correlates with per-90 output at every
# position (+0.4 to +0.7 on log value in this league's pool), because a price
# encodes reputation, transfer fee and expectation that no appearance record
# can show yet. So the baseline a player is pulled toward is set by his price.
#
# This matters most exactly where the points model is blindest: a big signing
# with no league record. Giving him the positional average guarantees an
# unremarkable forecast and hides the players whose value is about to move.
MIN_SAMPLES_FOR_VALUE_PRIOR = 8
# The fit is only allowed to move the baseline this far, so one outlier or a
# thin position cannot produce an absurd prior.
VALUE_PRIOR_BOUNDS = (0.6, 1.8)


def position_spreads(profiles: list[tuple[str, dict | None]]) -> dict[str, tuple[float, float]]:
    """How far above and below his own average a typical player at each position
    swings, as per-90 offsets.

    A player with no Bundesliga record has no percentiles of his own, so without
    this he was shown with no range at all — maximum apparent confidence exactly
    where the model knows least.
    """
    by_position: dict[str, list[tuple[float, float]]] = {}
    for position, profile in profiles:
        spread = (profile or {}).get("spread")
        if profile and spread and profile["minutes"] >= MIN_MINUTES_FOR_PRIOR:
            own = profile["residual_per90_raw"]
            by_position.setdefault(position, []).append((spread[0] - own, spread[1] - own))
    return {
        position: (
            statistics.median(low for low, _ in offsets),
            statistics.median(high for _, high in offsets),
        )
        for position, offsets in by_position.items()
        if len(offsets) >= 3
    }


def value_priors(samples: list[tuple[str, dict | None, float | None]]) -> dict[str, tuple[float, float]]:
    """Per position, how per-90 output varies with log market value.

    Returns position -> (slope, median log value), fitted by least squares over
    players with enough minutes to trust. Positions with too few samples are
    absent, and the caller falls back to the flat positional prior.
    """
    by_position: dict[str, list[tuple[float, float]]] = {}
    for position, profile, value in samples:
        if profile and value and profile["minutes"] >= MIN_MINUTES_FOR_PRIOR:
            by_position.setdefault(position, []).append(
                (math.log(value), profile["residual_per90_raw"])
            )

    fitted = {}
    for position, points in by_position.items():
        if len(points) < MIN_SAMPLES_FOR_VALUE_PRIOR:
            continue
        xs = [x for x, _ in points]
        ys = [y for _, y in points]
        mx, my = statistics.fmean(xs), statistics.fmean(ys)
        variance = sum((x - mx) ** 2 for x in xs)
        if variance <= 0:
            continue
        slope = sum((x - mx) * (y - my) for x, y in points) / variance
        fitted[position] = (slope, statistics.median(xs))
    return fitted


def prior_for(position: str, value: float | None, priors: dict, value_model: dict) -> float:
    """The per-90 baseline this player is shrunk toward, adjusted for his price."""
    flat = priors.get(position, FALLBACK_PRIORS.get(position, 55.0))
    fit = value_model.get(position)
    if not fit or not value:
        return flat
    slope, median_log = fit
    adjusted = flat + slope * (math.log(value) - median_log)
    low, high = VALUE_PRIOR_BOUNDS
    return min(max(adjusted, flat * low), flat * high)


def _shrink(observed: float, minutes: float, prior: float, weight: float = RATE_SHRINKAGE_MINUTES) -> float:
    """Pull a per-90 rate toward a baseline in proportion to how thin the sample is."""
    return (minutes * observed + weight * prior) / (minutes + weight)


def shrunk_rate(profile: dict, prior: float) -> float:
    """Blend the observed rate toward the positional baseline by sample size."""
    return _shrink(profile["residual_per90_raw"], profile["minutes"], prior, SHRINKAGE_MINUTES)


def _spread(samples: list[float]) -> tuple[float, float] | None:
    """Typical low/high per-90 residual, from the player's own distribution."""
    if len(samples) < 5:
        return None
    ordered = sorted(samples)
    lo = ordered[int(0.2 * (len(ordered) - 1))]
    hi = ordered[int(0.8 * (len(ordered) - 1))]
    return lo, hi


def predict(
    profile: dict | None,
    outlook: dict | None,
    position: str,
    predicted_starter,
    injured: bool,
    prior: float | None = None,
    start_prob: int | None = None,
    position_spread: tuple[float, float] | None = None,
) -> dict | None:
    """Expected points for the upcoming match."""
    if injured:
        return {"points": 0.0, "expected_minutes": 0.0, "p_start": 0.0, "note": "injured/suspended"}
    if not outlook:
        return None

    prior = prior if prior is not None else FALLBACK_PRIORS.get(position, 55.0)
    if not profile:
        # No Bundesliga record at all (new signing, youth player): fall back to
        # the positional baseline and say so — a guess, but a usable one.
        profile = {
            "residual_per90_raw": prior,
            "minutes": 0.0,
            "start_rate": 0.6,
            "play_rate": 0.8,
            "spread": None,
        }
        no_history = True
    else:
        no_history = False

    rate = shrunk_rate(profile, prior)
    confidence = "low" if profile["minutes"] < MIN_MINUTES_FOR_PRIOR else "ok"

    if start_prob in KICKBASE_START_PROB:
        # Kickbase's own rating is first-party and covers every player, so it
        # takes precedence over the scraped lineup.
        p_start, p_play = KICKBASE_START_PROB[start_prob]
        note = None if start_prob <= 3 else "Kickbase rates him unlikely to start"
    elif predicted_starter is None:  # no lineup published — fall back to history
        p_start, p_play = profile["start_rate"], profile["play_rate"]
        note = "no lineup published, using historical start rate"
    elif predicted_starter:
        # Trust the lineup, but let an ever-present starter score above the
        # generic prior and a rotation player stay below it.
        p_start = min(0.97, max(0.85, profile["start_rate"]))
        p_play = min(0.99, p_start + 0.05)
        note = None
    else:
        p_start = min(START_PRIORS[False][0], profile["start_rate"])
        p_play = START_PRIORS[False][1]
        note = None

    expected_minutes = p_start * 90 + max(0.0, p_play - p_start) * SUB_MINUTES

    blocks = expected_minutes / 10
    full_match_chance = p_start  # only starters usually see 90 minutes
    appearance = p_start * STARTING_XI_BONUS + max(0.0, p_play - p_start) * SUB_BONUS
    minute_points = blocks + full_match_chance
    result_points = p_play * (WIN_POINTS * outlook["p_win"] + LOSS_POINTS * outlook["p_loss"])
    cs_rate = CLEAN_SHEET_RATE.get(position, 0)
    clean_sheet_points = outlook["p_clean_sheet"] * cs_rate * (blocks + full_match_chance)
    skill_points = rate * expected_minutes / 90

    # Goals and assists: the player's own rate, scaled by how strong his team's
    # attack looks in this specific fixture (from the odds-fitted goal model).
    attack_factor = (outlook.get("xg_for") or LEAGUE_AVG_TEAM_GOALS) / LEAGUE_AVG_TEAM_GOALS
    goal_rate = _shrink(
        profile.get("goals_per90_raw", 0.0), profile["minutes"], GOAL_RATE_PRIOR.get(position, 0.1)
    )
    assist_rate = _shrink(
        profile.get("assists_per90_raw", 0.0), profile["minutes"], ASSIST_RATE_PRIOR.get(position, 0.1)
    )
    expected_goals = goal_rate * expected_minutes / 90 * attack_factor
    expected_assists = assist_rate * expected_minutes / 90 * attack_factor
    goal_points = expected_goals * GOAL_POINTS.get(position, 0) + expected_assists * ASSIST_POINTS.get(
        position, 0
    )

    total = appearance + minute_points + result_points + clean_sheet_points + skill_points + goal_points

    result = {
        "points": total,
        "expected_minutes": expected_minutes,
        "p_start": p_start,
        "fixture_part": appearance + minute_points + result_points + clean_sheet_points,
        "skill_part": skill_points,
        "goal_part": goal_points,
        "expected_goals": expected_goals,
        "expected_assists": expected_assists,
        "confidence": confidence,
        "rate_used": rate,
    }
    notes = [n for n in (note, "no Bundesliga history — positional baseline" if no_history else None) if n]
    if confidence == "low" and not no_history:
        notes.append(f"only {profile['matches']} apps — shrunk toward baseline")
    if notes:
        result["note"] = "; ".join(notes)
    # The range is two explicit scenarios rather than a band around the
    # estimate, because for most players the uncertainty is not "how well does
    # he play" but "does he play at all". A substitute's honest floor is that
    # he never comes on; his ceiling is that he starts and produces. Matchday 1
    # showed why this matters: two bench players returned 180 and 238 points
    # while the model was showing them no range whatsoever.
    spread = profile.get("spread")
    if not spread and position_spread:
        low_offset, high_offset = position_spread
        own = profile["residual_per90_raw"]
        spread = (own + low_offset, own + high_offset)

    if spread:
        offset = rate - profile["residual_per90_raw"]
        rate_low, rate_high = spread[0] + offset, spread[1] + offset

        def scenario(minutes: float, played_rate: float) -> float:
            if minutes <= 0:
                return 0.0
            started = minutes >= 60
            blocks_s = minutes / 10
            appearance_s = STARTING_XI_BONUS if started else SUB_BONUS
            minute_s = blocks_s + (1.0 if started else 0.0)
            result_s = WIN_POINTS * outlook["p_win"] + LOSS_POINTS * outlook["p_loss"]
            cs_s = outlook["p_clean_sheet"] * cs_rate * (blocks_s + (1.0 if started else 0.0))
            skill_s = played_rate * minutes / 90
            goals_s = (goal_rate * minutes / 90 * attack_factor) * GOAL_POINTS.get(position, 0)
            assists_s = (assist_rate * minutes / 90 * attack_factor) * ASSIST_POINTS.get(position, 0)
            return appearance_s + minute_s + result_s + cs_s + skill_s + goals_s + assists_s

        if p_start >= 0.85:
            result["low"] = scenario(FULL_MATCH_MINUTES, rate_low)
        elif p_play >= 0.9:
            result["low"] = scenario(SUB_MINUTES, rate_low)
        else:
            result["low"] = 0.0  # he may simply not appear
        result["high"] = scenario(FULL_MATCH_MINUTES, rate_high)

        # The range must always contain the estimate it brackets.
        result["low"] = min(result["low"], total)
        result["high"] = max(result["high"], total)
    return result
