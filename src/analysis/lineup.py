"""Pick the highest-scoring legal starting eleven from a squad."""

from itertools import product

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
