"""Where a player sits on his market value curve.

A single "+40k since yesterday" says almost nothing on its own. Kickbase values
move in arcs: a player gets noticed, the daily rises grow, then they shrink,
flatten and turn negative — the value peaks long before anyone announces it.
What matters for a sell decision is therefore not the last delta but its
*gradient*: is today's rise bigger or smaller than last week's rises?

So compare two windows. The last three days give the current daily slope; the
seven days before them give the slope he is coming from. The difference between
the two is the acceleration, and that is the early warning. A player still
rising at a quarter of his previous pace is topping out even though every
number in the table is still green, and he is the one to sell first.

Slopes are expressed both in € per day and as a share of the player's value,
because 40k/day on a 20M player is a stall while the same 40k on a 2M player is
a steep climb.
"""

# Windows: three days smooths out one odd update without lagging the turn.
RECENT_DAYS = 3
PRIOR_DAYS = 7
# The two windows' midpoints are this far apart, which converts the difference
# between the slopes into an acceleration per day.
WINDOW_GAP_DAYS = (RECENT_DAYS + PRIOR_DAYS) / 2
# Below this daily move (as a share of value) the curve counts as flat.
FLAT_PCT_PER_DAY = 0.0025
# A rise this much weaker than the one before it is a curve rolling over.
COOLING_RATIO = 0.5
ACCELERATING_RATIO = 1.25
PEAK_WINDOW_DAYS = 30
# An extrapolation past this horizon is noise, not a forecast.
MAX_TURN_HORIZON_DAYS = 21

# Ordered from "sell now" to "keep riding" — the briefing sorts by this.
PHASE_URGENCY = {
    "falling": 0,
    "topped out": 1,
    "cooling": 2,
    "flat": 3,
    "rising": 4,
    "rebounding": 5,
    "accelerating": 6,
}


def _mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def _classify(slope_recent: float, slope_prior: float, rel_recent: float) -> str:
    if rel_recent <= -FLAT_PCT_PER_DAY:
        return "falling"
    if rel_recent < FLAT_PCT_PER_DAY:
        # Flat after a climb is the top of the arc, not a resting player.
        return "topped out" if slope_prior > 0 else "flat"
    if slope_prior <= 0:
        return "rebounding"
    if slope_recent < COOLING_RATIO * slope_prior:
        return "cooling"
    if slope_recent > ACCELERATING_RATIO * slope_prior:
        return "accelerating"
    return "rising"


def value_curve(values: list[float]) -> dict | None:
    """Gradient, acceleration and phase of a daily market value series.

    `values` is chronological and ends with today. Returns None when there is
    not enough history to say anything honest about the shape.
    """
    series = [v for v in values if v]
    if len(series) < RECENT_DAYS + PRIOR_DAYS + 1:
        return None

    current = series[-1]
    deltas = [b - a for a, b in zip(series[:-1], series[1:])]
    slope_recent = _mean(deltas[-RECENT_DAYS:])
    slope_prior = _mean(deltas[-(RECENT_DAYS + PRIOR_DAYS) : -RECENT_DAYS])
    accel_per_day = (slope_recent - slope_prior) / WINDOW_GAP_DAYS
    rel_recent = slope_recent / current

    phase = _classify(slope_recent, slope_prior, rel_recent)

    # If the slope keeps shrinking at the current rate, this is when it hits
    # zero. Only meaningful while he is still rising and still decelerating.
    days_to_turn = None
    if slope_recent > 0 and accel_per_day < 0:
        estimate = slope_recent / -accel_per_day
        if estimate <= MAX_TURN_HORIZON_DAYS:
            days_to_turn = round(estimate)

    window = series[-(PEAK_WINDOW_DAYS + 1) :]
    peak = max(window)
    days_since_peak = len(window) - 1 - window.index(peak)

    return {
        "current": current,
        "slope_recent": slope_recent,
        "slope_prior": slope_prior,
        "accel_per_day": accel_per_day,
        "pct_per_day": rel_recent,
        "pct_per_day_prior": slope_prior / current,
        "phase": phase,
        "days_to_turn": days_to_turn,
        "peak": peak,
        "days_since_peak": days_since_peak,
        "off_peak_pct": (current - peak) / peak if peak else 0.0,
        # Everything above is descriptive; this is the one judgement call.
        "sell_window_closing": phase in ("falling", "topped out", "cooling"),
    }


def _per_day(value: float) -> str:
    return f"{value / 1_000:+.0f}k/d"


def short(curve: dict | None) -> str:
    """Compact cell for the wide squad/market tables."""
    if not curve:
        return "–"
    return f"{curve['phase']} {_per_day(curve['slope_recent'])}"


def describe(curve: dict | None) -> str:
    """One cell for the briefing tables: pace, phase, and what changed."""
    if not curve:
        return "–"
    text = f"{_per_day(curve['slope_recent'])} ({curve['pct_per_day'] * 100:+.2f}%), **{curve['phase']}**"
    if curve["phase"] not in ("flat", "rising"):
        text += f", was {_per_day(curve['slope_prior'])}"
    if curve["days_to_turn"] is not None:
        text += f", turns in ~{curve['days_to_turn']}d"
    if curve["off_peak_pct"] < -0.005:
        text += f", {curve['off_peak_pct'] * 100:.1f}% off {curve['days_since_peak']}d peak"
    return text
