"""Log in to Kickbase and dump league, squad, budget, and market data.

Raw responses land in data/raw/<timestamp>/, a summary is printed.

Usage: uv run scripts/dump.py
"""

import json
import sys
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv
import os

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from kickbase.client import KickbaseClient, KickbaseError


def save(out_dir: Path, name: str, payload: dict) -> None:
    path = out_dir / f"{name}.json"
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False))
    print(f"  saved {path.relative_to(out_dir.parents[1])}")


def euros(cents_or_value) -> str:
    try:
        return f"{float(cents_or_value):,.0f} €"
    except (TypeError, ValueError):
        return str(cents_or_value)


def main() -> None:
    project_root = Path(__file__).resolve().parents[1]
    load_dotenv(project_root / ".env")
    email = os.environ.get("KICKBASE_EMAIL")
    password = os.environ.get("KICKBASE_PASSWORD")
    if not email or not password:
        sys.exit("KICKBASE_EMAIL / KICKBASE_PASSWORD missing in .env")

    out_dir = project_root / "data" / "raw" / datetime.now().strftime("%Y-%m-%d_%H%M%S")
    out_dir.mkdir(parents=True)

    client = KickbaseClient(email, password)
    try:
        login_data = client.login()
    except KickbaseError as e:
        sys.exit(str(e))
    user = client.user or {}
    print(f"Logged in as: {user.get('name', email)}")
    save(out_dir, "login", login_data)

    leagues = client.leagues()
    save(out_dir, "leagues", leagues)
    league_list = leagues.get("it", [])
    if not league_list:
        sys.exit("No leagues found on this account.")

    league = league_list[0]
    league_id = league["i"]
    print(f"\nLeague: {league.get('n')} (id {league_id})")

    me = client.league_me(league_id)
    save(out_dir, "me", me)
    budget = client.league_budget(league_id)
    save(out_dir, "budget", budget)
    print(f"Budget: {euros(budget.get('b'))}")

    try:
        ranking = client.league_ranking(league_id)
        save(out_dir, "ranking", ranking)
        print("\nStandings:")
        for entry in ranking.get("us", []):
            print(f"  {entry.get('spl', entry.get('p', '?')):>3}. {entry.get('n'):<20} {entry.get('sp', entry.get('tp', ''))} pts")
    except Exception as e:
        print(f"Ranking not available: {e}")

    squad = client.squad(league_id)
    save(out_dir, "squad", squad)
    players = squad.get("it", [])
    team_value = sum(p.get("mv") or 0 for p in players)
    print(f"Team value: {euros(team_value)}")
    print(f"\nMy squad ({len(players)} players):")
    for p in players:
        print(
            f"  {p.get('n', '?'):<22} value {euros(p.get('mv')):>14}"
            f"  trend {p.get('mvt', '?')}  pts {p.get('p', p.get('tp', '?'))}"
        )

    market = client.market(league_id)
    save(out_dir, "market", market)
    listings = market.get("it", [])
    print(f"\nTransfer market ({len(listings)} listings):")
    for it in listings:
        seller = (it.get("u") or {}).get("n", "Kickbase")
        print(
            f"  {it.get('n', '?'):<22} price {euros(it.get('prc')):>14}"
            f"  mv {euros(it.get('mv')):>14}  seller: {seller}"
        )

    # Market value history for my players — the raw material for trend signals.
    mv_dir = out_dir / "market_values"
    mv_dir.mkdir()
    print("\nFetching market value history for squad players...")
    for p in players:
        pid = p.get("i")
        if not pid:
            continue
        try:
            history = client.player_market_value(league_id, pid, timeframe=365)
            (mv_dir / f"{pid}.json").write_text(json.dumps(history, ensure_ascii=False))
        except Exception as e:
            print(f"  {p.get('n', pid)}: failed ({e})")
    print(f"  saved {len(list(mv_dir.glob('*.json')))} histories to {mv_dir.relative_to(project_root)}")

    print(f"\nDone. Raw data in {out_dir.relative_to(project_root)}")


if __name__ == "__main__":
    main()
