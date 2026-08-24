"""Collect and join all data needed for a decision briefing."""

import os

from datetime import datetime, timezone

from kickbase.client import KickbaseClient
from ligainsider.scraper import LigainsiderScraper
from analysis.matching import map_teams, match_player
from analysis.odds import match_outlook, expected_base_points, neutral_base_points
from analysis.prediction import player_profile, predict, position_priors
from analysis.lineup import best_xi

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


def _history(performance: dict, limit: int = 3) -> list[dict]:
    """Recent seasons with appearances, starts and average — the ØPts column
    only shows the newest season, which hides bench years and division changes.
    """
    out = []
    for season in performance.get("it", []):
        played = [m for m in season.get("ph", []) if m.get("p") is not None]
        if not played:
            continue
        starts = sum(1 for m in played if m.get("st") == 5)
        out.append(
            {
                "season": season.get("ti"),
                "competition": season.get("n"),
                "apps": len(played),
                "starts": starts,
                "avg": round(sum(m["p"] for m in played) / len(played)),
            }
        )
    return out[-limit:]


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


def _next_matchday_outlooks(client, progress) -> tuple[dict, dict]:
    """Per-team fixture outlook for the next matchday, derived from odds."""
    matchdays = client.get(f"/v4/competitions/{BUNDESLIGA_COMPETITION_ID}/matchdays")["it"]
    now = datetime.now(timezone.utc)
    upcoming = None
    for day in matchdays:
        matches = day.get("it", [])
        if any(datetime.fromisoformat(m["dt"].replace("Z", "+00:00")) > now for m in matches):
            upcoming = day
            break
    if not upcoming:
        progress("WARNING: no upcoming matchday found")
        return {}, {}

    by_team, missing = {}, []
    for m in upcoming["it"]:
        odds = m.get("bo")
        kickoff = m["dt"]
        if not odds:
            missing.append(f"{m.get('t1sy')}-{m.get('t2sy')}")
            continue
        outlook = match_outlook(odds["o1"], odds["ox"], odds["o2"])
        for side, tid, opponent in (
            ("home", m["t1"], m.get("t2sy")),
            ("away", m["t2"], m.get("t1sy")),
        ):
            by_team[tid] = {
                **outlook[side],
                "opponent": opponent,
                "home": side == "home",
                "kickoff": kickoff,
            }
    if missing:
        progress(f"NOTE: no odds yet for {', '.join(missing)}")
    progress(f"Odds: matchday {upcoming['day']}, outlook for {len(by_team)} teams")
    return by_team, {"day": upcoming["day"]}


def _normalize_rival_player(player: dict) -> dict:
    """Rival squads use pi/pn where our own squad uses i/n."""
    normalized = dict(player)
    normalized["i"] = player.get("pi") or player.get("i")
    normalized["n"] = player.get("pn") or player.get("n")
    return normalized


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

    # Every rival's full squad is visible, which lets us project the whole
    # league's matchday, not just our own team.
    my_user_id = (client.user or {}).get("id")
    rivals = []
    for entry in ranking.get("us", []):
        rival_squad = client.get(f"/v4/leagues/{league_id}/managers/{entry['i']}/squad")
        players = [_normalize_rival_player(p) for p in rival_squad.get("it", [])]
        rivals.append(
            {
                "user_id": entry["i"],
                "name": entry.get("n"),
                "is_me": entry["i"] == my_user_id,
                "players": players,
            }
        )
    progress(f"Kickbase: {len(rivals)} managers, {sum(len(r['players']) for r in rivals)} owned players")

    progress("Kickbase: fetching market value histories and performance...")
    performance_cache: dict[str, dict] = {}

    def performance(player_id: str) -> dict:
        if player_id not in performance_cache:
            performance_cache[player_id] = client.player_performance(league_id, player_id)
        return performance_cache[player_id]

    for player in squad + market:
        player["position"] = POSITIONS.get(player.get("pos"), "?")
        # Only timeframe=365 returns data; shorter windows come back empty.
        history = client.player_market_value(league_id, player["i"], timeframe=365)
        player["mv_changes"] = _mv_changes(history)
        perf = performance(player["i"])
        player["stats"] = _season_stats(perf)
        player["history"] = _history(perf)
        player["profile"] = player_profile(perf, player["position"])

    progress("Kickbase: profiling rival squads...")
    for rival in rivals:
        for player in rival["players"]:
            player["position"] = POSITIONS.get(player.get("pos"), "?")
            player["profile"] = player_profile(performance(player["i"]), player["position"])

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

    # Map from the full team list, not from lineups — Ligainsider sometimes has
    # no predicted XI for a team yet, and that must not break the team mapping.
    team_map = map_teams(kb_teams, li_teams)
    unmapped = {p["tid"] for p in squad + market} - set(team_map)
    if unmapped:
        progress(f"WARNING: no Ligainsider mapping for Kickbase team ids {sorted(unmapped)}")

    lineup_by_team = {l["team"]: l for l in lineups}
    teams_with_lineup = set(lineup_by_team)
    injuries_by_team: dict[str, list] = {}
    for row in injuries:
        injuries_by_team.setdefault(row["team"], []).append(row)

    outlooks, matchday_info = _next_matchday_outlooks(client, progress)
    unmapped_fixtures = set()

    rival_players = [p for r in rivals if not r["is_me"] for p in r["players"]]
    all_players = squad + market + rival_players

    for player in all_players:
        outlook = outlooks.get(player["tid"])
        if outlook:
            player["fixture"] = outlook
            player["x_base_points"] = expected_base_points(player["position"], outlook)
            player["x_base_points_neutral"] = neutral_base_points(player["position"])
        else:
            unmapped_fixtures.add(player["tid"])
        li_team = team_map.get(player["tid"])
        player["li_team"] = li_team
        lineup = lineup_by_team.get(li_team, {})
        if li_team in teams_with_lineup:
            player["predicted_starter"] = match_player(player["n"], lineup["players"]) is not None
        else:
            # No predicted XI published for this team — unknown, NOT "benched".
            player["predicted_starter"] = None
        player["next_match"] = lineup.get("match")
        injury = match_player(player["n"], injuries_by_team.get(li_team, []))
        if injury:
            player["injury"] = {
                "status": injury["status"],
                "reason": injury["reason"],
                "news": injury["news_title"],
                "out_since": injury["out_since"],
            }

    if unmapped_fixtures:
        progress(f"NOTE: no fixture odds for team ids {sorted(unmapped_fixtures)}")

    # Predictions need the fixture, the profile and the lineup signal together.
    # Baselines come from the league's own well-sampled players, so a thin
    # record gets pulled toward what that position normally produces.
    priors = position_priors([(p["position"], p.get("profile")) for p in all_players])
    progress("Baseline pts/90 per position: " + ", ".join(f"{k} {v:.0f}" for k, v in sorted(priors.items())))

    predicted = 0
    for player in all_players:
        player["prediction"] = predict(
            player.get("profile"),
            player.get("fixture"),
            player["position"],
            player.get("predicted_starter"),
            injured=bool(player.get("injury")),
            prior=priors.get(player["position"]),
        )
        predicted += 1 if player["prediction"] else 0
    progress(f"Predictions: {predicted}/{len(all_players)} players")

    # Project the whole league: each manager's best legal XI for this matchday.
    for rival in rivals:
        players = squad if rival["is_me"] else rival["players"]
        xi = best_xi(players)
        rival["xi"] = xi
        rival["projected_points"] = xi["total"]
        rival["team_value"] = sum(p.get("mv") or 0 for p in players)
        rival["squad_size"] = len(players)
    rivals.sort(key=lambda r: -r["projected_points"])
    my_rank = next((i for i, r in enumerate(rivals, 1) if r["is_me"]), None)
    progress(f"League projection: you rank {my_rank}/{len(rivals)} for this matchday")

    return {
        "league": league,
        "budget": budget,
        "ranking": ranking,
        "squad": squad,
        "market": market,
        "injuries": injuries,
        "lineups": lineups,
        "recent_transfers": transfers,
        "matchday": matchday_info,
        "rivals": rivals,
        "my_xi": next((r["xi"] for r in rivals if r["is_me"]), None),
    }
