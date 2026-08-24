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
- Selling to Kickbase pays exactly the current market value, instantly.
- **Kickbase-listed players are BLIND AUCTIONS with a countdown** (the "Auction ends" \
column). When the countdown expires, the player goes to the manager with the highest bid; \
if nobody bids, nobody gets him. Bids are blind — you cannot see rivals' amounts — and you \
pay exactly what you bid, so the game is to bid the MINIMUM that still wins. For every \
recommended auction target, give a concrete bid in € and justify the margin.
- **Bid sizing for auctions**: anchor on the recent-league-transfers section — the overpay \
percentages there are what actually wins in THIS league. Then scale by expected \
competition: an obvious target (predicted starter, steeply rising value, high ØPts — the \
players everyone sees) needs an aggressive margin, roughly 5–15% over value, and for \
expensive proven scorers ("big boys") a big overpay is acceptable because their points are \
near-guaranteed. An unnoticed player (flat value, no hype, not obviously a starter) often \
gets ZERO competing bids — bid asking price or +1–2% at most. Never bid above the price at \
which the deal stops making sense; state that walk-away number too. Bids near expiry are \
placed against the value AFTER the nightly 22:00 update — factor a rising player's next \
update into the margin.
- **Manager-listed players are negotiations, not auctions** (no countdown — "seller \
decides"). The seller will NEVER accept plain market value: he can always sell to Kickbase \
for exactly that, instantly. Any offer must beat his alternative of holding a rising asset \
or listing it. Realistic range: start around +5–8% over current value, expect to close \
desirable starters at +8–15%; for a player whose value is rising fast the seller rationally \
holds out for more — either pay up or wait for his momentum to flatten. I can also talk to \
the seller directly in the league; suggest a negotiation angle when useful. The asking \
price already encodes the seller's desired overpay — compare price vs value in the table.
- Cheap players who might break into their club's starting XI are the MOST interesting \
buys overall: a few million of risk with huge value and points upside. Actively hunt these.
- Points are earned only by players in my starting lineup who actually play. A player not \
in his club's real starting XI usually earns few or no points.
- **ALWAYS field 11 players**: every empty lineup slot costs a -100 point penalty. A 500k \
filler player (the minimum market value) who scores nothing still beats an empty slot by \
100 points. Early in the season, cheap fillers are the correct way to complete the XI \
until budget growth affords 11 real starters — then upgrade fillers one by one.
- **Offers to rivals**: I can bid on players in other managers' squads even when they are \
not listed on the market. They may accept, decline, hold, or sell to the market instead — \
treat such offers as opportunistic, never as a plan the budget depends on. The same applies \
in reverse: rivals can bid on my players, and holding a rising player means fielding those \
offers.
- **Hidden gems beat crowded trades**: a player whose value is already rising steeply is \
visible to every manager in the community — the profit is half gone and the demand is \
priced in. The real edge is players where the upside is NOT yet obvious: predicted \
starters whose value is still flat or barely moving, backups about to inherit a starting \
role from an injured or suspended player (check the injury list against lineups), new \
signings the community hasn't noticed, and players returning from injury whose value \
crashed. Actively scan the market for "in the predicted XI but value not moving yet" — \
that combination is the strongest buy signal in this data.
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
value trend, price vs value) — flag cheap potential-starter gems explicitly. For each \
target state concrete numbers: for auctions the exact bid in € and the walk-away maximum; \
for manager-listed players the opening offer, the realistic closing price, and the \
walk-away maximum. Mind each auction's countdown when sequencing the week plan.
4. **Starting XI**: my best possible lineup after these transfers, with formation — always \
a complete XI (buy 500k fillers if needed rather than leaving a slot empty at -100 points).
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
