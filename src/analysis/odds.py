"""Turn bookmaker 1X2 odds into per-player expected base points.

The Kickbase matchdays endpoint ships bookmaker odds per match ("bo"), so we
can derive win/clean-sheet probabilities without an external odds provider.

Method: strip the bookmaker margin from the 1X2 odds, then fit an independent
Poisson goal model (lambda_home, lambda_away) that reproduces those
probabilities. Clean-sheet probability for a team is then P(opponent scores 0).
"""

import math

# Kickbase points table (us.kickbase.com/de/points-table), values a player
# collects over a full 90 minutes.
STARTING_XI_BONUS = 5
FULL_MATCH_MINUTES_BONUS = 10  # +1 per 10 min, +1 full-match bonus
WIN_POINTS = 15
LOSS_POINTS = -15
CLEAN_SHEET_POINTS = {"GK": 50, "DEF": 30, "MID": 20, "FWD": 10}

_MAX_GOALS = 10
_POISSON_CACHE: dict[tuple[float, int], float] = {}


def _poisson_pmf(lam: float, k: int) -> float:
    key = (lam, k)
    if key not in _POISSON_CACHE:
        _POISSON_CACHE[key] = math.exp(-lam) * lam**k / math.factorial(k)
    return _POISSON_CACHE[key]


def implied_probabilities(o1: float, ox: float, o2: float) -> tuple[float, float, float]:
    """1X2 odds -> true probabilities, with the bookmaker margin removed."""
    raw = (1 / o1, 1 / ox, 1 / o2)
    total = sum(raw)
    return tuple(p / total for p in raw)


def _outcome_probabilities(lh: float, la: float) -> tuple[float, float, float]:
    home = draw = away = 0.0
    for i in range(_MAX_GOALS + 1):
        pi = _poisson_pmf(lh, i)
        for j in range(_MAX_GOALS + 1):
            p = pi * _poisson_pmf(la, j)
            if i > j:
                home += p
            elif i == j:
                draw += p
            else:
                away += p
    return home, draw, away


def fit_goal_rates(p_home: float, p_draw: float, p_away: float) -> tuple[float, float]:
    """Find (lambda_home, lambda_away) whose Poisson model matches the odds."""

    def error(lh: float, la: float) -> float:
        h, d, a = _outcome_probabilities(lh, la)
        return (h - p_home) ** 2 + (d - p_draw) ** 2 + (a - p_away) ** 2

    best = (1.4, 1.2)
    best_err = float("inf")
    # Coarse sweep, then refine around the winner.
    for step, span in ((0.1, None), (0.01, 0.1)):
        if span is None:
            lh_values = [0.2 + i * step for i in range(int(3.8 / step) + 1)]
            la_values = lh_values
        else:
            lh_values = [max(0.05, best[0] - span + i * step) for i in range(int(2 * span / step) + 1)]
            la_values = [max(0.05, best[1] - span + i * step) for i in range(int(2 * span / step) + 1)]
        for lh in lh_values:
            for la in la_values:
                err = error(lh, la)
                if err < best_err:
                    best_err, best = err, (lh, la)
    return best


def match_outlook(o1: float, ox: float, o2: float) -> dict:
    """Per-team probabilities for one match with bookmaker odds."""
    p_home, p_draw, p_away = implied_probabilities(o1, ox, o2)
    lh, la = fit_goal_rates(p_home, p_draw, p_away)
    return {
        "home": {
            "p_win": p_home,
            "p_draw": p_draw,
            "p_loss": p_away,
            "p_clean_sheet": _poisson_pmf(la, 0),
            "xg_for": lh,
            "xg_against": la,
        },
        "away": {
            "p_win": p_away,
            "p_draw": p_draw,
            "p_loss": p_home,
            "p_clean_sheet": _poisson_pmf(lh, 0),
            "xg_for": la,
            "xg_against": lh,
        },
    }


def expected_base_points(position: str, outlook: dict) -> float:
    """Points a full-90 starter earns from appearance, result and clean sheet.

    Excludes goals, assists and defensive actions — that is the variable part
    a player's historical average already reflects. This is the fixture-driven
    floor, useful for comparing two players' upcoming matches.
    """
    clean_sheet = CLEAN_SHEET_POINTS.get(position, 0)
    return (
        STARTING_XI_BONUS
        + FULL_MATCH_MINUTES_BONUS
        + WIN_POINTS * outlook["p_win"]
        + LOSS_POINTS * outlook["p_loss"]
        + clean_sheet * outlook["p_clean_sheet"]
    )


def neutral_base_points(position: str) -> float:
    """Same metric for an average fixture — the yardstick for 'good draw'."""
    neutral = {"p_win": 0.40, "p_draw": 0.25, "p_loss": 0.35, "p_clean_sheet": 0.28}
    return expected_base_points(position, neutral)
