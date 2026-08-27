"""Turn collected data into a markdown briefing for the decision agent.

The briefing is built as named sections so the advisor can be run either as one
big prompt or as focused stages that each receive only the sections they need.
"""

from datetime import datetime

from analysis.deadline import DAILY_LOGIN_BONUS, next_deadline
from analysis.momentum import PHASE_URGENCY, describe as curve_describe, short as curve_short

__all__ = ["briefing_sections", "build_briefing", "compose", "next_deadline"]


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
    where = "home vs" if f.get("home") else "away at"
    return f"{where} {f.get('opponent')} ({f['p_win']*100:.0f}% win, {f['p_clean_sheet']*100:.0f}% CS)"


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
    xg = pred.get("expected_goals")
    if xg:
        text += f", xG {xg:.2f}"
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
    prob = p.get("prob")
    if prob is not None:
        labels = {1: "nailed on", 2: "very likely", 3: "uncertain", 4: "doubtful", 5: "unlikely"}
        flags.append(f"KB start: {labels.get(prob, prob)}")
    return ", ".join(flags)


def _squad_table(squad: list[dict]) -> str:
    lines = [
        "| Player | Pos | Team | Value | Curve | Δ7d | Δ30d | Season history (starts/apps) | Fixture | xBase | **Predicted pts** | Status |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for p in sorted(squad, key=lambda x: -(x.get("prediction") or {}).get("points", -999)):
        ch = p.get("mv_changes", {})
        lines.append(
            f"| {p['n']} | {p['position']} | {p.get('li_team') or p['tid']} | {eur(p.get('mv'))} "
            f"| {curve_short(p.get('mv_curve'))} | {delta(ch.get('7d'))} | {delta(ch.get('30d'))} "
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
        "| Player | Pos | Team | Price | Value | Curve | Δ30d | Season history (starts/apps) | Seller | Auction ends | Bids | Fixture | **Predicted pts** | Status |",
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
            f"| {eur(p.get('mv'))} | {curve_short(p.get('mv_curve'))} | {delta(ch.get('30d'))} "
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
            if xi.get("sold"):
                notes.append(
                    f"after the forced sale of {', '.join(p['n'] for p in xi['sold'])}; "
                    f"{xi['unconstrained_total']:.0f} if the budget allowed"
                )
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
    lines = [f"XI I can actually field: **{xi['formation']}**, projected **{xi['total']:.0f}** points"]

    if xi.get("unfundable"):
        lines.append(
            f"⚠ **No combination of sales clears the {eur(xi['deficit'])} deficit**, so this XI "
            "is not fundable as it stands — the budget has to come from somewhere else."
        )
    elif xi.get("sold"):
        sold = ", ".join(f"{p['n']} ({eur(p.get('mv'))})" for p in xi["sold"])
        lines.append(
            f"The budget is **{eur(xi['deficit'])} short** at kickoff, so this lineup already "
            f"assumes the cheapest way out in points terms: **sell {sold}** — "
            f"{eur(xi.get('raised'))} raised, which clears the deficit. "
            f"Keeping everyone would project {xi['unconstrained_total']:.0f} points, but that "
            "eleven cannot be fielded, because the budget must be ≥ 0 at the first kickoff. "
            "Any other way of clearing the deficit — buying nothing and selling different "
            "players, or winning cheaper replacements first — scores less than this unless it "
            "brings in new players."
        )
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


def _breakout_candidates(data: dict) -> str:
    """Players priced below the role they could win at their own club."""
    rows = []
    for p in data["squad"] + data["market"]:
        up = p.get("upside")
        if not up or not up.get("is_candidate"):
            continue
        owned = "mine" if p in data["squad"] else ((p.get("u") or {}).get("n") or "Kickbase")
        rows.append((up["upside_ratio"], p, up, owned))
    if not rows:
        return "_No player currently sits far enough below his club's starters to qualify._"
    rows.sort(key=lambda r: -r[0])

    lines = [
        "| Player | Pos | Club | Value | Starters at his position cost | Room | Start rating | History | Where |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    labels = {1: "nailed on", 2: "very likely", 3: "uncertain", 4: "doubtful", 5: "unlikely"}
    for ratio, p, up, owned in rows[:10]:
        peers = ", ".join(f"{q['name']} {eur(q['value'])}" for q in up["peers"][:2])
        history = "no Bundesliga record" if up["unproven"] else f"Ø{p.get('ap')}"
        lines.append(
            f"| {p['n']} | {p['position']} | {p.get('li_team') or p['tid']} | {eur(p.get('mv'))} "
            f"| {eur(up['peer_starter_value'])} ({peers}) | **{ratio:.1f}x** "
            f"| {labels.get(p.get('prob'), '?')} | {history} | {owned} |"
        )
    return "\n".join(lines)


def _curve_rows(players: list[dict], owner_label=None) -> list[str]:
    rows = []
    for p in sorted(
        players,
        key=lambda x: (
            PHASE_URGENCY.get((x.get("mv_curve") or {}).get("phase"), 9),
            -(x.get("mv") or 0),
        ),
    ):
        curve = p.get("mv_curve")
        if not curve:
            continue
        who = f" | {owner_label(p)}" if owner_label else ""
        # A prospect waiting for a role is meant to look flat, so his curve
        # must not be read as a momentum signal.
        note = ""
        if (p.get("upside") or {}).get("is_candidate"):
            note = (
                f" — role bet ({p['upside']['upside_ratio']:.1f}x room), so a flat or "
                "drifting curve is the expected wait, not a sell signal"
            )
        rows.append(
            f"| {p['n']} | {eur(p.get('mv'))} | {curve_describe(curve)}{note}{who} |"
        )
    return rows


def _value_curves(data: dict) -> str:
    """My squad ordered by how close each player is to the top of his arc."""
    header = ["| Player | Value | Curve |", "|---|---|---|"]
    mine = _curve_rows(data["squad"])
    if not mine:
        return "_No market value histories available._"

    # Market listings that are already rolling over: buying one means paying
    # today's price for tomorrow's lower value.
    cooling_market = sorted(
        (p for p in data["market"] if (p.get("mv_curve") or {}).get("sell_window_closing")),
        key=lambda p: -(p.get("mv") or 0),
    )[:12]
    out = ["**My squad** — sell the ones nearest the top of the curve first.", ""]
    out += header + mine
    if cooling_market:
        out += [
            "",
            "**Market listings whose value is already topping out** — a bid here buys a falling asset.",
            "",
            "| Player | Value | Curve | Seller |",
            "|---|---|---|---|",
        ]
        out += _curve_rows(
            cooling_market, owner_label=lambda p: (p.get("u") or {}).get("n", "Kickbase")
        )
    return "\n".join(out)


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


def briefing_sections(data: dict, now: datetime | None = None) -> dict[str, tuple[str, str]]:
    """Every part of the briefing, keyed so a stage can ask for just a few.

    Returns key -> (heading, markdown body), in reading order.
    """
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

    sections: dict[str, tuple[str, str]] = {}

    sections["time"] = (
        "Time context",
        f"""- Now: {now.strftime('%A %d.%m.%Y %H:%M')}
- **Budget deadline (first kickoff): {deadline.strftime('%A %d.%m.%Y %H:%M')}** — {hours_left:.0f}h from now
- Expected daily login bonuses until then: {login_days} × 100k = **{eur(login_bonus)}** extra budget""",
    )

    sections["me"] = (
        "My situation",
        f"""- **Budget: {eur(budget)}** {"(NEGATIVE — must be ≥ 0 at the deadline above; afterwards it may go negative again)" if budget and budget < 0 else ""}
- Team value: {eur(team_value)}
- Squad size: {len(squad)} players, {n_starters} confirmed in their club's predicted starting XI{f", {n_unknown} with no lineup published yet (unknown, not benched)" if n_unknown else ""}
- Max players per user: {data['budget'].get('mppu', 15)}""",
    )

    sections["standings"] = ("League standings (season points)", _standings(data["ranking"]))

    sections["projection"] = (
        "Matchday projection — every manager's best possible XI",
        f"""Each rival's full squad is visible, so the same prediction model is run over
all of them. This is what the coming matchday looks like if everyone fields
their strongest legal lineup. Managers with fewer than 11 players are charged
−100 per empty slot.

My own row is the XI I can actually field: if the budget is negative it already
subtracts the players I must sell to be ≥ 0 at kickoff. Rival budgets are not
visible, so their rows assume no forced sales — a rival deep in deficit will
score less than his row suggests.

{_league_projection(data)}""",
    )

    sections["my_xi"] = ("My best legal XI right now", _my_xi(data))

    sections["rival_holdings"] = (
        "Strongest players owned by rivals (not buyable on the market)",
        f"""These are locked up unless the owner lists them or accepts a direct offer.
Useful for knowing which rivals are strong where, and who to approach.

{_rival_holdings(data)}""",
    )

    sections["squad"] = (
        "My squad",
        f"""(Sorted by predicted points. "Curve" is where his market value sits on its arc — see "Value curves" below. Δ = market value change. Status from ligainsider.de: injury flags and whether the player is in his club's predicted starting XI. Season history, Fixture and Predicted pts are explained under "Scoring & prediction model".)

{_squad_table(squad)}""",
    )

    sections["market"] = (
        f"Transfer market ({len(data['market'])} listings)",
        f"""(Sorted by predicted points. Price = asking price. Players listed by "Kickbase" are blind auctions decided at the countdown; players listed by other managers are negotiations.)

{_market_table(data['market'])}""",
    )

    sections["curves"] = (
        "Value curves — the gradient, not the last delta",
        f"""Market values move in arcs: a player gets noticed, the daily rises grow, then
shrink, flatten and turn negative. The value peaks days before any single
number in the table turns red, so the signal that matters is the *gradient* —
today's daily rise measured against the rise he is coming from.

"Curve" compares the last 3 days' average daily change with the 7 days before
them. **cooling** means he is still rising but at less than half his previous
pace: that is the top of the arc forming, and the moment to sell into strength.
**topped out** means the rises have already stopped, **falling** means the
decline has begun and every further day of holding costs money. **rising** and
**accelerating** mean the climb is intact — hold, and keep collecting the daily
updates. "turns in ~Nd" extrapolates the current deceleration to the day the
rise reaches zero; it is a straight-line estimate, not a forecast, so treat 3
days as "this week" and 12 days as "no rush".

The percentage matters more than the euro figure: +40k/day on a 20M player is a
stall, the same +40k on a 2M player is a steep climb.

{_value_curves(data)}""",
    )

    sections["model"] = (
        "Scoring & prediction model",
        _model_explainer(),
    )

    sections["upside"] = (
        "Role upside — players priced below the job they could take",
        f"""A Kickbase player earns in two ways: points this weekend, and market value over
the season. This table is only about the second. It compares a player against
the team-mates he would have to displace at his own club: "Room" is what the
club's established starters in his position are worth divided by his own value,
so 2.0x means the market pays roughly double for that role at that club.

Only players who are *not* currently first choice appear here — a starter has
no role left to win. Treat a high "Room" as the size of the prize, not the
likelihood: it says nothing about whether or when the manager plays him. The
strongest version of this bet is a player the market already prices above his
club's typical player while he has no scoring record at all, because that value
is pure expectation and will re-rate fast if the role arrives.

{_breakout_candidates(data)}""",
    )

    sections["transfers"] = (
        "Recent league transfers (what competitors actually paid)",
        _transfers_section(data),
    )

    sections["fixtures"] = (
        "Next matches (predicted by ligainsider.de)",
        _lineup_summary(data["lineups"]),
    )

    return sections


def compose(sections: dict[str, tuple[str, str]], keys=None, title: str = "Kickbase Briefing") -> str:
    """Render selected sections as one markdown document."""
    chosen = keys or list(sections)
    parts = [f"# {title}"]
    for key in chosen:
        if key not in sections:
            continue
        heading, body = sections[key]
        parts.append(f"## {heading}\n{body}")
    return "\n\n".join(parts) + "\n"


def build_briefing(data: dict, now: datetime | None = None) -> str:
    sections = briefing_sections(data, now)
    return compose(sections, title=f"Kickbase Briefing — {data['league']['n']}")


def _model_explainer() -> str:
    return """Kickbase points a full-90 starter collects regardless of goals or actions:
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
from the probabilities above. The *player part* splits again. Goals and assists are
predicted from his own per-90 goal and assist rate (read from the event codes
on every match he has played, verified against Understat), scaled by how strong
his team's attack looks in this fixture — `xG` in the cell is his expected goals
for this match. Everything else — duels, passes, saves — is recovered by taking
every match he has played, subtracting the fixture and goal points he was
entitled to that day, and averaging the remainder per 90 minutes (recent season weighted double, 2.
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
with Ø6 across 30 starts."""
