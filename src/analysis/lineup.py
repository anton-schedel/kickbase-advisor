"""Pick the highest-scoring legal starting eleven from a squad.

Two versions of "best", and the difference matters. `best_xi` is the eleven a
squad could field if money were no object. `affordable_xi` is the eleven that
survives a negative budget: Kickbase requires the budget to be ≥ 0 at the first
kickoff, so a manager in deficit has to sell players before he can field
anyone, and an XI built from players he is about to sell is fiction.
"""

from itertools import combinations, product

# Kickbase requires exactly 1 goalkeeper and ten outfield players within these
# bounds. Every empty slot costs 100 points, so a short squad is penalised.
DEF_RANGE = range(3, 6)
MID_RANGE = range(2, 7)
FWD_RANGE = range(1, 4)
OUTFIELD_SLOTS = 10
EMPTY_SLOT_PENALTY = -100


def _points(player: dict) -> float:
    prediction = player.get("prediction") or {}
    return prediction.get("points", 0.0)


def formations() -> list[tuple[int, int, int]]:
    return [
        (d, m, f)
        for d, m, f in product(DEF_RANGE, MID_RANGE, FWD_RANGE)
        if d + m + f == OUTFIELD_SLOTS
    ]


def best_xi(players: list[dict]) -> dict:
    """Best legal XI by predicted points, filling short squads with penalties.

    Returns the chosen players per line, the formation, and the projected
    total including a -100 charge for any slot that cannot be filled.
    """
    by_position: dict[str, list[dict]] = {"GK": [], "DEF": [], "MID": [], "FWD": []}
    for player in players:
        by_position.get(player.get("position"), []).append(player)
    for line in by_position.values():
        line.sort(key=_points, reverse=True)

    keeper = by_position["GK"][:1]
    best = None
    for defenders, midfielders, forwards in formations():
        picked = {
            "DEF": by_position["DEF"][:defenders],
            "MID": by_position["MID"][:midfielders],
            "FWD": by_position["FWD"][:forwards],
        }
        filled = len(keeper) + sum(len(v) for v in picked.values())
        total = sum(_points(p) for p in keeper)
        total += sum(_points(p) for line in picked.values() for p in line)
        total += (11 - filled) * EMPTY_SLOT_PENALTY
        if best is None or total > best["total"]:
            best = {
                "formation": f"{defenders}-{midfielders}-{forwards}",
                "lines": {"GK": keeper, **picked},
                "total": total,
                "filled": filled,
                "empty_slots": 11 - filled,
            }
    return best


# Deeper than this and the search is describing a squad rebuild, not a forced
# sale — and every extra sale costs an XI place anyway.
MAX_FORCED_SALES = 5


def _value(player: dict) -> float:
    return player.get("mv") or 0.0


def affordable_xi(players: list[dict], budget: float) -> dict:
    """The best XI still fieldable after clearing a budget deficit.

    A negative budget must be cleared by kickoff, and the only certain way to
    clear it is selling to Kickbase at market value. So the real question is
    not "what is my best eleven" but "which players do I have to give up, and
    what is the best eleven left afterwards". Sales are chosen to protect the
    XI, not to raise the most cash.

    Returns the resulting XI plus the players it costs. With a healthy budget
    this is exactly `best_xi` and `sold` is empty.
    """
    xi = best_xi(players)
    xi["sold"] = []
    xi["deficit"] = 0.0
    xi["unconstrained_total"] = xi["total"]
    if budget >= 0:
        return xi

    deficit = -budget
    best = None
    for size in range(1, min(MAX_FORCED_SALES, len(players)) + 1):
        for combo in combinations(players, size):
            raised = sum(_value(p) for p in combo)
            if raised < deficit:
                continue
            # Only minimal sets are worth evaluating: dropping a player from a
            # set that already clears the deficit can only improve the XI.
            if size > 1 and raised - max(_value(p) for p in combo) >= deficit:
                continue
            remaining = [p for p in players if p not in combo]
            candidate = best_xi(remaining)
            # Tie-break on cash raised so we do not over-sell for nothing.
            key = (candidate["total"], -raised)
            if best is None or key > best[0]:
                best = (key, candidate, list(combo), raised)
    # Every size is searched: three cheap bench players can clear a deficit
    # that would otherwise cost the squad's best scorer.

    if best is None:
        # Nothing sellable clears the deficit inside the search depth — say so
        # rather than pretending the unconstrained eleven is available.
        xi["deficit"] = deficit
        xi["unfundable"] = True
        return xi

    _, candidate, sold, raised = best
    candidate["sold"] = sold
    candidate["deficit"] = deficit
    candidate["raised"] = raised
    candidate["unconstrained_total"] = xi["total"]
    return candidate
