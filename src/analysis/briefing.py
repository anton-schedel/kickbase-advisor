"""Turn collected data into a markdown briefing for the decision agent."""


def eur(value) -> str:
    if value is None:
        return "-"
    return f"{value / 1_000_000:.2f}M €"


def delta(value) -> str:
    if value is None:
        return "-"
    return f"{value / 1_000:+.0f}k"


def _flags(p: dict) -> str:
    flags = []
    if p.get("injury"):
        inj = p["injury"]
        flags.append(f"⚠ {inj['status']}" + (f" ({inj['reason']})" if inj.get("reason") else ""))
    flags.append("starter" if p.get("predicted_starter") else "NOT in predicted XI")
    return ", ".join(flags)


def _squad_table(squad: list[dict]) -> str:
    lines = [
        "| Player | Pos | Team | Value | Δ1d | Δ7d | Δ30d | Pts | ØPts | Status |",
        "|---|---|---|---|---|---|---|---|---|---|",
    ]
    for p in sorted(squad, key=lambda x: -x.get("mv", 0)):
        ch = p.get("mv_changes", {})
        lines.append(
            f"| {p['n']} | {p['position']} | {p.get('li_team') or p['tid']} | {eur(p.get('mv'))} "
            f"| {delta(ch.get('1d'))} | {delta(ch.get('7d'))} | {delta(ch.get('30d'))} "
            f"| {p.get('p', '-')} | {p.get('ap', '-')} | {_flags(p)} |"
        )
    return "\n".join(lines)


def _market_table(market: list[dict]) -> str:
    lines = [
        "| Player | Pos | Team | Price | Value | Δ7d | Δ30d | Last season | Seller | Status |",
        "|---|---|---|---|---|---|---|---|---|---|",
    ]
    for p in sorted(market, key=lambda x: -x.get("mv", 0)):
        ch = p.get("mv_changes", {})
        all_stats = p.get("stats") or {}
        stats = all_stats.get("current") or {}
        if stats.get("total_points") is None:  # season not started yet
            stats = all_stats.get("previous") or {}
        season = "-"
        if stats.get("total_points") is not None:
            season = (
                f"{stats['total_points']} pts (Ø{stats['avg_points']}, "
                f"{stats['season']} {stats['competition']})"
            )
        seller = (p.get("u") or {}).get("n", "Kickbase")
        lines.append(
            f"| {p['n']} | {p['position']} | {p.get('li_team') or p['tid']} | {eur(p.get('prc'))} "
            f"| {eur(p.get('mv'))} | {delta(ch.get('7d'))} | {delta(ch.get('30d'))} "
            f"| {season} | {seller} | {_flags(p)} |"
        )
    return "\n".join(lines)


def _standings(ranking: dict) -> str:
    rows = ranking.get("us", [])
    lines = []
    for i, entry in enumerate(rows, 1):
        lines.append(f"{i}. {entry.get('n')} — {entry.get('sp', entry.get('tp', 0))} pts")
    return "\n".join(lines)


def _lineup_summary(lineups: list[dict]) -> str:
    lines = []
    for l in lineups:
        lines.append(f"- **{l['team']}**: {l.get('match', '?')}")
    return "\n".join(lines)


def build_briefing(data: dict) -> str:
    league = data["league"]
    budget = data["budget"].get("b")
    squad = data["squad"]
    team_value = sum(p.get("mv") or 0 for p in squad)
    n_starters = sum(1 for p in squad if p.get("predicted_starter"))

    return f"""# Kickbase Briefing — {league['n']}

## My situation
- **Budget: {eur(budget)}** {"(NEGATIVE — must be balanced before matchday, selling required!)" if budget and budget < 0 else ""}
- Team value: {eur(team_value)}
- Squad size: {len(squad)} players, {n_starters} of them in their club's predicted starting XI
- Max players per user: {data['budget'].get('mppu', 15)}

## League standings
{_standings(data['ranking'])}

## My squad
(Δ = market value change; Pts = current season total, ØPts = average per matchday. Status from ligainsider.de: injury flags and whether the player is in his club's predicted starting XI for the next matchday.)

{_squad_table(squad)}

## Transfer market ({len(data['market'])} listings)
(Price = asking price. Players listed by "Kickbase" are free picks; players listed by other managers go to the highest bidder.)

{_market_table(data['market'])}

## Next matches (predicted by ligainsider.de)
{_lineup_summary(data['lineups'])}
"""
