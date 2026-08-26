"""Value upside from a player's position within his own club's squad.

The points model answers "what will he score this weekend". It has nothing to
say about the other way a Kickbase player makes money: a squad player who wins
a starting role, whose market value then climbs toward the team-mates he now
plays alongside.

That bet has a measurable shape. Take the players a club already fields in a
position and read their values — those are the prices the market pays for that
role at that club. A player sitting below them who is close to the eleven has
room to travel; a player already valued like a starter does not, whatever his
reputation. Two supporting signals separate a genuine prospect from a squad
filler: the market pricing him well above the club's benchmark despite him not
playing (someone believes), and no scoring history to explain the price
(the value is expectation, not production).

None of this predicts when the role arrives. It sizes the prize if it does.
"""

import statistics

# A player Kickbase rates 1-2 is effectively first choice; 3 is on the edge of
# the eleven, which is where a breakout can plausibly come from.
ESTABLISHED_START_PROB = 2
CONTENDER_START_PROB = 3
# Below this there is not enough headroom for the trade to be interesting.
MIN_UPSIDE_RATIO = 1.25


def squad_benchmarks(team_squad: list[dict]) -> dict:
    """Per position: what this club's established starters are worth."""
    by_position: dict[int, list[float]] = {}
    for player in team_squad:
        prob = player.get("prob")
        value = player.get("mv")
        if not value or prob is None or prob > ESTABLISHED_START_PROB:
            continue
        by_position.setdefault(player.get("pos"), []).append(value)

    values = [p["mv"] for p in team_squad if p.get("mv")]
    return {
        "starter_value_by_position": {
            pos: statistics.median(vals) for pos, vals in by_position.items() if vals
        },
        "squad_median_value": statistics.median(values) if values else 0.0,
    }


def upside(player: dict, team_squad: list[dict], benchmarks: dict) -> dict | None:
    """How much room a player has if he displaces his club's current starters.

    Returns None when he already is one — there is no role left to win.
    """
    value = player.get("mv")
    prob = player.get("prob")
    position = player.get("pos")
    if not value or prob is None or position is None:
        return None
    if prob <= ESTABLISHED_START_PROB:
        return None  # already first choice; upside comes from form, not role

    peer_value = benchmarks["starter_value_by_position"].get(position)
    if not peer_value:
        return None

    peers = sorted(
        (
            {"name": p.get("n"), "value": p.get("mv"), "prob": p.get("prob"), "avg_points": p.get("ap")}
            for p in team_squad
            if p.get("pos") == position and p.get("mv") and p is not player
        ),
        key=lambda p: -(p["value"] or 0),
    )[:4]

    ratio = peer_value / value
    squad_median = benchmarks["squad_median_value"] or value
    return {
        "peer_starter_value": peer_value,
        "upside_ratio": ratio,
        # Priced above the club's typical player while not in the eleven: the
        # market is paying for expectation rather than for minutes.
        "priced_above_squad_median": value / squad_median if squad_median else None,
        "contender": prob <= CONTENDER_START_PROB,
        "unproven": not player.get("ap"),
        "peers": peers,
        "is_candidate": ratio >= MIN_UPSIDE_RATIO
        and prob <= CONTENDER_START_PROB
        and value >= squad_median,
    }
