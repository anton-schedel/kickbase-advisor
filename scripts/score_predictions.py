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

from kickbase.client import KickbaseClient
from analysis.prediction import match_records, _decompose

ARCHIVE = Path(__file__).resolve().parents[1] / "data" / "predictions"


def main() -> None:
    project_root = Path(__file__).resolve().parents[1]
    load_dotenv(project_root / ".env")
    if not ARCHIVE.exists():
        sys.exit("No archived predictions yet — run scripts/advise.py first.")

    client = KickbaseClient(os.environ["KICKBASE_EMAIL"], os.environ["KICKBASE_PASSWORD"])
    client.login()
    league_id = client.leagues()["it"][0]["i"]

    scored: dict[int, list[dict]] = {}
    for archive_file in sorted(ARCHIVE.glob("*.json")):
        entry = json.loads(archive_file.read_text())
        matchday = entry.get("matchday")
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
                }
            )

    if not scored:
        sys.exit("No archived matchday has been played yet — nothing to score.")

    for matchday, rows in sorted(scored.items()):
        errors = [abs(r["predicted"] - r["actual"]) for r in rows]
        naive_errors = [abs(r["naive"] - r["actual"]) for r in rows if r.get("naive") is not None]
        print(f"\n=== Matchday {matchday} ({len(rows)} players) ===")
        blend_errors = [abs(r["blend"] - r["actual"]) for r in rows if r.get("blend") is not None]
        print(f"Model MAE:          {statistics.fmean(errors):.1f}")
        if naive_errors:
            print(f"ØPts baseline MAE:  {statistics.fmean(naive_errors):.1f}")
        if blend_errors:
            print(f"50/50 blend MAE:    {statistics.fmean(blend_errors):.1f}")
        rows.sort(key=lambda r: -abs(r["predicted"] - r["actual"]))
        print("\nBiggest misses:")
        for r in rows[:8]:
            print(
                f"  {r['name']:<18} predicted {r['predicted']:>5.0f}  actual {r['actual']:>5.0f}"
                f"  ({r['actual'] - r['predicted']:+.0f}, {r['minutes']}min)"
            )


if __name__ == "__main__":
    main()
