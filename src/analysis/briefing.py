"""Turn collected data into a markdown briefing for the decision agent."""

from datetime import datetime, timedelta

DAILY_LOGIN_BONUS = 100_000


def next_deadline(now: datetime) -> datetime:
    """First kickoff of the next matchday: Friday 20:30."""
    days_ahead = (4 - now.weekday()) % 7  # 4 = Friday
    candidate = (now + timedelta(days=days_ahead)).replace(
        hour=20, minute=30, second=0, microsecond=0
    )
    if candidate <= now:
        candidate += timedelta(days=7)
    return candidate


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


def _transfers_section(data: dict) -> str:
    transfers = data.get("recent_transfers") or []
    if not transfers:
        return "_No recent transfers in the feed._"
    mv_by_id = {p["i"]: p.get("mv") for p in data["squad"] + data["market"]}
    lines = []
    for t in transfers:
        mv = mv_by_id.get(t.get("player_id"))
        overpay = ""
        if mv and t.get("price"):
            pct = (t["price"] - mv) / mv * 100
            overpay = f" ({pct:+.1f}% vs current value {eur(mv)})"
        who = f"{t['buyer']} bought" if t.get("buyer") else f"{t.get('seller', '?')} sold"
        lines.append(f"- {t['date'][:10]}: {who} **{t['player']}** for {eur(t.get('price'))}{overpay}")
    return "\n".join(lines)


def build_briefing(data: dict, now: datetime | None = None) -> str:
    league = data["league"]
    budget = data["budget"].get("b")
    squad = data["squad"]
    team_value = sum(p.get("mv") or 0 for p in squad)
    n_starters = sum(1 for p in squad if p.get("predicted_starter"))

    now = now or datetime.now()
    deadline = next_deadline(now)
    hours_left = (deadline - now).total_seconds() / 3600
    login_days = max(0, (deadline.date() - now.date()).days)
    login_bonus = login_days * DAILY_LOGIN_BONUS

    return f"""# Kickbase Briefing — {league['n']}

## Time context
- Now: {now.strftime('%A %d.%m.%Y %H:%M')}
- **Budget deadline (first kickoff): {deadline.strftime('%A %d.%m.%Y %H:%M')}** — {hours_left:.0f}h from now
- Expected daily login bonuses until then: {login_days} × 100k = **{eur(login_bonus)}** extra budget

## My situation
- **Budget: {eur(budget)}** {"(NEGATIVE — must be ≥ 0 at the deadline above; afterwards it may go negative again)" if budget and budget < 0 else ""}
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

## Recent league transfers (what competitors actually paid)
{_transfers_section(data)}

## Next matches (predicted by ligainsider.de)
{_lineup_summary(data['lineups'])}
"""
