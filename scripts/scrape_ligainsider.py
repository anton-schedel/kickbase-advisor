"""Scrape ligainsider.de: injuries and predicted lineups for all Bundesliga teams.

Raw results land in data/raw/<timestamp>/ligainsider/, a summary is printed.

Usage: uv run scripts/scrape_ligainsider.py
"""

import json
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ligainsider.scraper import LigainsiderScraper


def main() -> None:
    project_root = Path(__file__).resolve().parents[1]
    out_dir = project_root / "data" / "raw" / datetime.now().strftime("%Y-%m-%d_%H%M%S") / "ligainsider"
    out_dir.mkdir(parents=True)

    scraper = LigainsiderScraper()

    teams = scraper.bundesliga_teams()
    (out_dir / "teams.json").write_text(json.dumps(teams, indent=2, ensure_ascii=False))
    print(f"Bundesliga teams: {len(teams)}")

    injuries = scraper.injuries()
    (out_dir / "injuries.json").write_text(json.dumps(injuries, indent=2, ensure_ascii=False))
    print(f"\nInjuries/suspensions: {len(injuries)} players affected")
    by_status: dict[str, int] = {}
    for row in injuries:
        by_status[row["status"] or "?"] = by_status.get(row["status"] or "?", 0) + 1
    for status, count in sorted(by_status.items(), key=lambda kv: -kv[1]):
        print(f"  {status}: {count}")

    print(f"\nFetching predicted lineups for {len(teams)} teams...")
    lineups = []
    for team in teams:
        lineup = scraper.predicted_lineup(team["url"])
        lineup["team"] = team["name"]
        # The table page can list stale teams (e.g. relegated last season);
        # they have no upcoming match and no lineup — skip them.
        if not lineup["players"]:
            print(f"  {team['name']:<28} skipped (no lineup — not in current Bundesliga?)")
            continue
        lineups.append(lineup)
        print(f"  {team['name']:<28} {len(lineup['players'])} players  ({lineup['match'] or 'no match info'})")
    (out_dir / "lineups.json").write_text(json.dumps(lineups, indent=2, ensure_ascii=False))
    print(f"\nLineups saved for {len(lineups)} teams")

    print(f"\nDone. Raw data in {out_dir.relative_to(project_root)}")


if __name__ == "__main__":
    main()
