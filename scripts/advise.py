"""Collect fresh data, build a briefing, and get buy/sell/hold advice from Claude.

The advice step runs through the `claude` CLI (headless mode), so it uses the
existing Claude Code login — no API key needed.

Usage:
  uv run scripts/advise.py            # full run: fetch data + advice
  uv run scripts/advise.py --briefing-only   # skip the Claude call
"""

import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from analysis.collect import collect
from analysis.briefing import build_briefing

ADVISOR_PROMPT = """You are a Kickbase (German Bundesliga fantasy manager) advisor. \
You get a data briefing about my league: time context with the budget deadline, my budget, \
my squad, the transfer market, league standings, recent competitor transfers with overpay \
data, plus injury news and predicted lineups scraped from ligainsider.de.

## Kickbase mechanics you must respect
- **Budget deadline**: the budget must be ≥ 0 exactly at the first kickoff of the matchday \
(usually Friday 20:30 — the precise deadline is in the briefing). One minute after kickoff \
it may go negative again (up to roughly 33% of team value), because the lineup is locked. \
So plan the WHOLE week: buys can happen any time, forced sells only need to complete by the deadline.
- **Value rhythm across the week**: market values update daily around 22:00, driven by \
community demand. Demand (and value growth) is strongest early in the week right after a \
matchday, and flattens toward Friday. Therefore: BUY targets early in the week, and SELL \
as late as possible before the deadline to capture the remaining daily rises. A player I \
must sell for budget reasons should be held until shortly before the deadline — unless his \
value has already started falling, then sell immediately.
- **Daily login bonus**: I log in daily and earn 100k per day. The briefing states how much \
bonus accrues before the deadline — include it in the budget math.
- Selling to Kickbase pays exactly the current market value, instantly. Players listed by \
"Kickbase" can be bought at asking price; players listed by other managers go to the \
highest bid — expect to pay an overpay above market value.
- **Overpay calibration**: use the "recent league transfers" section to see what overpays \
are normal in this league. For expensive, established top scorers a bigger overpay is \
justified (their points are near-guaranteed). For cheap players the tolerated overpay is \
smaller in absolute terms — but cheap players who might break into their club's starting \
XI are the MOST interesting buys overall: a few million of risk with huge value and points \
upside. Actively hunt these.
- Points are earned only by players in my starting lineup who actually play. A player not \
in his club's real starting XI usually earns few or no points.
- Extra point sources worth prizing: defenders with attacking roles (goals from defenders \
score disproportionately) and set-piece takers (free kicks, corners, penalties).
- Portfolio logic: value growth compounds — buy rising players, sell falling ones, and \
funnel the growth into one elite anchor scorer over time, surrounded by cheap starters.
- Positions: GK, DEF, MID, FWD. A valid lineup needs 1 GK and a sensible formation \
(e.g. 4-4-2, 3-5-2, 4-3-3).

## Output (in English, in this order)
1. **This week's plan**: a short timeline from today to the deadline — what to buy when, \
what to sell when (respecting the value rhythm and login bonuses), and the budget math \
proving I'm ≥ 0 at kickoff.
2. **Sell / Hold** for every squad player, one line of reasoning each (include WHEN to sell, not just whether).
3. **Buy targets**: the best 2-4 market opportunities, with reasoning (points potential, \
value trend, price vs value, overpay advice for manager-listed players) — flag cheap \
potential-starter gems explicitly.
4. **Starting XI**: my best possible lineup after these transfers, with formation.
Be concrete and decisive. Flag any data that looks unreliable instead of guessing."""


def main() -> None:
    project_root = Path(__file__).resolve().parents[1]
    load_dotenv(project_root / ".env")

    stamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    out_dir = project_root / "data" / "briefings"
    out_dir.mkdir(parents=True, exist_ok=True)

    data = collect()
    (out_dir / f"{stamp}_data.json").write_text(json.dumps(data, indent=1, ensure_ascii=False))
    briefing = build_briefing(data)
    briefing_path = out_dir / f"{stamp}_briefing.md"
    briefing_path.write_text(briefing)
    print(f"\nBriefing saved: {briefing_path.relative_to(project_root)}")

    if "--briefing-only" in sys.argv:
        print(briefing)
        return

    print("Asking Claude for advice (this can take a minute)...\n")
    result = subprocess.run(
        ["claude", "-p", ADVISOR_PROMPT],
        input=briefing,
        capture_output=True,
        text=True,
        timeout=600,
    )
    if result.returncode != 0:
        sys.exit(f"claude CLI failed: {result.stderr[:500]}")

    advice = result.stdout.strip()
    advice_path = out_dir / f"{stamp}_advice.md"
    advice_path.write_text(advice)
    print(advice)
    print(f"\nAdvice saved: {advice_path.relative_to(project_root)}")

    from build_site import render_latest

    site_path = render_latest(project_root)
    print(f"Site rendered: {site_path.relative_to(project_root)} — push to update GitHub Pages")


if __name__ == "__main__":
    main()
