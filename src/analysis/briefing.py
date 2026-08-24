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


def _fixture_cell(p: dict) -> str:
    f = p.get("fixture")
    if not f:
        return "–"
    where = "H" if f.get("home") else "A"
    return f"{where} vs {f.get('opponent')} ({f['p_win']*100:.0f}% win, {f['p_clean_sheet']*100:.0f}% CS)"


def _xpts_cell(p: dict) -> str:
    x = p.get("x_base_points")
    if x is None:
        return "–"
    neutral = p.get("x_base_points_neutral") or 0
    return f"{x:.0f} ({x - neutral:+.0f})"


def _prediction_cell(p: dict) -> str:
    pred = p.get("prediction")
    if not pred:
        return "no data"
    if pred.get("note") == "injured/suspended":
        return "**0** (out)"
    text = f"**{pred['points']:.0f}**"
    if pred.get("low") is not None:
        text += f" ({pred['low']:.0f}–{pred['high']:.0f})"
    text += f", {pred['expected_minutes']:.0f}min"
    if pred.get("confidence") == "low":
        text += " ⚠thin data"
    elif pred.get("note"):
        text += " ⚠"
    return text


def _history_cell(p: dict) -> str:
    seasons = p.get("history") or []
    if not seasons:
        return "–"
    parts = []
    for s in seasons:
        league = "2.BL" if "2." in (s["competition"] or "") else "BL"
        season = s["season"] or ""
        label = f"{season[2:4]}/{season[7:9]}" if len(season) >= 9 else season
        parts.append(f"{label} {league}: {s['starts']}st/{s['apps']}app Ø{s['avg']}")
    return "; ".join(parts)


def _flags(p: dict) -> str:
    flags = []
    if p.get("injury"):
        inj = p["injury"]
        flags.append(f"⚠ {inj['status']}" + (f" ({inj['reason']})" if inj.get("reason") else ""))
    starter = p.get("predicted_starter")
    if starter is None:
        flags.append("lineup not published yet")
    else:
        flags.append("starter" if starter else "NOT in predicted XI")
    return ", ".join(flags)


def _squad_table(squad: list[dict]) -> str:
    lines = [
        "| Player | Pos | Team | Value | Δ1d | Δ7d | Δ30d | Season history (starts/apps) | Fixture | xBase | **Predicted pts** | Status |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for p in sorted(squad, key=lambda x: -(x.get("prediction") or {}).get("points", -999)):
        ch = p.get("mv_changes", {})
        lines.append(
            f"| {p['n']} | {p['position']} | {p.get('li_team') or p['tid']} | {eur(p.get('mv'))} "
            f"| {delta(ch.get('1d'))} | {delta(ch.get('7d'))} | {delta(ch.get('30d'))} "
            f"| {_history_cell(p)} "
            f"| {_fixture_cell(p)} | {_xpts_cell(p)} | {_prediction_cell(p)} | {_flags(p)} |"
        )
    return "\n".join(lines)


def _expiry(p: dict) -> str:
    exs = p.get("exs")
    if exs is None:
        return "seller decides"  # manager-listed: no countdown
    return f"{exs / 3600:.1f}h"


def _market_table(market: list[dict]) -> str:
    lines = [
        "| Player | Pos | Team | Price | Value | Δ7d | Δ30d | Season history (starts/apps) | Seller | Auction ends | Bids | Fixture | **Predicted pts** | Status |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for p in sorted(market, key=lambda x: -(x.get("prediction") or {}).get("points", -999)):
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
            f"| {_history_cell(p)} | {seller} | {_expiry(p)} | {p.get('ofc', 0)} "
            f"| {_fixture_cell(p)} | {_prediction_cell(p)} | {_flags(p)} |"
        )
    return "\n".join(lines)


def _league_projection(data: dict) -> str:
    rivals = data.get("rivals") or []
    if not rivals:
        return "_No rival data._"
    lines = [
        "| # | Manager | Projected pts | Best XI | Squad | Team value | Notes |",
        "|---|---|---|---|---|---|---|",
    ]
    for rank, r in enumerate(rivals, 1):
        xi = r.get("xi") or {}
        notes = []
        if xi.get("empty_slots"):
            notes.append(f"**{xi['empty_slots']} empty slot(s) = {xi['empty_slots'] * -100} pts**")
        if r["is_me"]:
            notes.append("← you")
        lines.append(
            f"| {rank} | {r['name']} | **{r['projected_points']:.0f}** | {xi.get('formation', '?')} "
            f"| {r['squad_size']} | {eur(r['team_value'])} | {', '.join(notes)} |"
        )
    return "\n".join(lines)


def _rival_holdings(data: dict) -> str:
    """Who owns the strongest players — the pool that is not on the market."""
    rows = []
    for r in data.get("rivals") or []:
        if r["is_me"]:
            continue
        for p in r["players"]:
            pred = (p.get("prediction") or {}).get("points")
            if pred is not None:
                rows.append((pred, p, r["name"]))
    rows.sort(key=lambda x: -x[0])
    if not rows:
        return "_No rival holdings._"
    lines = [
        "| Player | Pos | Predicted | Value | Owner |",
        "|---|---|---|---|---|",
    ]
    for pred, p, owner in rows[:15]:
        lines.append(
            f"| {p.get('n')} | {p.get('position')} | **{pred:.0f}** | {eur(p.get('mv'))} | {owner} |"
        )
    return "\n".join(lines)


def _my_xi(data: dict) -> str:
    xi = data.get("my_xi")
    if not xi:
        return "_No lineup computed._"
    lines = [f"Best legal XI from my current squad: **{xi['formation']}**, "
             f"projected **{xi['total']:.0f}** points"]
    if xi.get("empty_slots"):
        lines.append(f"⚠ {xi['empty_slots']} slot(s) cannot be filled — that is {xi['empty_slots'] * -100} points.")
    lines.append("")
    for line_name in ("GK", "DEF", "MID", "FWD"):
        players = xi["lines"].get(line_name) or []
        if not players:
            continue
        names = ", ".join(
            f"{p['n']} ({(p.get('prediction') or {}).get('points', 0):.0f})" for p in players
        )
        lines.append(f"- **{line_name}**: {names}")
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
    n_starters = sum(1 for p in squad if p.get("predicted_starter") is True)
    n_unknown = sum(1 for p in squad if p.get("predicted_starter") is None)

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
- Squad size: {len(squad)} players, {n_starters} confirmed in their club's predicted starting XI{f", {n_unknown} with no lineup published yet (unknown, not benched)" if n_unknown else ""}
- Max players per user: {data['budget'].get('mppu', 15)}

## League standings (season points)
{_standings(data['ranking'])}

## Matchday projection — every manager's best possible XI
Each rival's full squad is visible, so the same prediction model is run over
all of them. This is what the coming matchday looks like if everyone fields
their strongest legal lineup. Managers with fewer than 11 players are charged
−100 per empty slot.

{_league_projection(data)}

## My best legal XI right now
{_my_xi(data)}

## Strongest players owned by rivals (not buyable on the market)
These are locked up unless the owner lists them or accepts a direct offer.
Useful for knowing which rivals are strong where, and who to approach.

{_rival_holdings(data)}

## My squad
(Sorted by predicted points. Δ = market value change. Status from ligainsider.de: injury flags and whether the player is in his club's predicted starting XI. Season history, Fixture and Predicted pts are explained under "Scoring & prediction model" below.)

{_squad_table(squad)}

## Transfer market ({len(data['market'])} listings)
(Sorted by predicted points. Price = asking price. Players listed by "Kickbase" are blind auctions decided at the countdown; players listed by other managers are negotiations.)

{_market_table(data['market'])}

## Scoring & prediction model
Kickbase points a full-90 starter collects regardless of goals or actions:
Startelf +5, minutes +10, **win +15 / draw 0 / loss −15**, and clean sheet
(**GK +50, DEF +30, MID +20, FWD +10**). On top come goals (GK +120, DEF +100,
MID +90, FWD +80), assists (GK +55, DEF +45, MID/FWD +35), yellow −10,
red −50, own goal −60.

**Fixture** shows home/away, opponent, and the bookmaker-implied win and
clean-sheet probability (odds come from the Kickbase API, margin removed,
fitted with a Poisson goal model).

**Predicted pts** is a full point forecast for this matchday, not a floor:

    predicted = fixture part + player part

The *fixture part* is appearance + minutes + win/loss + clean sheet, computed
from the probabilities above. The *player part* is that player's own scoring
rate — goals, assists, duels, passes, saves — recovered by taking every match
he has played, subtracting the fixture part he was entitled to that day, and
averaging the remainder per 90 minutes (recent season weighted double, 2.
Bundesliga output discounted 15%). It is then scaled by his expected minutes,
which come from the predicted lineup, or from his own historical start rate
when no lineup is published (those rows are marked ⚠).
The bracket is his typical range (20th–80th percentile of his own past
matches, scaled to this fixture) — a genuine spread, not a confidence interval.
**xBase** is the fixture part alone, kept for reference, with the bracket
showing how this matchup compares to an average one.

**Season history** gives starts/appearances and average per season, because a
single ØPts number hides bench years and division changes — a player with
Ø6 from five substitute appearances is a very different asset from a player
with Ø6 across 30 starts.

## Recent league transfers (what competitors actually paid)
{_transfers_section(data)}

## Next matches (predicted by ligainsider.de)
{_lineup_summary(data['lineups'])}
"""
