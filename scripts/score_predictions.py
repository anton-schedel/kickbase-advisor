"""Score archived predictions against what players actually scored.

The backtest could not measure the odds-driven half of the model, because the
API only carries bookmaker odds for upcoming matches. This closes that gap
going forward: every run archives its predictions, and once a matchday is
played this compares them to the real points.

Usage: uv run scripts/score_predictions.py
"""

import json
import statistics
import sys
from pathlib import Path

from dotenv import load_dotenv
import os

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from datetime import datetime, timezone

from kickbase.client import KickbaseClient
from analysis.prediction import match_records, _decompose


def completed_matchdays(client) -> set[int]:
    """Matchdays whose last kickoff is in the past.

    Needed to tell "has not been played yet" apart from "was not in the squad".
    Both look identical in the data — no entry for that matchday — but only one
    of them is a forecast that got the answer wrong, and dropping those would
    only ever score the players who happened to appear.
    """
    now = datetime.now(timezone.utc)
    done = set()
    for day in client.get("/v4/competitions/1/matchdays")["it"]:
        kickoffs = [
            datetime.fromisoformat(m["dt"].replace("Z", "+00:00"))
            for m in day.get("it", [])
            if m.get("dt")
        ]
        if kickoffs and max(kickoffs) < now:
            done.add(day["day"])
    return done

ARCHIVE = Path(__file__).resolve().parents[1] / "data" / "predictions"


def main() -> None:
    project_root = Path(__file__).resolve().parents[1]
    load_dotenv(project_root / ".env")
    if not ARCHIVE.exists():
        sys.exit("No archived predictions yet — run scripts/advise.py first.")

    client = KickbaseClient(os.environ["KICKBASE_EMAIL"], os.environ["KICKBASE_PASSWORD"])
    client.login()
    league_id = client.leagues()["it"][0]["i"]

    # Only the last archive before kickoff counts. Scoring every run would
    # weight a player by how many times the pipeline happened to run that week
    # and score forecasts that were superseded hours later.
    latest: dict[int, Path] = {}
    for archive_file in sorted(ARCHIVE.glob("*.json")):
        matchday = json.loads(archive_file.read_text()).get("matchday")
        if matchday is not None:
            latest[matchday] = archive_file

    finished = completed_matchdays(client)
    scored: dict[int, list[dict]] = {}
    unplayed: dict[int, int] = {}
    absent: dict[int, int] = {}
    for matchday, archive_file in sorted(latest.items()):
        entry = json.loads(archive_file.read_text())
        print(f"Matchday {matchday}: scoring {archive_file.name}")
        for row in entry["predictions"]:
            records = match_records(client.player_performance(league_id, row["player_id"]))
            actual = next(
                (
                    r
                    for r in records
                    if r["match"].get("day") == matchday and r["match"].get("p") is not None
                ),
                None,
            )
            if not actual:
                if matchday not in finished:
                    # A matchday spans Friday to Sunday, so a midweek check is
                    # scoring only the games already finished.
                    unplayed[matchday] = unplayed.get(matchday, 0) + 1
                    continue
                # The matchday is over and he has no entry: he was not in the
                # squad. That is a real zero, and the forecast said otherwise.
                absent[matchday] = absent.get(matchday, 0) + 1
                scored.setdefault(matchday, []).append(
                    {
                        "name": row["name"],
                        "predicted": row["predicted"],
                        "actual": 0.0,
                        "minutes": 0,
                        "naive": row.get("naive"),
                        "blend": row.get("blend"),
                        "goals": 0,
                        "low": row.get("low"),
                        "high": row.get("high"),
                        "absent": True,
                    }
                )
                continue
            decomposed = _decompose(actual["match"], row["position"])
            if not decomposed:
                continue
            scored.setdefault(matchday, []).append(
                {
                    "name": row["name"],
                    "predicted": row["predicted"],
                    "actual": decomposed["points"],
                    "minutes": decomposed["minutes"],
                    "naive": row.get("naive"),
                    "blend": row.get("blend"),
                    "goals": decomposed["goals"],
                    "low": row.get("low"),
                    "high": row.get("high"),
                }
            )

    if not scored:
        sys.exit("No archived matchday has been played yet — nothing to score.")

    for matchday, rows in sorted(scored.items()):
        # Every baseline is scored on the SAME players. A player with no season
        # history has no ØPts number, so comparing the model over everyone
        # against a baseline over the subset it can cover would flatter the
        # model with players the baseline never got to attempt.
        comparable = [r for r in rows if r.get("naive") is not None]
        errors = [abs(r["predicted"] - r["actual"]) for r in comparable]
        naive_errors = [abs(r["naive"] - r["actual"]) for r in comparable]
        all_errors = [abs(r["predicted"] - r["actual"]) for r in rows]
        pending = unplayed.get(matchday, 0)
        print(f"\n=== Matchday {matchday} ({len(rows)} players scored) ===")
        if pending:
            print(f"⚠ {pending} more have not played yet — this matchday is incomplete.")
        missing = absent.get(matchday, 0)
        if missing:
            print(f"({missing} of them were not in the squad at all — scored as zero.)")
        blend_errors = [abs(r["blend"] - r["actual"]) for r in comparable if r.get("blend") is not None]
        print(f"Model MAE:          {statistics.fmean(errors):.1f}  (on the {len(comparable)} "
              f"with a baseline to compare against; {statistics.fmean(all_errors):.1f} over all {len(rows)})")
        if naive_errors:
            print(f"ØPts baseline MAE:  {statistics.fmean(naive_errors):.1f}")
        if blend_errors:
            print(f"50/50 blend MAE:    {statistics.fmean(blend_errors):.1f}")
        bracketed = [
            r for r in rows
            if r.get("low") is not None and r["low"] <= r["actual"] <= r["high"]
        ]
        with_range = [r for r in rows if r.get("low") is not None]
        if with_range:
            print(
                f"Range contained it: {len(bracketed)}/{len(with_range)} "
                f"({len(bracketed) / len(with_range) * 100:.0f}%)"
            )
        rows.sort(key=lambda r: -abs(r["predicted"] - r["actual"]))
        print("\nBiggest misses:")
        for r in rows[:8]:
            print(
                f"  {r['name']:<18} predicted {r['predicted']:>5.0f}  actual {r['actual']:>5.0f}"
                f"  ({r['actual'] - r['predicted']:+.0f}, {r['minutes']}min)"
            )

        # Published so the dashboard can show how the model actually did. A
        # forecast nobody checks afterwards is a horoscope.
        results_dir = project_root / "data" / "results"
        results_dir.mkdir(parents=True, exist_ok=True)
        (results_dir / f"md{matchday}.json").write_text(
            json.dumps(
                {
                    "matchday": matchday,
                    "scored": len(rows),
                    "pending": pending,
                    "absent": absent.get(matchday, 0),
                    "model_mae": round(statistics.fmean(errors), 1),
                    "compared_on": len(comparable),
                    "naive_mae": round(statistics.fmean(naive_errors), 1) if naive_errors else None,
                    "blend_mae": round(statistics.fmean(blend_errors), 1) if blend_errors else None,
                    "range_hits": len(bracketed),
                    "range_total": len(with_range),
                    "misses": [
                        {
                            "name": r["name"],
                            "predicted": round(r["predicted"]),
                            "actual": round(r["actual"]),
                            "minutes": r["minutes"],
                        }
                        for r in rows[:5]
                    ],
                },
                ensure_ascii=False,
            )
        )
        print(f"\nSaved data/results/md{matchday}.json for the dashboard")


if __name__ == "__main__":
    main()
