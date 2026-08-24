"""Walk-forward backtest of the points prediction model.

For every historical match we rebuild the player's profile from his earlier
matches only, predict that match, and compare against what he actually scored.
No information from the match itself (or later ones) enters the profile.

The fixture part is computed from the real result, because the API carries
bookmaker odds only for the next couple of matchdays — there is no way to
replay historical odds. So this measures the *learned* half of the model: does
a player's past scoring rate predict his future scoring rate, and does
shrinking thin samples help? The odds half has to be judged forward, once
results start arriving.

Baselines are given the same actual minutes and, where noted, the same actual
fixture, so the comparison isolates one ingredient at a time.

Usage:
  uv run scripts/backtest.py            # evaluate with current settings
  uv run scripts/backtest.py --sweep    # also tune the shrinkage constant
"""

import json
import statistics
import sys
from pathlib import Path

from dotenv import load_dotenv
import os

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from kickbase.client import KickbaseClient
from analysis import prediction as P

MIN_PRIOR_APPEARANCES = 5  # need some history before a prediction is meaningful
CACHE = Path(__file__).resolve().parents[1] / "data" / "cache" / "performance"


def load_players(progress=print) -> list[dict]:
    """Every player we can see: our squad, the market, and all rival squads."""
    project_root = Path(__file__).resolve().parents[1]
    load_dotenv(project_root / ".env")
    client = KickbaseClient(os.environ["KICKBASE_EMAIL"], os.environ["KICKBASE_PASSWORD"])
    client.login()
    league_id = client.leagues()["it"][0]["i"]
    positions = {1: "GK", 2: "DEF", 3: "MID", 4: "FWD"}

    seen: dict[str, dict] = {}
    for player in client.squad(league_id)["it"] + client.market(league_id)["it"]:
        seen[player["i"]] = {"id": player["i"], "name": player["n"], "position": positions.get(player.get("pos"), "?")}
    for entry in client.league_ranking(league_id).get("us", []):
        squad = client.get(f"/v4/leagues/{league_id}/managers/{entry['i']}/squad")
        for player in squad.get("it", []):
            pid = player.get("pi")
            if pid and pid not in seen:
                seen[pid] = {"id": pid, "name": player.get("pn"), "position": positions.get(player.get("pos"), "?")}

    CACHE.mkdir(parents=True, exist_ok=True)
    players = []
    for i, player in enumerate(seen.values(), 1):
        cached = CACHE / f"{player['id']}.json"
        if cached.exists():
            performance = json.loads(cached.read_text())
        else:
            performance = client.player_performance(league_id, player["id"])
            cached.write_text(json.dumps(performance))
        player["records"] = P.match_records(performance)
        players.append(player)
        if i % 40 == 0:
            progress(f"  loaded {i}/{len(seen)}")
    return players


def positional_priors(players: list[dict]) -> dict[str, float]:
    profiles = [(p["position"], P.profile_from_records(p["records"], p["position"])) for p in players]
    return P.position_priors(profiles)


NEUTRAL_FIXTURE = {"p_win": 0.40, "p_draw": 0.25, "p_loss": 0.35, "p_clean_sheet": 0.28}


def evaluate(players: list[dict], priors: dict[str, float], shrinkage: float) -> dict:
    """Walk forward through every player's career, scoring each prediction.

    Two families of comparison:
      *blind*  — nothing about the match is known, which is production reality
                 minus the odds signal. This is the fair test against ØPts.
      *oracle* — the real result and minutes are handed to the model. Useful
                 only as a ceiling on what perfect fixture knowledge buys.
    """
    blind_keys = (
        "blind_model",
        "blind_position_only",
        "naive_avg",
        "naive_recent",
        "blend_50",
        "blend_30",
    )
    oracle_keys = ("model", "no_shrink", "position_only")
    errors: dict[str, list[float]] = {k: [] for k in blind_keys + oracle_keys}
    rate_errors: dict[str, list[float]] = {"shrunk": [], "raw": [], "position": []}
    by_sample: dict[str, list[float]] = {"thin": [], "rich": []}
    actuals = []

    for player in players:
        position = player["position"]
        prior = priors.get(position, 55.0)
        records = player["records"]
        for index in range(len(records)):
            decomposed = P._decompose(records[index]["match"], position)
            if not decomposed or decomposed["minutes"] < 20:
                continue
            past = records[:index]
            profile = P.profile_from_records(past, position)
            if not profile or profile["matches"] < MIN_PRIOR_APPEARANCES:
                continue

            minutes = decomposed["minutes"]
            actual = decomposed["points"]
            fixture_part = actual - decomposed["residual"]
            scale = minutes / 90

            shrunk = (profile["minutes"] * profile["residual_per90_raw"] + shrinkage * prior) / (
                profile["minutes"] + shrinkage
            )
            past_points = [
                P._decompose(r["match"], position) for r in past
            ]
            past_points = [d["points"] for d in past_points if d]
            naive = statistics.fmean(past_points) if past_points else prior

            # Blind: only what was knowable beforehand, with no odds available
            # for historical matches so every fixture is treated as average.
            p_start = profile["start_rate"]
            expected_minutes = p_start * 90 + max(0.0, profile["play_rate"] - p_start) * P.SUB_MINUTES
            blind_scale = expected_minutes / 90
            blind_fixture = P.fixture_points(
                position, expected_minutes, started=p_start >= 0.5, won=False, lost=False, clean_sheet=False
            )
            blind_fixture += P.WIN_POINTS * NEUTRAL_FIXTURE["p_win"] + P.LOSS_POINTS * NEUTRAL_FIXTURE["p_loss"]
            blind_fixture += NEUTRAL_FIXTURE["p_clean_sheet"] * P.CLEAN_SHEET_RATE.get(position, 0) * (
                expected_minutes / 10
            )

            recent_points = past_points[-10:] or past_points
            naive_recent = statistics.fmean(recent_points) if recent_points else prior
            blind_model = blind_fixture + shrunk * blind_scale

            predictions = {
                "blind_model": blind_model,
                "blind_position_only": blind_fixture + prior * blind_scale,
                "naive_avg": naive,
                "naive_recent": naive_recent,
                "blend_50": 0.5 * blind_model + 0.5 * naive,
                "blend_30": 0.3 * blind_model + 0.7 * naive,
                "model": fixture_part + shrunk * scale,
                "no_shrink": fixture_part + profile["residual_per90_raw"] * scale,
                "position_only": fixture_part + prior * scale,
            }
            for name, value in predictions.items():
                errors[name].append(abs(value - actual))

            # Pure test of the learned component: predicting the player's own
            # per-90 output, with no fixture involvement whatsoever.
            actual_rate = decomposed["residual"] * 90 / minutes
            rate_errors["shrunk"].append(abs(shrunk - actual_rate))
            rate_errors["raw"].append(abs(profile["residual_per90_raw"] - actual_rate))
            rate_errors["position"].append(abs(prior - actual_rate))

            bucket = "thin" if profile["minutes"] < P.MIN_MINUTES_FOR_PRIOR else "rich"
            by_sample[bucket].append(abs(predictions["blind_model"] - actual))
            actuals.append(actual)

    def summarize(values: list[float]) -> dict:
        return {"mae": statistics.fmean(values), "n": len(values)}

    return {
        "methods": {name: summarize(values) for name, values in errors.items() if values},
        "rates": {name: summarize(values) for name, values in rate_errors.items() if values},
        "by_sample": {name: summarize(values) for name, values in by_sample.items() if values},
        "actual_mean": statistics.fmean(actuals) if actuals else 0,
        "actual_sd": statistics.pstdev(actuals) if len(actuals) > 1 else 0,
    }


BLIND_KEYS = ("blind_model", "blind_position_only", "naive_avg", "naive_recent", "blend_50", "blend_30")


def main() -> None:
    print("Loading player histories (cached after the first run)...")
    players = load_players()
    priors = positional_priors(players)
    total_matches = sum(len(p["records"]) for p in players)
    print(f"{len(players)} players, {total_matches} recorded matches")
    print("Positional baselines pts/90: " + ", ".join(f"{k} {v:.0f}" for k, v in sorted(priors.items())))

    result = evaluate(players, priors, P.SHRINKAGE_MINUTES)
    n = result["methods"]["model"]["n"]
    print(f"\nEvaluated {n} predictions (walk-forward, no lookahead)")
    print(f"Actual points: mean {result['actual_mean']:.0f}, sd {result['actual_sd']:.0f}\n")

    labels = {
        "blind_model": "Model, blind (no match info) — production-like",
        "blind_position_only": "Position baseline, blind (ignores who he is)",
        "naive_avg": "Player's average so far (what ØPts shows)",
        "naive_recent": "Player's average over his last 10 matches",
        "blend_50": "Blend: 50% model + 50% career average",
        "blend_30": "Blend: 30% model + 70% career average",
        "model": "Model + actual result/minutes",
        "no_shrink": "Same, without shrinkage",
        "position_only": "Position baseline + actual result/minutes",
    }
    print("FAIR TEST — nothing about the match is known (as in production, minus odds):")
    blind = sorted(
        ((k, v) for k, v in result["methods"].items() if k in BLIND_KEYS),
        key=lambda kv: kv[1]["mae"],
    )
    best = blind[0][1]["mae"]
    print(f"  {'method':<48}{'MAE':>8}{'vs best':>10}")
    for name, stats in blind:
        print(f"  {labels[name]:<48}{stats['mae']:>8.1f}{stats['mae'] - best:>+10.1f}")

    print("\nCEILING — the match result and minutes are handed to the model:")
    oracle = sorted(
        ((k, v) for k, v in result["methods"].items() if k not in BLIND_KEYS),
        key=lambda kv: kv[1]["mae"],
    )
    for name, stats in oracle:
        print(f"  {labels[name]:<48}{stats['mae']:>8.1f}")

    print("\nPURE LEARNED PART — predicting the player's own per-90 output:")
    rate_labels = {"shrunk": "Shrunk player rate", "raw": "Raw player rate", "position": "Position baseline"}
    for name, stats in sorted(result["rates"].items(), key=lambda kv: kv[1]["mae"]):
        print(f"  {rate_labels[name]:<48}{stats['mae']:>8.1f}")

    print("\nBlind-model error by how much history the player had:")
    for bucket, stats in result["by_sample"].items():
        label = "thin (<900 min)" if bucket == "thin" else "rich (>=900 min)"
        print(f"  {label:<20} MAE {stats['mae']:.1f}  (n={stats['n']})")

    if "--sweep" in sys.argv:
        print("\nShrinkage sweep (minutes of prior weight):")
        for shrinkage in (0, 150, 300, 600, 900, 1500, 3000):
            swept = evaluate(players, priors, shrinkage)
            marker = "  <- current" if shrinkage == P.SHRINKAGE_MINUTES else ""
            print(
                f"  {shrinkage:>5} min  blind MAE {swept['methods']['blind_model']['mae']:.2f}"
                f"   rate MAE {swept['rates']['shrunk']['mae']:.2f}{marker}"
            )


if __name__ == "__main__":
    main()
