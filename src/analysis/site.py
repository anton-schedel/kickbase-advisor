"""Render the latest briefing data + advice into a static single-file page."""

import html
from datetime import datetime

import markdown


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


def _status_cell(p: dict) -> str:
    if p.get("injury"):
        inj = p["injury"]
        label = inj.get("status") or "verletzt"
        return f"<td class='status out' title='{html.escape(inj.get('news') or '')}'>✚ {html.escape(label)}</td>"
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
            + _trend_cell(ch.get("7d"))
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
            + _trend_cell(ch.get("7d"))
            + _pred_cell(p)
            + _status_cell(p)
            + "</tr>"
        )
    return "\n".join(rows)


def build_site(data: dict, advice_md: str, generated_at: datetime) -> str:
    budget = data["budget"].get("b") or 0
    squad = data["squad"]
    team_value = sum(p.get("mv") or 0 for p in squad)
    league_name = data["league"]["n"]
    budget_cls = "down" if budget < 0 else "up"
    advice_html = markdown.markdown(advice_md, extensions=["tables"])
    # Tables must scroll inside their own container, otherwise they stretch
    # the advice card and every paragraph clips at phone width.
    advice_html = advice_html.replace("<table>", "<div class='tablewrap'><table>")
    advice_html = advice_html.replace("</table>", "</table></div>")
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
  --green: #1d7a3e; --red: #c02f1d; --card: #ffffff;
}}
@media (prefers-color-scheme: dark) {{
  :root {{
    --paper: #14181d; --ink: #e8e4da; --muted: #8b92a0; --line: #2a313a;
    --green: #4cc472; --red: #e8604f; --card: #1b2129;
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
h2 {{ font-size: .95rem; font-weight: 600; margin: 30px 0 10px; padding-left: 10px; border-left: 4px solid var(--ink); }}
.advice {{ background: var(--card); border: 1px solid var(--line); border-radius: 6px; padding: 16px 18px; font-size: .93rem; }}
.advice .tablewrap {{ overflow-x: auto; }}
.advice h1, .advice h2, .advice h3 {{ font-size: .95rem; margin: 14px 0 6px; padding: 0; border: 0; }}
.advice p, .advice li {{ margin-bottom: 8px; }}
.advice ul, .advice ol {{ padding-left: 20px; }}
.advice table {{ border-collapse: collapse; font-size: .85rem; margin: 8px 0; }}
.advice th, .advice td {{ border: 1px solid var(--line); padding: 4px 8px; text-align: left; }}
.tablewrap {{ overflow-x: auto; }}
table.data {{ width: 100%; border-collapse: collapse; font-size: .88rem; }}
table.data td {{ padding: 8px 6px; border-bottom: 1px solid var(--line); vertical-align: top; }}
td.name {{ font-weight: 600; }}
td.name .sub {{ display: block; font-weight: 400; font-size: .74rem; color: var(--muted); }}
td.num {{ text-align: right; font-variant-numeric: tabular-nums; white-space: nowrap; }}
td.num.up {{ color: var(--green); }}
td.num.down {{ color: var(--red); }}
td.num.pred {{ font-weight: 700; font-size: 1.02rem; }}
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
</section>

<h2>Advice</h2>
<div class="advice">{advice_html}</div>

<h2>Squad — predicted points, matchday {html.escape(str((data.get("matchday") or {}).get("day", "")))}</h2>
<div class="tablewrap"><table class="data">
{_squad_rows(squad)}
</table></div>

<h2>Market — best predicted points</h2>
<div class="tablewrap"><table class="data">
{_market_rows(data["market"])}
</table></div>

<footer>Predicted points = player's own per-90 scoring rate projected onto this fixture's
win and clean-sheet odds. <strong>*</strong> marks thin data pulled toward the positional baseline.<br>
Data: Kickbase API + ligainsider.de · advice by Claude · not financial advice, just football</footer>
</body>
</html>
"""
