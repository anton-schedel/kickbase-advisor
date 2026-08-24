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
You get a data briefing about my league: my budget, my squad, the transfer market, \
league standings, plus injury news and predicted lineups scraped from ligainsider.de.

Kickbase mechanics you must respect:
- A negative budget MUST be non-negative by the next matchday kickoff, otherwise players are force-sold. Selling to Kickbase pays exactly the market value, instantly.
- Points are earned only by players in my starting lineup who actually play. A player not in his club's real starting XI usually earns few or no points.
- Market values move daily based on demand; buying rising players and selling falling ones grows team value, which funds better players later.
- Positions: GK, DEF, MID, FWD. A valid lineup needs 1 GK and a sensible formation (e.g. 4-4-2, 3-5-2, 4-3-3).
- Players listed by "Kickbase" can be bought at asking price; players listed by other managers go to the highest bid above price.

Give me, in this order and in English:
1. **Budget fix**: exactly which player(s) to sell to get the budget non-negative with the least loss of future points and value growth. Consider injury status, predicted-starter status, and value trend.
2. **Sell / Hold** for every other squad player, one line of reasoning each.
3. **Buy targets**: the best 2-4 market opportunities I can actually afford after the sales, with reasoning (points potential, value trend, price vs market value).
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
