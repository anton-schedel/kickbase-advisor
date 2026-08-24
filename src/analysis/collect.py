"""Collect and join all data needed for a decision briefing."""

import os

from kickbase.client import KickbaseClient
from ligainsider.scraper import LigainsiderScraper
from analysis.matching import map_teams, match_player

BUNDESLIGA_COMPETITION_ID = "1"

POSITIONS = {1: "GK", 2: "DEF", 3: "MID", 4: "FWD"}


def _mv_changes(history: dict) -> dict:
    """1d/7d/30d market value deltas from a daily history."""
    points = [it["mv"] for it in history.get("it", [])]
    out = {}
    if not points:
        return out
    current = points[-1]
    for label, days in (("1d", 1), ("7d", 7), ("30d", 30)):
        if len(points) > days:
            out[label] = current - points[-1 - days]
    return out


def _season_stats(performance: dict) -> dict:
    """Total/avg points of the newest season with data, plus the previous one."""
    seasons = performance.get("it", [])
    out = {}
    for idx, key in ((-1, "current"), (-2, "previous")):
        if len(seasons) >= -idx:
            s = seasons[idx]
            played = [m for m in s.get("ph", []) if m.get("p") is not None]
            out[key] = {
                "season": s.get("ti"),
                "competition": s.get("n"),
                "total_points": played[-1].get("tp") if played else None,
                "avg_points": played[-1].get("ap") if played else None,
                "matches_with_points": len(played),
            }
    return out


def collect(progress=print) -> dict:
    client = KickbaseClient(os.environ["KICKBASE_EMAIL"], os.environ["KICKBASE_PASSWORD"])
    client.login()
    league = client.leagues()["it"][0]
    league_id = league["i"]
    progress(f"Kickbase: logged in, league '{league['n']}'")

    budget = client.league_budget(league_id)
    feed = client.get(f"/v4/leagues/{league_id}/activitiesFeed").get("af", [])
    # Type 15 = completed transfer between managers/Kickbase, trp = price paid.
    transfers = [
        {
            "player": ev["data"].get("pn"),
            "player_id": ev["data"].get("pi"),
            "buyer": ev["data"].get("byr"),
            "seller": ev["data"].get("slr"),
            "price": ev["data"].get("trp"),
            "date": ev.get("dt"),
        }
        for ev in feed
        if ev.get("t") == 15
    ]
    ranking = client.league_ranking(league_id)
    squad = client.squad(league_id)["it"]
    market = client.market(league_id)["it"]
    kb_teams = client.get(f"/v4/competitions/{BUNDESLIGA_COMPETITION_ID}/table")["it"]
    progress(f"Kickbase: squad {len(squad)}, market {len(market)}")

    progress("Kickbase: fetching market value histories and performance...")
    for player in squad + market:
        # Only timeframe=365 returns data; shorter windows come back empty.
        history = client.player_market_value(league_id, player["i"], timeframe=365)
        player["mv_changes"] = _mv_changes(history)
    for player in market:
        perf = client.player_performance(league_id, player["i"])
        player["stats"] = _season_stats(perf)

    scraper = LigainsiderScraper()
    li_teams = scraper.bundesliga_teams()
    injuries = scraper.injuries()
    progress(f"Ligainsider: {len(injuries)} injury entries")
    lineups = []
    for team in li_teams:
        lineup = scraper.predicted_lineup(team["url"])
        if lineup["players"]:
            lineup["team"] = team["name"]
            lineups.append(lineup)
    progress(f"Ligainsider: lineups for {len(lineups)} teams")

    team_map = map_teams(kb_teams, [{"name": l["team"]} for l in lineups])
    unmapped = {p["tid"] for p in squad + market} - set(team_map)
    if unmapped:
        progress(f"WARNING: no Ligainsider mapping for Kickbase team ids {sorted(unmapped)}")

    lineup_by_team = {l["team"]: l for l in lineups}
    injuries_by_team: dict[str, list] = {}
    for row in injuries:
        injuries_by_team.setdefault(row["team"], []).append(row)

    for player in squad + market:
        player["position"] = POSITIONS.get(player.get("pos"), "?")
        li_team = team_map.get(player["tid"])
        player["li_team"] = li_team
        lineup = lineup_by_team.get(li_team, {})
        starter = match_player(player["n"], lineup.get("players", []))
        player["predicted_starter"] = starter is not None
        player["next_match"] = lineup.get("match")
        injury = match_player(player["n"], injuries_by_team.get(li_team, []))
        if injury:
            player["injury"] = {
                "status": injury["status"],
                "reason": injury["reason"],
                "news": injury["news_title"],
                "out_since": injury["out_since"],
            }

    return {
        "league": league,
        "budget": budget,
        "ranking": ranking,
        "squad": squad,
        "market": market,
        "injuries": injuries,
        "lineups": lineups,
        "recent_transfers": transfers,
    }
