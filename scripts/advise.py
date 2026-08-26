"""Collect fresh data, build a briefing, and get buy/sell/hold advice from Claude.

The advice runs through the `claude` CLI (headless mode), so it uses the
existing Claude Code login — no API key needed. It is split into four focused
calls (sell/hold, buys, lineup, week plan); see src/advisor/prompts.py.

Usage:
  uv run scripts/advise.py            # full run: fetch data + advice
  uv run scripts/advise.py --briefing-only   # skip the Claude calls
"""

import json
import sys
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from analysis.collect import collect
from analysis.briefing import briefing_sections, compose
from advisor.run import run_stages


def archive_predictions(project_root: Path, stamp: str, data: dict) -> None:
    """Save this run's forecasts so they can be scored once the matchday is played.

    The backtest could not measure the odds-driven half of the model; this is
    how that gets settled, with real results.
    """
    matchday = (data.get("matchday") or {}).get("day")
    if matchday is None:
        return
    rows = []
    for player in data["squad"] + data["market"]:
        prediction = player.get("prediction")
        if not prediction or prediction.get("note") == "injured/suspended":
            continue
        seasons = player.get("history") or []
        rows.append(
            {
                "player_id": player["i"],
                "name": player["n"],
                "position": player["position"],
                "predicted": round(prediction["points"], 1),
                # The baseline the backtest showed is hard to beat.
                "naive": seasons[-1]["avg"] if seasons else None,
                # 50/50 blend was the best blind performer; scored alongside the
                # model so real results decide which to trust.
                "blend": (
                    round(0.5 * prediction["points"] + 0.5 * seasons[-1]["avg"], 1)
                    if seasons
                    else None
                ),
                "expected_goals": round(prediction.get("expected_goals") or 0, 3),
                "predicted_starter": player.get("predicted_starter"),
                "p_win": (player.get("fixture") or {}).get("p_win"),
            }
        )
    archive_dir = project_root / "data" / "predictions"
    archive_dir.mkdir(parents=True, exist_ok=True)
    (archive_dir / f"{stamp}_md{matchday}.json").write_text(
        json.dumps({"matchday": matchday, "generated": stamp, "predictions": rows}, ensure_ascii=False)
    )
    print(f"Archived {len(rows)} predictions for matchday {matchday}")


def main() -> None:
    project_root = Path(__file__).resolve().parents[1]
    load_dotenv(project_root / ".env")

    stamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    out_dir = project_root / "data" / "briefings"
    out_dir.mkdir(parents=True, exist_ok=True)

    data = collect()
    (out_dir / f"{stamp}_data.json").write_text(json.dumps(data, indent=1, ensure_ascii=False))
    archive_predictions(project_root, stamp, data)
    sections = briefing_sections(data)
    briefing = compose(sections, title=f"Kickbase Briefing — {data['league']['n']}")
    briefing_path = out_dir / f"{stamp}_briefing.md"
    briefing_path.write_text(briefing)
    print(f"\nBriefing saved: {briefing_path.relative_to(project_root)}")

    if "--briefing-only" in sys.argv:
        print(briefing)
        return

    print("Asking Claude for advice — four focused passes, a few minutes each...\n", flush=True)
    stage_dir = out_dir / f"{stamp}_stages"

    def save_stage(key: str, answer: str) -> None:
        stage_dir.mkdir(exist_ok=True)
        (stage_dir / f"{key}.md").write_text(answer)

    advice, _ = run_stages(sections, progress=lambda m: print(m, flush=True), on_stage=save_stage)

    if advice:
        advice_path = out_dir / f"{stamp}_advice.md"
        advice_path.write_text(advice)
        print(advice)
        print(f"\nAdvice saved: {advice_path.relative_to(project_root)}")

    # The dashboard is rebuilt either way: fresh data is useful on its own, and
    # a slow advice step must not leave the site stale.
    from build_site import render_latest

    site_path = render_latest(project_root)
    print(f"Site rendered: {site_path.relative_to(project_root)} — push to update GitHub Pages")


if __name__ == "__main__":
    main()
