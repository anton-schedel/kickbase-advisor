"""Render the latest briefing data + advice into a static single-file page."""

import html
import re
from datetime import datetime

import markdown


PLAYER_CDN = "https://kickbase.b-cdn.net/"


def eur_m(value) -> str:
    if value is None:
        return "–"
    return f"{value / 1_000_000:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".") + " M€"


def delta_k(value) -> str:
    if value is None:
        return ""
    return f"{value / 1_000:+,.0f}k".replace(",", ".")


def _trend_cell(value) -> str:
    if value is None:
        return "<td class='num'></td>"
    cls = "up" if value > 0 else "down" if value < 0 else ""
    return f"<td class='num {cls}'>{delta_k(value)}</td>"


# The 7-day number says how far he moved; the phase says whether the move is
# still accelerating or already rolling over. Amber is the useful one: still
# green, but the rises are shrinking.
PHASE_CLASS = {
    "accelerating": "up",
    "rising": "up",
    "rebounding": "up",
    "flat": "",
    "cooling": "warn",
    "topped out": "warn",
    "falling": "down",
}


def _curve_cell(p: dict, weekly) -> str:
    curve = p.get("mv_curve")
    if not curve:
        return _trend_cell(weekly)
    cls = "up" if (weekly or 0) > 0 else "down" if (weekly or 0) < 0 else ""
    phase_cls = PHASE_CLASS.get(curve["phase"], "")
    title = (
        f"last 3 days {curve['slope_recent'] / 1000:+.0f}k/day "
        f"({curve['pct_per_day'] * 100:+.2f}%/day), "
        f"7 days before that {curve['slope_prior'] / 1000:+.0f}k/day"
    )
    if curve["days_to_turn"] is not None:
        title += f" — rise reaches zero in about {curve['days_to_turn']} days"
    return (
        f"<td class='num {cls}' title='{html.escape(title)}'>{delta_k(weekly)}"
        f"<span class='sub {phase_cls}'>{curve['phase']}</span></td>"
    )


def _status_cell(p: dict) -> str:
    if p.get("injury"):
        inj = p["injury"]
        label = inj.get("status") or "verletzt"
        return f"<td class='status out' title='{html.escape(inj.get('news') or '')}'>✚ {html.escape(label)}</td>"
    prob = p.get("prob")
    if prob is not None:
        # Kickbase's own 1-5 starting likelihood, 1 = nailed on.
        labels = {1: "nailed on", 2: "very likely", 3: "uncertain", 4: "doubtful", 5: "unlikely"}
        cls = "in" if prob <= 2 else ("bench" if prob >= 4 else "")
        return f"<td class='status {cls}' title='Kickbase start rating: {labels.get(prob, prob)}'>{'XI' if prob <= 2 else ('?' if prob == 3 else 'OUT')}</td>"
    starter = p.get("predicted_starter")
    if starter is None:
        return "<td class='status bench' title='Ligainsider has not published this lineup yet'>?</td>"
    if starter:
        return "<td class='status in'>XI</td>"
    return "<td class='status bench'>Bank</td>"


def _pred_cell(p: dict) -> str:
    pred = p.get("prediction")
    if not pred:
        return "<td class='num'>–</td>"
    thin = " *" if pred.get("confidence") == "low" else ""
    title = f"{pred['expected_minutes']:.0f} min expected"
    if pred.get("note"):
        title += f" — {pred['note']}"
    return f"<td class='num pred' title='{html.escape(title)}'>{pred['points']:.0f}{thin}</td>"


def _scored_label(results: dict) -> str:
    """Players scored, and how many the baselines could be compared on.

    A player with no season history has no ØPts number, so the baseline columns
    cover fewer players than the model does — worth saying rather than implying
    all three ran on the same 44.
    """
    scored = results.get("scored")
    compared = results.get("compared_on")
    if compared and compared != scored:
        return f"{scored}<span class='scsub'>{compared} compared</span>"
    return str(scored)


def _scorecard(results: dict | None) -> str:
    """How the last matchday's forecasts actually turned out.

    A prediction nobody checks afterwards is a horoscope, so the page carries
    its own report card — including the baseline it has to beat.
    """
    if not results:
        return ""
    hits, total = results.get("range_hits", 0), results.get("range_total", 0)
    # Predictions archived before ranges were stored have nothing to score, so
    # the tile is left out rather than shown empty.
    coverage = f"{hits / total * 100:.0f}%" if total else None
    best = min(
        (v for v in (results.get("model_mae"), results.get("naive_mae"), results.get("blend_mae")) if v),
        default=None,
    )

    def cell(label: str, value, unit: str = "") -> str:
        if value is None:
            return ""
        win = " win" if best is not None and value == best and unit else ""
        return (
            f"<div class='sc'><div class='sclabel'>{label}</div>"
            f"<div class='scnum{win}'>{value}{unit}</div></div>"
        )

    misses = "".join(
        f"<tr><td class='name'>{html.escape(m['name'])}"
        f"<span class='sub'>{m['minutes']} min played</span></td>"
        f"<td class='num'>{m['predicted']}</td>"
        f"<td class='num pred'>{m['actual']}</td>"
        f"<td class='num {'up' if m['actual'] > m['predicted'] else 'down'}'>"
        f"{m['actual'] - m['predicted']:+d}</td></tr>"
        for m in results.get("misses", [])
    )
    pending = results.get("pending") or 0
    caveat = (
        f"<p class='note warnbox'>Incomplete — {pending} more players from this matchday "
        "have not kicked off yet, so every number here can still move.</p>"
        if pending
        else ""
    )
    return f"""<h2>Model check — matchday {results.get('matchday')}</h2>
<p class="note">Average error per player against what they really scored, on the last forecast
made before kickoff. Lower is better; the baselines are what the model has to beat.</p>
{caveat}
<div class="scorecard">
{cell("Model", results.get("model_mae"), " MAE")}
{cell("ØPts baseline", results.get("naive_mae"), " MAE")}
{cell("50/50 blend", results.get("blend_mae"), " MAE")}
{cell("Range held", coverage)}
{cell("Players", _scored_label(results))}
</div>
<div class="tablewrap"><table class="data">
<tr class="hdr"><th>Biggest misses</th><th class="num">said</th><th class="num">scored</th><th class="num">off by</th></tr>
{misses}
</table></div>"""


def _forced_sales_note(xi: dict | None) -> str:
    """Why the pitch is missing players you still own."""
    if not xi:
        return ""
    if xi.get("unfundable"):
        return (
            f"<p class='note warnbox'>Budget is {eur_m(xi['deficit'])} short at kickoff and no "
            "combination of sales clears it — this lineup is not fundable as it stands.</p>"
        )
    if not xi.get("sold"):
        return ""
    sold = ", ".join(f"{html.escape(p['n'])} ({eur_m(p.get('mv'))})" for p in xi["sold"])
    return (
        f"<p class='note warnbox'>Budget is {eur_m(xi['deficit'])} short at kickoff, so this XI "
        f"already assumes you sell <strong>{sold}</strong> — the cheapest way out in points. "
        f"Keeping everyone would project {xi['unconstrained_total']:.0f}, but that eleven cannot "
        "be fielded.</p>"
    )


def _pitch(xi: dict | None) -> str:
    """Pre-match style lineup graphic: position lines drawn on a pitch."""
    if not xi:
        return "<p class='muted'>No lineup available.</p>"

    # Attacking upward, as pre-match graphics are drawn: keeper at the bottom.
    line_order = ["FWD", "MID", "DEF", "GK"]
    rows = []
    for line_name in line_order:
        players = xi["lines"].get(line_name) or []
        if not players:
            continue
        cells = []
        for p in players:
            pred = (p.get("prediction") or {}).get("points")
            fixture = p.get("fixture") or {}
            # "vs" for a home match, "at" for an away one — two words rather
            # than a word and a symbol, so the pair reads consistently.
            opponent = (
                f"{'vs' if fixture.get('home') else 'at'} {fixture.get('opponent')}"
                if fixture
                else ""
            )
            prediction = p.get("prediction") or {}
            thin = prediction.get("confidence") == "low"
            spread = ""
            if prediction.get("low") is not None:
                spread = f"<div class='pr'>{prediction['low']:.0f}–{prediction['high']:.0f}</div>"
            # Player photos come from Kickbase's public CDN — no account needed.
            photo = p.get("pim")
            face = (
                f"<img class='face' src='{PLAYER_CDN}{html.escape(photo)}' alt='' loading='lazy'>"
                if photo
                else "<div class='face blank'></div>"
            )
            cells.append(
                "<div class='pp'>"
                f"<div class='shirt {line_name.lower()}'>{face}"
                f"<span class='badge'>{pred:.0f}{'*' if thin else ''}</span></div>"
                f"<div class='pn'>{html.escape(p.get('n') or '')}</div>"
                f"{spread}"
                f"<div class='po'>{html.escape(opponent)}</div>"
                "</div>"
            )
        rows.append(f"<div class='prow'>{''.join(cells)}</div>")

    empty = xi.get("empty_slots") or 0
    if empty:
        cells = "".join(
            "<div class='pp'><div class='shirt empty'>−100</div>"
            "<div class='pn'>empty</div><div class='po'>penalty</div></div>"
            for _ in range(empty)
        )
        # Shown at the attacking end, above the outfield lines.
        rows.insert(0, f"<div class='prow'>{cells}</div>")

    return (
        f"<div class='pitch'>{''.join(rows)}</div>"
        f"<div class='pitchfoot'><span>{xi['formation']}</span>"
        f"<span><strong>{xi['total']:.0f}</strong> projected points</span></div>"
    )


def _rival_rows(rivals: list[dict]) -> str:
    rows = []
    for rank, r in enumerate(rivals, 1):
        xi = r.get("xi") or {}
        note = f"{xi['empty_slots']} empty" if xi.get("empty_slots") else xi.get("formation", "")
        cls = " me" if r.get("is_me") else ""
        rows.append(
            f"<tr class='rival{cls}'>"
            f"<td class='rank'>{rank}</td>"
            f"<td class='name'>{html.escape(r.get('name') or '')}"
            f"<span class='sub'>{html.escape(note)} · {r.get('squad_size', 0)} players</span></td>"
            f"<td class='num'>{eur_m(r.get('team_value'))}</td>"
            f"<td class='num pred'>{r.get('projected_points', 0):.0f}</td>"
            "</tr>"
        )
    return "\n".join(rows)


def _squad_rows(squad: list[dict]) -> str:
    rows = []
    for p in sorted(squad, key=lambda x: -(x.get("prediction") or {}).get("points", -999)):
        ch = p.get("mv_changes", {})
        fixture = p.get("fixture") or {}
        opponent = (
            f"{'H' if fixture.get('home') else 'A'} {fixture.get('opponent')}"
            if fixture
            else ""
        )
        rows.append(
            "<tr>"
            f"<td class='name'>{html.escape(p['n'])}<span class='sub'>{p['position']} · {html.escape(p.get('li_team') or '')} · {html.escape(opponent)}</span></td>"
            f"<td class='num'>{eur_m(p.get('mv'))}</td>"
            + _curve_cell(p, ch.get("7d"))
            + _pred_cell(p)
            + _status_cell(p)
            + "</tr>"
        )
    return "\n".join(rows)


def _market_rows(market: list[dict], limit: int = 12) -> str:
    interesting = sorted(
        market, key=lambda p: -(p.get("prediction") or {}).get("points", -999)
    )[:limit]
    rows = []
    for p in interesting:
        ch = p.get("mv_changes", {})
        seller = (p.get("u") or {}).get("n", "Kickbase")
        rows.append(
            "<tr>"
            f"<td class='name'>{html.escape(p['n'])}<span class='sub'>{p['position']} · {html.escape(p.get('li_team') or '')} · {html.escape(seller)}</span></td>"
            f"<td class='num'>{eur_m(p.get('prc'))}</td>"
            + _curve_cell(p, ch.get("7d"))
            + _pred_cell(p)
            + _status_cell(p)
            + "</tr>"
        )
    return "\n".join(rows)


def _deadline_block(data: dict, generated_at: datetime) -> str:
    """Countdown to the first kickoff — the moment the budget must be >= 0."""
    kickoffs = [
        p["fixture"]["kickoff"]
        for p in data.get("squad", [])
        if (p.get("fixture") or {}).get("kickoff")
    ]
    if not kickoffs:
        return ""
    first = min(kickoffs)
    kickoff = datetime.fromisoformat(first.replace("Z", "+00:00")).replace(tzinfo=None)
    hours = (kickoff - generated_at).total_seconds() / 3600
    if hours < 0:
        return ""
    when = f"{hours / 24:.1f} days" if hours >= 48 else f"{hours:.0f} hours"
    return (
        "<div><div class='label'>Budget deadline</div>"
        f"<div class='hero-num'>{when}</div>"
        f"<div class='deadline muted'>{kickoff.strftime('%a %d.%m. %H:%M')} first kickoff</div></div>"
    )


# Occasionally a stage opens by narrating how it is answering rather than
# answering. The prompts now forbid it; this catches the archives written
# before that, and can be deleted once none are left on the page.
NARRATION_RE = re.compile(
    r"\A.{0,300}?(?:no skill applies|using no skill|advisory read|not a code task)"
    r".*?(?:\n\s*\n|\Z)",
    re.IGNORECASE | re.DOTALL,
)
SUBHEADING_RE = re.compile(r"^#{1,4}\s+", re.MULTILINE)


def _clean_stage_body(body: str, title: str) -> str:
    words = re.sub(r"[^\w\s]", " ", title.lower()).split()

    def repeats_title(line: str) -> bool:
        text = re.sub(r"[^\w\s]", " ", line.lower())
        return all(word in text for word in words)

    kept = [
        line
        for line in body.splitlines()
        # A heading that restates the section title shows it twice, with or
        # without an "A." prefix or a date glued on the end.
        if not (line.lstrip().startswith("#") and repeats_title(line))
    ]
    body = "\n".join(kept).strip()

    body = NARRATION_RE.sub("", body, count=1)
    # Everything a stage emitted is a sub-part of this section. The "A. / B. /
    # C." lettering is scaffolding from the output spec and means nothing to a
    # reader, so the label stands on its own — numbers stay, because those
    # enumerate real things like the buy targets.
    body = re.sub(r"^(#{1,3})\s+[A-Z]\.\s+", r"\1 ", body.strip(), flags=re.MULTILINE)
    return re.sub(r"^#{1,3}\s+", "#### ", body, flags=re.MULTILINE)


SECTION_RE = re.compile(r"^##\s+\d+\.\s+(.+?)\s*$", re.MULTILINE)


def _advice_parts(advice_md: str) -> list[tuple[str, str]]:
    """Split the assembled advice into its numbered sections.

    Each stage writes its own "A. / B. / C." headings, which markdown renders at
    the same level as the page's own section headers — so a sub-part of the buy
    pass looked exactly as important as the squad table. Here the numbered
    sections become the structure and everything inside them is demoted to sit
    under it, including the stray title a stage sometimes repeats at the top.
    """
    matches = list(SECTION_RE.finditer(advice_md))
    if not matches:
        return [("Advice", advice_md)]

    parts = []
    for i, match in enumerate(matches):
        title = match.group(1)
        end = matches[i + 1].start() if i + 1 < len(matches) else len(advice_md)
        body = _clean_stage_body(advice_md[match.end():end].strip(), title)
        parts.append((title, body))
    return parts


def _advice_html(advice_md: str) -> str:
    """The advice as collapsible sections, the plan open and the detail folded.

    Twenty thousand characters of reasoning is the right amount to have and the
    wrong amount to scroll past on a phone, so only the week's plan is open.
    """
    if not advice_md.strip():
        return "<p class='muted'>No advice generated yet.</p>"

    blocks = []
    for index, (title, body) in enumerate(_advice_parts(advice_md)):
        inner = markdown.markdown(body, extensions=["tables"])
        inner = inner.replace("<table>", "<div class='tablewrap'><table>")
        inner = inner.replace("</table>", "</table></div>")
        # The first section is the reconciled plan; the rest are the individual
        # passes it was built from. Publishing them as equals put a superseded
        # verdict next to the final one with nothing to tell them apart.
        if index:
            inner = (
                "<p class='supersede'>One pass's reasoning, before the plan reconciled "
                "them. Where this differs from the plan, the plan wins.</p>" + inner
            )
        label = title if index == 0 else f"Working — {title}"
        blocks.append(
            f"<details class='adv{' lead' if index == 0 else ''}'{' open' if index == 0 else ''}>"
            f"<summary>{html.escape(label)}</summary>"
            f"<div class='advbody'>{inner}</div>"
            "</details>"
        )
    return "\n".join(blocks)


def _headline(advice_md: str) -> str:
    """The single line the plan pass says matters most — the reason to open the page."""
    match = re.search(
        # Any letter prefix: the output spec's lettering shifts when sections
        # are added, and the heading text is what identifies it.
        r"^#{1,4}\s*(?:[A-Z]\.\s*)?The one thing that matters most.*?$\n+(.+?)(?:\n\s*\n|\Z)",
        advice_md,
        flags=re.MULTILINE | re.DOTALL | re.IGNORECASE,
    )
    if not match:
        return ""
    text = " ".join(match.group(1).split())
    text = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", html.escape(text))
    return f"<section class='headline'><span class='label'>Do this first</span><p>{text}</p></section>"


def build_site(data: dict, advice_md: str, generated_at: datetime, results: dict | None = None) -> str:
    budget = data["budget"].get("b") or 0
    squad = data["squad"]
    team_value = sum(p.get("mv") or 0 for p in squad)
    league_name = data["league"]["n"]
    budget_cls = "down" if budget < 0 else "up"
    rivals = data.get("rivals") or []
    my_rank = next((i for i, r in enumerate(rivals, 1) if r.get("is_me")), None)
    if my_rank:
        leader = rivals[0]["projected_points"]
        mine = next(r["projected_points"] for r in rivals if r.get("is_me"))
        gap = mine - leader
        gap_text = "leading" if gap >= 0 else f"{gap:.0f} behind leader"
        rank_block = (
            "<div><div class='label'>Projected rank</div>"
            f"<div class='hero-num'>{my_rank}<span class='of'>/{len(rivals)}</span></div>"
            f"<div class='deadline muted'>{gap_text}</div></div>"
        )
    else:
        rank_block = ""

    advice_html = _advice_html(advice_md)
    headline = _headline(advice_md)
    stamp = generated_at.strftime("%d.%m.%Y %H:%M")

    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex">
<title>Matchday Desk</title>
<link rel="icon" href="data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 100 100'><text y='.9em' font-size='90'>⚽</text></svg>">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Oswald:wght@500;600&display=swap" rel="stylesheet">
<style>
:root {{
  --paper: #faf7f0; --ink: #1d2733; --muted: #6b7480; --line: #e3ded2;
  --green: #1d7a3e; --red: #c02f1d; --amber: #a8730a; --card: #ffffff; --highlight: #fdf3d4;
}}
@media (prefers-color-scheme: dark) {{
  :root {{
    --paper: #14181d; --ink: #e8e4da; --muted: #8b92a0; --line: #2a313a;
    --green: #4cc472; --red: #e8604f; --amber: #e0a33a; --card: #1b2129; --highlight: #2c2a1c;
  }}
}}
* {{ box-sizing: border-box; margin: 0; }}
body {{
  background: var(--paper); color: var(--ink);
  font: 16px/1.55 -apple-system, "Segoe UI", Roboto, sans-serif;
  max-width: 680px; margin: 0 auto; padding: 20px 16px 60px;
}}
h1, h2, .hero-num {{ font-family: "Oswald", "Arial Narrow", sans-serif; text-transform: uppercase; letter-spacing: .04em; }}
header {{ display: flex; justify-content: space-between; align-items: baseline; gap: 4px 12px;
  flex-wrap: wrap; border-bottom: 3px solid var(--ink); padding-bottom: 10px; }}
h1 {{ font-size: 1.25rem; font-weight: 600; }}
.stamp {{ color: var(--muted); font-size: .78rem; white-space: nowrap; }}
.hero {{ display: flex; gap: 28px; padding: 22px 0 18px; border-bottom: 1px solid var(--line); flex-wrap: wrap; }}
.hero div {{ min-width: 130px; }}
.hero .label {{ font-size: .72rem; text-transform: uppercase; letter-spacing: .1em; color: var(--muted); }}
.hero-num {{ font-size: clamp(1.7rem, 9vw, 2.4rem); font-weight: 600; line-height: 1.1; font-variant-numeric: tabular-nums; }}
.hero-num.down {{ color: var(--red); }}
.hero-num.up {{ color: var(--green); }}
.deadline {{ font-size: .82rem; color: var(--red); margin-top: 2px; }}
.deadline.muted {{ color: var(--muted); }}
.of {{ font-size: 1.2rem; color: var(--muted); }}
h2 {{ font-size: .95rem; font-weight: 600; margin: 30px 0 10px; padding-left: 10px; border-left: 4px solid var(--ink); }}
.advice {{ font-size: .93rem; }}
.advice .tablewrap {{ overflow-x: auto; }}
details.adv {{
  background: var(--card); border: 1px solid var(--line); border-radius: 6px;
  margin-bottom: 8px; overflow: hidden;
}}
details.adv > summary {{
  cursor: pointer; list-style: none; padding: 11px 14px;
  font-family: "Oswald", "Arial Narrow", sans-serif; text-transform: uppercase;
  letter-spacing: .05em; font-size: .82rem;
  display: flex; align-items: center; justify-content: space-between; gap: 10px;
}}
details.adv > summary::-webkit-details-marker {{ display: none; }}
details.adv > summary::after {{
  content: "+"; font-family: -apple-system, sans-serif; font-size: 1.1rem;
  color: var(--muted); line-height: 1;
}}
details.adv[open] > summary::after {{ content: "–"; }}
details.adv[open] > summary {{ border-bottom: 1px solid var(--line); }}
details.adv > summary:hover {{ background: var(--highlight); }}
summary:focus-visible {{ outline: 2px solid var(--amber); outline-offset: -2px; }}
.advbody {{ padding: 12px 14px 14px; }}
.advbody > *:first-child {{ margin-top: 0; }}
.advice h4 {{
  font-family: "Oswald", "Arial Narrow", sans-serif; text-transform: uppercase;
  letter-spacing: .05em; font-size: .74rem; color: var(--muted);
  margin: 16px 0 6px; padding: 0; border: 0;
}}
.advbody > h4:first-child {{ margin-top: 0; }}
.advice p, .advice li {{ margin-bottom: 8px; }}
.advice ul, .advice ol {{ padding-left: 20px; }}
.advice table {{ width: 100%; border-collapse: collapse; font-size: .84rem; margin: 10px 0; }}
.advice th {{
  text-align: left; padding: 4px 10px 6px 0; border-bottom: 1px solid var(--ink);
  font-size: .7rem; text-transform: uppercase; letter-spacing: .06em; color: var(--muted);
  font-weight: 600; white-space: nowrap;
}}
.advice td {{
  padding: 7px 10px 7px 0; border-bottom: 1px solid var(--line);
  text-align: left; vertical-align: top;
}}
.advice th:last-child, .advice td:last-child {{ padding-right: 0; }}
.headline {{
  background: var(--card); border: 1px solid var(--line);
  border-left: 3px solid var(--green); border-radius: 6px;
  padding: 12px 14px; margin: 0 0 22px;
}}
.scorecard {{ display: flex; flex-wrap: wrap; gap: 10px; margin-bottom: 14px; }}
.sc {{
  flex: 1 1 88px; background: var(--card); border: 1px solid var(--line);
  border-radius: 6px; padding: 9px 11px;
}}
.sclabel {{
  font-size: .66rem; text-transform: uppercase; letter-spacing: .08em;
  color: var(--muted); white-space: nowrap;
}}
.scnum {{
  font-family: "Oswald", "Arial Narrow", sans-serif; font-size: 1.15rem;
  font-variant-numeric: tabular-nums; margin-top: 2px;
}}
.scnum.win {{ color: var(--green); }}
.scsub {{ display: block; font-family: -apple-system, sans-serif; font-size: .6rem; color: var(--muted); letter-spacing: 0; }}
tr.hdr th {{
  text-align: left; font-size: .66rem; text-transform: uppercase; letter-spacing: .07em;
  color: var(--muted); font-weight: 600; padding: 0 6px 6px; border-bottom: 1px solid var(--ink);
}}
tr.hdr th.num {{ text-align: right; }}
.supersede {{
  font-size: .76rem; color: var(--muted); font-style: italic;
  border-left: 2px solid var(--line); padding-left: 9px; margin-bottom: 12px;
}}
details.adv.lead {{ border-color: var(--ink); }}
details.adv.lead > summary {{ font-size: .9rem; }}
.headline .label {{
  font-family: "Oswald", "Arial Narrow", sans-serif; text-transform: uppercase;
  letter-spacing: .08em; font-size: .68rem; color: var(--muted); display: block; margin-bottom: 3px;
}}
.headline p {{ font-size: .95rem; line-height: 1.45; }}
.tablewrap {{ overflow-x: auto; }}
table.data {{ width: 100%; border-collapse: collapse; font-size: .88rem; }}
table.data td {{ padding: 8px 6px; border-bottom: 1px solid var(--line); vertical-align: top; }}
td.name {{ font-weight: 600; }}
td.name .sub {{ display: block; font-weight: 400; font-size: .74rem; color: var(--muted); }}
td.num {{ text-align: right; font-variant-numeric: tabular-nums; white-space: nowrap; }}
td.num.up {{ color: var(--green); }}
td.num.down {{ color: var(--red); }}
td.num .sub {{ display: block; font-weight: 400; font-size: .68rem; letter-spacing: .02em; color: var(--muted); }}
td.num .sub.up {{ color: var(--green); }}
td.num .sub.warn {{ color: var(--amber); }}
td.num .sub.down {{ color: var(--red); }}
td.num.pred {{ font-weight: 700; font-size: 1.02rem; }}
tr.rival.me td {{ background: var(--highlight); }}
td.rank {{ width: 1.8rem; color: var(--muted); font-variant-numeric: tabular-nums; }}

/* Lineup pitch — the one deliberately literal element on the page. */
.pitch {{
  background:
    repeating-linear-gradient(180deg, #1f5c37 0 44px, #1c5433 44px 88px);
  border: 2px solid rgba(255,255,255,.35); border-radius: 6px;
  padding: 16px 8px; display: flex; flex-direction: column; gap: 14px;
  position: relative; overflow: hidden;
}}
.pitch::before {{
  content: ""; position: absolute; left: 50%; top: 50%; width: 108px; height: 108px;
  transform: translate(-50%,-50%); border: 2px solid rgba(255,255,255,.28);
  border-radius: 50%; pointer-events: none;
}}
.pitch::after {{
  content: ""; position: absolute; left: 0; right: 0; top: 50%;
  border-top: 2px solid rgba(255,255,255,.28); pointer-events: none;
}}
.prow {{ display: flex; justify-content: space-evenly; gap: 4px; position: relative; z-index: 1; }}
.pp {{ text-align: center; width: 4.6rem; }}
.shirt {{
  width: 2.9rem; height: 2.9rem; margin: 0 auto 4px; border-radius: 50%;
  display: flex; align-items: center; justify-content: center;
  font-family: "Oswald", sans-serif; font-weight: 600; font-size: .95rem;
  color: #10241a; background: #f2f0e6; border: 2px solid rgba(255,255,255,.7);
  font-variant-numeric: tabular-nums; position: relative;
}}
.shirt.gk {{ background: #ffd166; border-color: #ffd166; }}
.shirt.empty {{ background: #b23b2c; color: #fff; }}
.face {{ width: 100%; height: 100%; border-radius: 50%; object-fit: cover;
  object-position: top center; background: #f2f0e6; }}
.face.blank {{ background: #d8d5c6; }}
.badge {{
  position: absolute; bottom: -5px; right: -6px; min-width: 1.5rem; padding: 0 3px;
  height: 1.05rem; border-radius: .55rem; background: #10241a; color: #fff;
  border: 1.5px solid rgba(255,255,255,.85);
  font-family: "Oswald", sans-serif; font-size: .68rem; line-height: 1.05rem;
  font-variant-numeric: tabular-nums;
}}
.pn {{ color: #fff; font-size: .74rem; font-weight: 600; line-height: 1.15;
  overflow-wrap: anywhere; text-shadow: 0 1px 2px rgba(0,0,0,.5); }}
.po {{ color: rgba(255,255,255,.75); font-size: .62rem; text-shadow: 0 1px 2px rgba(0,0,0,.5); }}
.pr {{ color: rgba(255,255,255,.6); font-size: .58rem; font-variant-numeric: tabular-nums;
  text-shadow: 0 1px 2px rgba(0,0,0,.5); }}
.pitchfoot {{ display: flex; justify-content: space-between; font-size: .8rem;
  color: var(--muted); margin-top: 6px; }}
.muted {{ color: var(--muted); }}
.note {{ color: var(--muted); font-size: .78rem; margin: -4px 0 8px; }}
.note.warnbox {{
  color: var(--ink); background: var(--highlight); border-left: 3px solid var(--amber);
  padding: 8px 10px; margin: 0 0 10px; border-radius: 3px;
}}
td.status {{ text-align: right; font-size: .76rem; text-transform: uppercase; letter-spacing: .05em; white-space: nowrap; }}
.status.in {{ color: var(--green); font-weight: 700; }}
.status.bench {{ color: var(--muted); }}
.status.out {{ color: var(--red); font-weight: 700; }}
footer {{ margin-top: 40px; font-size: .74rem; color: var(--muted); }}
</style>
</head>
<body>
<header>
  <h1>{html.escape(league_name)}</h1>
  <span class="stamp">updated {stamp}</span>
</header>

<section class="hero">
  <div>
    <div class="label">Budget</div>
    <div class="hero-num {budget_cls}">{eur_m(budget)}</div>
    {"<div class='deadline'>must be ≥ 0 by kickoff — sell!</div>" if budget < 0 else ""}
  </div>
  <div>
    <div class="label">Team value</div>
    <div class="hero-num">{eur_m(team_value)}</div>
  </div>
  {rank_block}
  {_deadline_block(data, generated_at)}
</section>

{headline}

<h2>Best XI — matchday {html.escape(str((data.get("matchday") or {}).get("day", "")))}</h2>
<p class="note">The lineup you can actually field, from the players you own right now — transfers are suggested separately under Advice.
Numbers are predicted points; <strong>vs</strong> = home match, <strong>at</strong> = away match.</p>
{_forced_sales_note(data.get("my_xi"))}
{_pitch(data.get("my_xi"))}

<h2>League projection</h2>
<p class="note">Every manager's current squad, run through the same model at its best legal formation.</p>
<div class="tablewrap"><table class="data">
{_rival_rows(data.get("rivals") or [])}
</table></div>

<h2>Advice</h2>
<p class="note">The plan is the answer. The three working sections below it are the separate passes it was reconciled from — kept so the reasoning is visible, not as advice to follow.</p>
<div class="advice">{advice_html}</div>

{_scorecard(results)}

<h2>Squad — predicted points, matchday {html.escape(str((data.get("matchday") or {}).get("day", "")))}</h2>
<div class="tablewrap"><table class="data">
{_squad_rows(squad)}
</table></div>

<h2>Market — best predicted points</h2>
<div class="tablewrap"><table class="data">
{_market_rows(data["market"])}
</table></div>

<footer>Predicted points = player's own per-90 scoring rate projected onto this fixture's
win and clean-sheet odds; the smaller range is his typical spread.
<strong>*</strong> marks thin data pulled toward the positional baseline.
Backtested over 9,199 past matches: single-match predictions carry a typical error of ~50 points,
so use them to <em>rank</em> players, not as forecasts.<br>
The word under each value change is where that player sits on his market value curve:
the last 3 days' daily rise measured against the 7 days before it.
<strong>cooling</strong> means still rising but at less than half the earlier pace — the top of
the arc forming, and the moment to sell into strength. Tap a value for the daily numbers.<br>
Data: Kickbase API + ligainsider.de · advice by Claude · not financial advice, just football</footer>
</body>
</html>
"""
